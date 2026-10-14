"""Regras de gestão integradas ao PDV. Valores financeiros novos em centavos.

Não reconstrói caixa histórico a partir de vendas: saldos precisam ser conferidos.
Todas as escritas compostas utilizam uma transação SQLite única.
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import csv
import hashlib
import json
import math
import secrets
import sqlite3
import unicodedata
import uuid
import database as db


class ErroGestao(ValueError):
    pass


USUARIO = 'Sistema local'
# Nenhum perfil privilegiado por padrão: enquanto ninguém se autenticar, o
# sistema não libera nenhuma operação protegida. O perfil só é definido por
# gestao.autenticar() após a verificação da senha do usuário.
PERFIL = None
PERMISSOES = {
    'gerente': {'venda', 'estoque', 'financeiro', 'configurar', 'credito', 'estornar'},
    'caixa': {'venda'}, 'estoque': {'estoque'},
    'financeiro': {'financeiro', 'credito'},
}
# Política básica de fiado: R$ 200 de limite, 15 dias de prazo e 1% de
# juros/multa por dia de atraso. É o padrão para clientes sem política própria.
POLITICA_PADRAO = {'limite_credito': 200, 'prazo_dias': 15, 'juros_dia': 1, 'multa_dia': 1}


def permitir(acao):
    if acao not in PERMISSOES.get(PERFIL, set()):
        raise ErroGestao('Seu perfil não tem permissão para esta operação.')


def centavos(valor):
    try:
        numero = Decimal(str(valor).replace(',', '.'))
        if not numero.is_finite():
            raise ValueError()
        return int((numero * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        raise ErroGestao('Informe um valor monetário válido.')


def centavos_itens(itens):
    """Soma o valor de itens (com 'preco_unitario' e 'quantidade') em centavos,
    arredondando item a item — exatamente a mesma regra usada por
    registrar_venda, para o PDV e o back-end nunca divergirem por
    arredondamento (ex.: 0,185 kg × R$ 45,00)."""
    total = 0
    for it in itens:
        total += centavos(Decimal(str(it['preco_unitario'])) * Decimal(str(it['quantidade'])))
    return total


def custo_medio_entrada(quantidade_antiga, custo_antigo, quantidade_entrada, custo_entrada):
    """Custo médio após uma entrada de mercadoria/produção, sem dividir por zero.

    Política para estoque negativo: se o estoque anterior NÃO é positivo, não
    existe base confiável para ponderar custo (estoque negativo é erro de
    registro, não inventário real) — então assume o custo da própria entrada,
    que é um valor documentado. Não usa divisor fictício nem custo inventado.
    Com estoque anterior positivo, faz a média ponderada normal."""
    q_ant = float(quantidade_antiga or 0)
    q_ent = float(quantidade_entrada or 0)
    if q_ant <= 0:
        return float(custo_entrada or 0)
    return (q_ant * float(custo_antigo or 0) + q_ent * float(custo_entrada or 0)) / (q_ant + q_ent)


def quantidade(valor):
    try:
        n = float(str(valor).replace(',', '.'))
        if not math.isfinite(n) or n <= 0:
            raise ValueError()
        n=round(n,3)
        if n<=0: raise ValueError()
        return n
    except (TypeError, ValueError):
        raise ErroGestao('Quantidade deve ser maior que zero.')


def data_iso(valor):
    try:
        return date.fromisoformat(str(valor)).isoformat()
    except ValueError:
        raise ErroGestao('Data inválida. Use AAAA-MM-DD.')


def normalizar(texto):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', str(texto))
                          if not unicodedata.combining(c)).casefold().split())


@contextmanager
def transacao():
    conn = db.get_conn()
    try:
        conn.execute('BEGIN IMMEDIATE')
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def consultar(sql, params=()):
    conn = db.get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def auditar(conn, acao, entidade, referencia='', detalhes=None):
    conn.execute('INSERT INTO auditoria(usuario,acao,entidade,referencia,detalhes) VALUES(?,?,?,?,?)',
                 (USUARIO, acao, entidade, str(referencia), json.dumps(detalhes or {}, ensure_ascii=False)))


def migrar(conn):
    conn.executescript(Path(__file__).with_name('gestao_schema.sql').read_text(encoding='utf-8'))
    campos = {
        'produtos': {'sku': 'TEXT', 'perecivel': 'INTEGER NOT NULL DEFAULT 0', 'fornecedor': "TEXT NOT NULL DEFAULT ''"},
        'clientes': {'limite_credito': 'REAL', 'prazo_dias': 'INTEGER', 'juros_dia': 'REAL', 'multa_dia': 'REAL'},
        'vendas': {'cancelada': 'INTEGER NOT NULL DEFAULT 0', 'chave_operacao': 'TEXT', 'usuario': "TEXT NOT NULL DEFAULT 'Legado'"},
        'itens_venda': {'custo_unitario': 'REAL', 'nome_original': 'TEXT'},
        'pagamentos_fiado': {'tipo': "TEXT NOT NULL DEFAULT 'legado'", 'encargos_centavos': 'INTEGER NOT NULL DEFAULT 0',
                             'chave_operacao': 'TEXT', 'estornado': 'INTEGER NOT NULL DEFAULT 0', 'movimento_id': 'INTEGER',
                             'taxa_centavos': 'INTEGER NOT NULL DEFAULT 0',
                             'usuario': "TEXT NOT NULL DEFAULT 'Legado'"},
        'consumo_interno': {'responsavel': "TEXT NOT NULL DEFAULT 'Legado'", 'centro_custo': "TEXT NOT NULL DEFAULT ''", 'chave': 'TEXT'},
        'perdas': {'responsavel': "TEXT NOT NULL DEFAULT 'Legado'", 'chave': 'TEXT'},
        'producoes': {'responsavel': "TEXT NOT NULL DEFAULT 'Legado'", 'validade': 'TEXT', 'rendimento_real': 'REAL', 'chave': 'TEXT'},
    }
    for tabela, colunas in campos.items():
        existentes = {r['name'] for r in conn.execute(f'PRAGMA table_info({tabela})')}
        for nome, definicao in colunas.items():
            if nome not in existentes:
                conn.execute(f'ALTER TABLE {tabela} ADD COLUMN {nome} {definicao}')
    conn.execute("UPDATE produtos SET sku='INT-' || printf('%06d',id) WHERE sku IS NULL OR trim(sku)=''")
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_prod_sku ON produtos(sku)')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_venda_chave ON vendas(chave_operacao)')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_receb_chave ON pagamentos_fiado(chave_operacao)')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_consumo_chave ON consumo_interno(chave)')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_perda_chave ON perdas(chave)')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_producao_chave ON producoes(chave)')
    conn.executescript('''
      CREATE TRIGGER IF NOT EXISTS produto_sku_interno AFTER INSERT ON produtos
      WHEN NEW.sku IS NULL OR trim(NEW.sku)=''
      BEGIN UPDATE produtos SET sku='INT-' || printf('%06d',NEW.id) WHERE id=NEW.id; END;
      CREATE TRIGGER IF NOT EXISTS auditar_preco_produto AFTER UPDATE OF preco_venda ON produtos
      WHEN OLD.preco_venda != NEW.preco_venda
      BEGIN INSERT INTO auditoria(usuario,acao,entidade,referencia,detalhes)
        VALUES(usuario_atual(),'preco','produto',NEW.id,
          json_object('anterior',OLD.preco_venda,'novo',NEW.preco_venda)); END;
      CREATE TRIGGER IF NOT EXISTS auditar_estoque_produto AFTER UPDATE OF quantidade_estoque ON produtos
      WHEN OLD.quantidade_estoque != NEW.quantidade_estoque
      BEGIN INSERT INTO auditoria(usuario,acao,entidade,referencia,detalhes)
        VALUES(usuario_atual(),'saldo_estoque','produto',NEW.id,
          json_object('anterior',OLD.quantidade_estoque,'novo',NEW.quantidade_estoque)); END;
      CREATE TRIGGER IF NOT EXISTS auditoria_nao_alterar BEFORE UPDATE ON auditoria
      BEGIN SELECT RAISE(ABORT,'Auditoria não pode ser alterada'); END;
      CREATE TRIGGER IF NOT EXISTS auditoria_nao_apagar BEFORE DELETE ON auditoria
      BEGIN SELECT RAISE(ABORT,'Auditoria não pode ser apagada'); END;
    ''')
    conn.execute("INSERT OR IGNORE INTO contas_financeiras(id,nome,tipo) VALUES(1,'Caixa da loja','dinheiro')")
    conn.execute("INSERT OR IGNORE INTO contas_financeiras(id,nome,tipo) VALUES(2,'Banco / PIX','banco')")
    conn.execute("INSERT OR IGNORE INTO gestao_config(chave,valor) VALUES('politica_fiado',?)", (json.dumps(POLITICA_PADRAO),))
    if not conn.execute("SELECT 1 FROM gestao_config WHERE chave='migracao_v1'").fetchone():
        # Sem vencimentos inventados e sem reclassificar ajustes antigos como dinheiro.
        for cli in conn.execute('SELECT id FROM clientes').fetchall():
            pagamentos = centavos(conn.execute('SELECT COALESCE(SUM(valor),0) FROM pagamentos_fiado WHERE cliente_id=?', (cli['id'],)).fetchone()[0])
            for v in conn.execute("SELECT * FROM vendas WHERE cliente_id=? AND forma_pagamento='fiado' ORDER BY data_hora,id", (cli['id'],)).fetchall():
                total = centavos(v['valor_total'])
                recebido = min(total, max(0, pagamentos))
                pagamentos -= recebido
                conn.execute('INSERT OR IGNORE INTO titulos_receber(venda_id,cliente_id,valor_centavos,recebido_centavos,legado) VALUES(?,?,?,?,1)',
                             (v['id'], cli['id'], total, recebido))
        conn.execute("INSERT INTO gestao_config(chave,valor) VALUES('migracao_v1',?)", (datetime.now().isoformat(timespec='seconds'),))
        auditar(conn, 'migracao', 'sistema', detalhes={'caixa_historico': 'não inferido', 'custos_antigos': 'não inferidos'})
    if not conn.execute("SELECT 1 FROM gestao_config WHERE chave='politica_padrao_v2'").fetchone():
        # Uma única vez: fixa a política padrão (200/15/1/1) e completa os
        # clientes sem política configurada com esses valores, sem mexer em
        # quem já tinha limite/prazo/juros próprios definidos.
        conn.execute("INSERT OR REPLACE INTO gestao_config(chave,valor) VALUES('politica_fiado',?)", (json.dumps(POLITICA_PADRAO),))
        conn.execute(
            "UPDATE clientes SET limite_credito=COALESCE(limite_credito,?), "
            "prazo_dias=COALESCE(prazo_dias,?), juros_dia=COALESCE(juros_dia,?), "
            "multa_dia=COALESCE(multa_dia,?) WHERE ativo=1",
            (POLITICA_PADRAO['limite_credito'], POLITICA_PADRAO['prazo_dias'],
             POLITICA_PADRAO['juros_dia'], POLITICA_PADRAO['multa_dia']))
        conn.execute("INSERT INTO gestao_config(chave,valor) VALUES('politica_padrao_v2',?)", (datetime.now().isoformat(timespec='seconds'),))
        auditar(conn, 'migracao', 'sistema', detalhes={'politica_padrao_v2': POLITICA_PADRAO})


def config(chave, padrao=None, conn=None):
    if conn is None:
        rows = consultar('SELECT valor FROM gestao_config WHERE chave=?', (chave,))
        return json.loads(rows[0]['valor']) if rows else padrao
    r = conn.execute('SELECT valor FROM gestao_config WHERE chave=?', (chave,)).fetchone()
    return json.loads(r[0]) if r else padrao


def salvar_config(chave, valor):
    permitir('configurar')
    with transacao() as c:
        c.execute('INSERT OR REPLACE INTO gestao_config(chave,valor) VALUES(?,?)', (chave, json.dumps(valor)))
        auditar(c, 'configurar', 'config', chave, {'valor': valor})


def politica_cliente(c, cliente_id):
    r = c.execute('SELECT * FROM clientes WHERE id=? AND ativo=1', (cliente_id,)).fetchone()
    if not r:
        raise ErroGestao('Cliente não encontrado ou inativo.')
    padrao = config('politica_fiado', {}, c)
    return {k: r[k] if r[k] is not None else padrao.get(k) for k in ('limite_credito','prazo_dias','juros_dia','multa_dia')}


def salvar_politica(cliente_id, limite_credito, prazo_dias, juros_dia, multa_dia):
    permitir('credito')
    limite = centavos(limite_credito) / 100
    prazo = int(prazo_dias)
    juros, multa = float(str(juros_dia).replace(',','.')), float(str(multa_dia).replace(',','.'))
    if limite < 0 or prazo < 0 or not all(math.isfinite(x) and x >= 0 for x in (juros, multa)):
        raise ErroGestao('Limite, prazo e encargos não podem ser negativos.')
    dados = dict(limite_credito=limite, prazo_dias=prazo, juros_dia=juros, multa_dia=multa)
    with transacao() as c:
        if cliente_id:
            c.execute('UPDATE clientes SET limite_credito=?,prazo_dias=?,juros_dia=?,multa_dia=? WHERE id=?',
                      (limite,prazo,juros,multa,cliente_id))
        else:
            permitir('configurar')
            c.execute("INSERT OR REPLACE INTO gestao_config(chave,valor) VALUES('politica_fiado',?)", (json.dumps(dados),))
        auditar(c, 'politica_fiado', 'cliente', cliente_id or 'padrao', dados)


def saldo_cliente(c, cliente_id):
    a = c.execute("SELECT COALESCE(SUM(valor_total),0) FROM vendas WHERE cliente_id=? AND forma_pagamento='fiado' AND cancelada=0", (cliente_id,)).fetchone()[0]
    b = c.execute('SELECT COALESCE(SUM(valor),0) FROM pagamentos_fiado WHERE cliente_id=? AND estornado=0', (cliente_id,)).fetchone()[0]
    return centavos(a) - centavos(b)


def movimento(c, conta_id, valor, categoria, descricao, origem, referencia, chave=None, data=None):
    if not valor:
        return None
    conta = c.execute('SELECT * FROM contas_financeiras WHERE id=?', (conta_id,)).fetchone()
    if not conta:
        raise ErroGestao('Selecione uma conta financeira válida.')
    data = data_iso(data or date.today().isoformat())
    if data < conta['data_base']:
        raise ErroGestao('Data anterior à abertura desta conta. Confira o saldo inicial em vez de duplicar o histórico.')
    cur = c.execute('INSERT INTO movimentos_financeiros(conta_id,valor_centavos,data,categoria,descricao,origem,referencia,chave,usuario) VALUES(?,?,?,?,?,?,?,?,?)',
                    (conta_id, int(valor), data, categoria, descricao, origem, str(referencia), chave or uuid.uuid4().hex, USUARIO))
    auditar(c, 'movimento', 'financeiro', cur.lastrowid, {'centavos': valor, 'conta': conta_id})
    return cur.lastrowid


def forma_normalizada(forma):
    f = normalizar(forma).replace(' ', '_')
    return {'cartao_de_credito':'cartao_credito','cartao_de_debito':'cartao_debito'}.get(f, f)


def entrada_pagamento(c, forma, valor, origem, referencia, taxa=0, conta_id=None):
    forma = forma_normalizada(forma)
    if forma in ('cartao_credito','cartao_debito','voucher'):
        c.execute('INSERT INTO recebiveis_cartao(origem,referencia,bruto_centavos,taxa_centavos,previsto) VALUES(?,?,?,?,?)',
                  (origem,str(referencia),valor,taxa,date.today().isoformat()))
        return None
    if forma not in ('dinheiro','pix','transferencia'):
        raise ErroGestao('Escolha Dinheiro, Pix, transferência ou cartão; forma indefinida não pode movimentar caixa.')
    conta_id = conta_id or (1 if forma == 'dinheiro' else 2)
    return movimento(c,conta_id,valor-taxa,'Recebimento de fiado' if origem=='fiado' else 'Venda à vista',
                     f'{origem} #{referencia}',origem,referencia)


def baixar_estoque(c, produto_id, qtd, origem, referencia, permitir_vencido=False, lote_id=None, permitir_negativo=False):
    qtd = quantidade(qtd)
    p = c.execute('SELECT * FROM produtos WHERE id=? AND ativo=1', (produto_id,)).fetchone()
    if not p:
        raise ErroGestao('Produto não encontrado ou inativo.')
    if not permitir_negativo and qtd > p['quantidade_estoque'] + .00001:
        raise ErroGestao(f'Estoque insuficiente de {p["nome"]}: disponível {p["quantidade_estoque"]:g}.')
    lotes = c.execute('SELECT * FROM lotes_validade WHERE produto_id=? AND quantidade>0 ORDER BY data_validade IS NULL,data_validade,id', (produto_id,)).fetchall()
    if not permitir_negativo and sum(l['quantidade'] for l in lotes) > p['quantidade_estoque'] + .001:
        raise ErroGestao(f'Lotes de {p["nome"]} excedem o estoque. Faça a conferência antes de continuar.')
    hoje = date.today().isoformat()
    vencidos = sum(l['quantidade'] for l in lotes if l['data_validade'] and l['data_validade'] < hoje)
    if not permitir_negativo and not permitir_vencido and qtd > p['quantidade_estoque']-vencidos+.00001:
        raise ErroGestao(f'{p["nome"]}: saldo disponível contém produtos vencidos. Registre a perda do lote.')
    if lote_id:
        selecionados = [l for l in lotes if l['id'] == lote_id]
        if not selecionados:
            raise ErroGestao('O lote selecionado não pertence a este produto ou não tem saldo.')
        lote_sel = selecionados[0]
        # Consumo/produção/venda não podem usar lote vencido — mesmo que haja
        # outro lote válido. Perda (permitir_vencido) pode, para dar baixa.
        if not permitir_vencido and lote_sel['data_validade'] and lote_sel['data_validade'] < hoje:
            raise ErroGestao(f'{p["nome"]}: o lote escolhido venceu em {lote_sel["data_validade"]}. '
                             'Registre a perda desse lote ou escolha um lote válido.')
        if qtd > lote_sel['quantidade'] + .00001:
            raise ErroGestao('Quantidade indisponível no lote selecionado.')
        lotes = [lote_sel]
    elif not permitir_vencido:
        lotes = [l for l in lotes if not l['data_validade'] or l['data_validade'] >= hoje]
    if p['perecivel'] and not permitir_negativo and not permitir_vencido and sum(l['quantidade'] for l in lotes if l['data_validade'])+.00001 < qtd:
        raise ErroGestao(f'{p["nome"]}: cadastre a validade do estoque perecível antes da saída.')
    restante = qtd
    for lote in lotes:
        usar = min(restante,lote['quantidade'])
        if usar <= 0: break
        c.execute('UPDATE lotes_validade SET quantidade=round(quantidade-?,3) WHERE id=?',(usar,lote['id']))
        c.execute('INSERT INTO baixas_lotes(lote_id,quantidade,origem,referencia) VALUES(?,?,?,?)',(lote['id'],usar,origem,str(referencia)))
        restante = round(restante-usar,3)
    c.execute('UPDATE produtos SET quantidade_estoque=round(quantidade_estoque-?,3) WHERE id=?',(qtd,produto_id))
    c.execute("INSERT INTO movimentacoes_estoque(produto_id,tipo,quantidade,observacao) VALUES(?,'saida',?,?)",(produto_id,qtd,f'{origem} #{referencia}'))
    return dict(p)


def registrar_venda(itens, forma_pagamento='dinheiro', desconto=0, cliente_id=None, taxa_paga=0,
                    voucher_marca=None, chave_operacao=None, pagamentos=None,total_esperado=None):
    permitir('venda')
    if not itens: raise ErroGestao('A venda precisa ter itens.')
    chave_operacao = chave_operacao or uuid.uuid4().hex
    with transacao() as c:
        existente = c.execute('SELECT * FROM vendas WHERE chave_operacao=?',(chave_operacao,)).fetchone()
        if existente:
            return dict(existente)
        if config('exigir_caixa_aberto', True, c) and not c.execute('SELECT id FROM sessoes_caixa WHERE fechamento IS NULL').fetchone():
            raise ErroGestao('Abra o caixa antes de iniciar as vendas, em Financeiro → Abrir caixa.')
        processados, bruto = [], 0
        for item in itens:
            qtd = quantidade(item['quantidade'])
            p = c.execute('SELECT * FROM produtos WHERE id=? AND ativo=1',(item['produto_id'],)).fetchone()
            if not p: raise ErroGestao('Produto não encontrado ou inativo.')
            promocao = c.execute("SELECT MIN(preco) FROM promocoes WHERE produto_id=? AND inicio<=date('now','localtime') AND fim>=date('now','localtime')",(p['id'],)).fetchone()[0]
            preco = min(p['preco_venda'],promocao) if promocao is not None else p['preco_venda']
            bruto += centavos(Decimal(str(preco))*Decimal(str(qtd)))
            processados.append((p,qtd,preco))
        desc, taxa = centavos(desconto), centavos(taxa_paga)
        if desc < 0 or desc > bruto or taxa < 0 or taxa > bruto-desc:
            raise ErroGestao('Desconto ou taxa inválidos.')
        total = bruto-desc
        if total_esperado is not None and centavos(total_esperado)!=total:
            raise ErroGestao('O preço vigente mudou ou há diferença de arredondamento. Confira o carrinho antes de receber o pagamento.')
        if pagamentos:
            partes = [(forma_normalizada(x['forma']),centavos(x['valor'])) for x in pagamentos]
            if any(v<=0 or f=='fiado' for f,v in partes) or sum(v for f,v in partes)!=total:
                raise ErroGestao('A soma dos pagamentos deve ser igual ao total. Divisão com fiado não é permitida.')
            forma_pagamento='misto'
        else:
            partes=[(forma_normalizada(forma_pagamento),total)]
            forma_pagamento=partes[0][0]
        politica = None
        if forma_pagamento=='fiado':
            politica=politica_cliente(c,cliente_id)
            if politica['limite_credito'] is None or politica['prazo_dias'] is None:
                raise ErroGestao('Configure prazo e limite de crédito do cliente antes de vender fiado.')
            if max(0,saldo_cliente(c,cliente_id))+total > centavos(politica['limite_credito']):
                raise ErroGestao('Venda excede o limite de crédito. Solicite revisão da política ao gerente.')
        v=c.execute('INSERT INTO vendas(valor_total,desconto,forma_pagamento,cliente_id,taxa_paga,voucher_marca,chave_operacao,usuario) VALUES(?,?,?,?,?,?,?,?)',
                    (total/100,desc/100,forma_pagamento,cliente_id,taxa/100,voucher_marca,chave_operacao,USUARIO)).lastrowid
        permitir_negativo = config('permitir_estoque_negativo', False, c)
        for p,qtd,preco in processados:
            baixar_estoque(c,p['id'],qtd,'Venda',v,permitir_negativo=permitir_negativo)
            c.execute('INSERT INTO itens_venda(venda_id,produto_id,quantidade,preco_unitario,custo_unitario,nome_original) VALUES(?,?,?,?,?,?)',
                      (v,p['id'],qtd,preco,p['preco_custo'],p['nome']))
        if politica:
            prazo=(date.today()+timedelta(days=int(politica['prazo_dias']))).isoformat()
            c.execute('INSERT INTO titulos_receber(venda_id,cliente_id,valor_centavos,vencimento,juros_dia,multa_dia) VALUES(?,?,?,?,?,?)',
                      (v,cliente_id,total,prazo,politica['juros_dia'] or 0,politica['multa_dia'] or 0))
            reconciliar_titulos(c,cliente_id)
        else:
            if pagamentos and taxa:
                raise ErroGestao('Para pagamento dividido, registre as taxas reais na liquidação do cartão.')
            for f,valor in partes:
                entrada_pagamento(c,f,valor,'venda',v,taxa if len(partes)==1 else 0)
                c.execute('INSERT INTO venda_pagamentos(venda_id,forma,valor_centavos) VALUES(?,?,?)',(v,f,valor))
        auditar(c,'venda','vendas',v,{'total':total,'forma':forma_pagamento})
        return {'id':v,'valor_total':total/100,'taxa_paga':taxa/100,'valor_liquido':(total-taxa)/100}


def titulos_cliente(cliente_id, hoje=None):
    hoje=date.fromisoformat(hoje) if hoje else date.today()
    rows=consultar('SELECT * FROM titulos_receber WHERE cliente_id=? AND cancelado=0 ORDER BY vencimento IS NULL,vencimento,id',(cliente_id,))
    for r in rows:
        saldo=r['valor_centavos']-r['recebido_centavos']
        dias=max(0,(hoje-date.fromisoformat(r['vencimento'])).days) if r['vencimento'] else 0
        # Encargos proporcionais ao principal liquidado: pagamentos parciais não
        # reaplicam multa sobre a parte já quitada.
        r['juros_centavos']=centavos(Decimal(saldo)/100*Decimal(str(r['juros_dia']))/100*Decimal(dias))
        r['multa_centavos']=centavos(Decimal(saldo)/100*Decimal(str(r['multa_dia']))/100*Decimal(dias))
        r['encargos_centavos']=r['juros_centavos']+r['multa_centavos']
        r['saldo_centavos']=saldo
        r['status']='Recebido' if saldo<=0 else ('Parcialmente recebido' if r['recebido_centavos'] else 'Lançado')
        r['atraso']=dias if saldo>0 else 0
    return rows


def receber_fiado(cliente_id, valor, observacao='', forma_pagamento='dinheiro', chave_operacao=None, cobrar_encargos=True, taxa_centavos=0):
    permitir('venda') if PERFIL=='caixa' else permitir('financeiro')
    valor=centavos(valor)
    taxa_centavos=int(taxa_centavos or 0)
    if taxa_centavos<0: raise ErroGestao('Taxa inválida.')
    chave_operacao=chave_operacao or uuid.uuid4().hex
    with transacao() as c:
        existente=c.execute('SELECT id FROM pagamentos_fiado WHERE chave_operacao=?',(chave_operacao,)).fetchone()
        if existente: return existente[0]
        saldo=saldo_cliente(c,cliente_id)
        if valor<=0 or valor>saldo: raise ErroGestao('Principal deve ser positivo e não pode exceder o saldo em aberto.')
        if not cobrar_encargos: permitir('credito')
        restante,encargos,alocacoes=valor,0,[]
        for t in titulos_cliente(cliente_id):
            principal=min(restante,max(0,t['saldo_centavos']))
            if principal:
                enc=round(t['encargos_centavos']*principal/t['saldo_centavos']) if cobrar_encargos else 0
                alocacoes.append((t['id'],principal,enc)); encargos+=enc; restante-=principal
        pid=c.execute("INSERT INTO pagamentos_fiado(cliente_id,valor,forma_pagamento,observacao,tipo,encargos_centavos,taxa_centavos,chave_operacao,usuario) VALUES(?,?,?,?,'recebimento',?,?,?,?)",
                      (cliente_id,valor/100,forma_pagamento,observacao,encargos,taxa_centavos,chave_operacao,USUARIO)).lastrowid
        for tid,principal,enc in alocacoes:
            c.execute('UPDATE titulos_receber SET recebido_centavos=recebido_centavos+? WHERE id=?',(principal,tid))
            c.execute('INSERT INTO recebimentos_titulos(titulo_id,pagamento_id,principal_centavos,encargos_centavos) VALUES(?,?,?,?)',(tid,pid,principal,enc))
        # A taxa (cartao/pix/voucher) e cobrada do cliente: entra no bruto recebido
        # e o movimento/recebivel liquido fica igual ao que quitou a divida.
        mid=entrada_pagamento(c,forma_pagamento,valor+encargos+taxa_centavos,'fiado',pid,taxa=taxa_centavos)
        c.execute('UPDATE pagamentos_fiado SET movimento_id=? WHERE id=?',(mid,pid))
        auditar(c,'recebimento','fiado',pid,{'principal':valor,'encargos':encargos,'taxa':taxa_centavos,'dispensa':not cobrar_encargos})
        return pid


def recibo_fiado(pid):
    r=consultar('SELECT p.*,c.nome FROM pagamentos_fiado p JOIN clientes c ON c.id=p.cliente_id WHERE p.id=?',(pid,))[0]
    taxa=(r.get('taxa_centavos') or 0)/100
    total=r['valor']+r['encargos_centavos']/100+taxa
    linhas=[f'RECIBO DE PAGAMENTO #{pid}', f'Cliente: {r["nome"]}', f'Data: {r["data_hora"]}',
            f'Principal: R$ {r["valor"]:.2f}', f'Encargos: R$ {r["encargos_centavos"]/100:.2f}']
    if taxa:
        linhas.append(f'Taxa {r["forma_pagamento"]}: R$ {taxa:.2f}')
    linhas += [f'Total recebido: R$ {total:.2f}', f'Forma: {r["forma_pagamento"]}',
               f'Responsável: {r["usuario"]}', r["observacao"], 'Comprovante não fiscal.']
    return '\n'.join(linhas)


def registrar_baixa(itens,motivo,observacao='',perda=False,responsavel=None,centro_custo='',chave=None):
    permitir('estoque')
    if not itens: raise ErroGestao('Adicione pelo menos um produto.')
    tabela='perdas' if perda else 'consumo_interno'
    chave=chave or uuid.uuid4().hex
    with transacao() as c:
        # Idempotência: mesma chave não gera duas baixas (protege de duplo clique
        # e reenvio). Devolve o lançamento já existente, sem efeito novo.
        existente=c.execute(f'SELECT id,valor_total FROM {tabela} WHERE chave=?',(chave,)).fetchone()
        if existente:
            return {'id':existente['id'],'valor_total':existente['valor_total'],'duplicado':True}
        total=0
        rid=c.execute(f'INSERT INTO {tabela}(motivo,observacao,responsavel,chave) VALUES(?,?,?,?)',(motivo,observacao,responsavel or USUARIO,chave)).lastrowid
        if not perda: c.execute('UPDATE consumo_interno SET centro_custo=? WHERE id=?',(centro_custo,rid))
        for it in itens:
            qtd=quantidade(it['quantidade'])
            p=baixar_estoque(c,it['produto_id'],qtd,'Perda' if perda else 'Consumo interno',rid,perda,it.get('lote_id'))
            subtotal=centavos(Decimal(str(qtd))*Decimal(str(p['preco_custo'])))
            total+=subtotal
            tab,col=('itens_perda','perda_id') if perda else ('itens_consumo_interno','consumo_id')
            c.execute(f'INSERT INTO {tab}({col},produto_id,quantidade,preco_custo_unitario,subtotal) VALUES(?,?,?,?,?)',(rid,p['id'],qtd,p['preco_custo'],subtotal/100))
        c.execute(f'UPDATE {tabela} SET valor_total=? WHERE id=?',(total/100,rid))
        auditar(c,'baixa',tabela,rid,{'custo_centavos':total,'motivo':motivo})
        return {'id':rid,'valor_total':total/100}


def criar_conta_pagar(credor,descricao,valor,vencimento,categoria='Despesas fixas',emissao=None,competencia=None,documento='',compra_ref=''):
    permitir('financeiro')
    valor=centavos(valor)
    if not credor.strip() or not descricao.strip() or valor<=0: raise ErroGestao('Informe credor, descrição e valor positivo.')
    vencimento=data_iso(vencimento); emissao=data_iso(emissao or date.today().isoformat()); competencia=data_iso(competencia or emissao)
    with transacao() as c:
        r=c.execute('SELECT id FROM credores WHERE lower(nome)=lower(?)',(credor.strip(),)).fetchone()
        cid=r[0] if r else c.execute('INSERT INTO credores(nome) VALUES(?)',(credor.strip(),)).lastrowid
        if documento and c.execute('SELECT 1 FROM contas_pagar WHERE credor_id=? AND documento=? AND cancelada=0',(cid,documento)).fetchone():
            raise ErroGestao('Já existe uma obrigação com esse credor e documento.')
        tid=c.execute('INSERT INTO contas_pagar(credor_id,descricao,categoria,documento,valor_centavos,emissao,vencimento,competencia,compra_ref,usuario) VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (cid,descricao,categoria,documento,valor,emissao,vencimento,competencia,compra_ref,USUARIO)).lastrowid
        auditar(c,'criar','contas_pagar',tid,{'valor':valor})
        return tid


def contas_pagar():
    rows=consultar('''SELECT t.*,c.nome credor, t.valor_centavos-COALESCE((SELECT SUM(principal_centavos)
          FROM pagamentos_contas p WHERE p.titulo_id=t.id AND p.estornado=0),0) saldo_centavos
          FROM contas_pagar t JOIN credores c ON c.id=t.credor_id WHERE t.cancelada=0 ORDER BY vencimento,t.id''')
    for r in rows:
        r['status']='Pago' if not r['saldo_centavos'] else ('Parcialmente pago' if r['saldo_centavos']<r['valor_centavos'] else 'Em aberto')
        r['dias']=(date.fromisoformat(r['vencimento'])-date.today()).days
    return rows


def pagar_conta(titulo_id,valor,conta_id=2,metodo='Pix',data=None,encargos=0,desconto=0,comprovante='',chave=None):
    permitir('financeiro')
    principal,enc,desc=centavos(valor),centavos(encargos),centavos(desconto)
    chave=chave or uuid.uuid4().hex; data=data_iso(data or date.today().isoformat())
    with transacao() as c:
        old=c.execute('SELECT id FROM pagamentos_contas WHERE chave=?',(chave,)).fetchone()
        if old: return old[0]
        t=c.execute('SELECT * FROM contas_pagar WHERE id=? AND cancelada=0',(titulo_id,)).fetchone()
        if not t: raise ErroGestao('Conta não encontrada.')
        pago=c.execute('SELECT COALESCE(SUM(principal_centavos),0) FROM pagamentos_contas WHERE titulo_id=? AND estornado=0',(titulo_id,)).fetchone()[0]
        if principal<=0 or principal>t['valor_centavos']-pago or min(enc,desc)<0 or desc>principal+enc:
            raise ErroGestao('Pagamento, encargos ou desconto inválidos.')
        mid=movimento(c,conta_id,-(principal+enc-desc),t['categoria'],t['descricao'],'conta_pagar',titulo_id,data=data)
        pid=c.execute('INSERT INTO pagamentos_contas(titulo_id,principal_centavos,encargos_centavos,desconto_centavos,data,metodo,comprovante,movimento_id,chave) VALUES(?,?,?,?,?,?,?,?,?)',
                      (titulo_id,principal,enc,desc,data,metodo,comprovante,mid,chave)).lastrowid
        auditar(c,'pagar','contas_pagar',titulo_id,{'pagamento':pid,'principal':principal})
        return pid


def contas_saldos():
    return consultar('''SELECT c.*,c.saldo_inicial_centavos+COALESCE(SUM(m.valor_centavos),0) saldo_centavos
                        FROM contas_financeiras c LEFT JOIN movimentos_financeiros m ON m.conta_id=c.id GROUP BY c.id''')


def abrir_caixa(valor):
    permitir('venda')
    valor=centavos(valor)
    if valor<0: raise ErroGestao('Saldo inicial inválido.')
    with transacao() as c:
        if c.execute('SELECT 1 FROM sessoes_caixa WHERE fechamento IS NULL').fetchone(): raise ErroGestao('Já existe um caixa aberto.')
        sid=c.execute('INSERT INTO sessoes_caixa(usuario,inicial_centavos) VALUES(?,?)',(USUARIO,valor)).lastrowid
        auditar(c,'abrir','caixa',sid,{'fundo':valor})
        return sid


def fechar_caixa(contado,justificativa=''):
    permitir('venda')
    contado=centavos(contado)
    if contado<0: raise ErroGestao('Contagem inválida.')
    with transacao() as c:
        s=c.execute('SELECT * FROM sessoes_caixa WHERE fechamento IS NULL').fetchone()
        if not s: raise ErroGestao('Não há caixa aberto.')
        # Auditoria fornece hora exata de inserção; data financeira sozinha não separa turnos.
        mov=c.execute("SELECT COALESCE(SUM(m.valor_centavos),0) FROM movimentos_financeiros m JOIN auditoria a ON a.entidade='financeiro' AND a.acao='movimento' AND a.referencia=CAST(m.id AS TEXT) WHERE m.conta_id=1 AND a.id>(SELECT id FROM auditoria WHERE entidade='caixa' AND acao='abrir' AND referencia=? ORDER BY id DESC LIMIT 1)",(str(s['id']),)).fetchone()[0]
        esperado=s['inicial_centavos']+mov
        if contado!=esperado and not justificativa.strip(): raise ErroGestao(f'Esperado R$ {esperado/100:.2f}. Justifique a diferença de caixa.')
        c.execute("UPDATE sessoes_caixa SET fechamento=datetime('now','localtime'),contado_centavos=?,esperado_centavos=?,justificativa=? WHERE id=?",(contado,esperado,justificativa,s['id']))
        auditar(c,'fechar','caixa',s['id'],{'esperado':esperado,'contado':contado,'justificativa':justificativa})
        return esperado/100


def transferencia(origem,destino,valor,descricao='Transferência interna'):
    permitir('financeiro')
    valor=centavos(valor)
    if valor<=0 or origem==destino: raise ErroGestao('Informe contas diferentes e valor positivo.')
    with transacao() as c:
        ref=uuid.uuid4().hex
        movimento(c,origem,-valor,'Transferência',descricao,'transferencia',ref)
        movimento(c,destino,valor,'Transferência',descricao,'transferencia',ref)


def liquidar_cartao(rid,conta_id=2,taxa=None):
    permitir('financeiro')
    with transacao() as c:
        r=c.execute('SELECT * FROM recebiveis_cartao WHERE id=?',(rid,)).fetchone()
        if not r or r['liquidado']: raise ErroGestao('Recebível inexistente ou já liquidado.')
        taxa=r['taxa_centavos'] if taxa is None else centavos(taxa)
        if taxa<0 or taxa>r['bruto_centavos']: raise ErroGestao('Taxa inválida.')
        mid=movimento(c,conta_id,r['bruto_centavos']-taxa,'Liquidação de cartão',f'Cartão #{rid}','cartao',rid)
        c.execute("UPDATE recebiveis_cartao SET liquidado=date('now','localtime'),movimento_id=?,taxa_centavos=? WHERE id=?",(mid,taxa,rid))


def resumo_financeiro(inicio,fim):
    inicio=data_iso(inicio); fim=data_iso(fim)
    if inicio>fim: raise ErroGestao('Período inválido.')
    c=db.get_conn()
    try:
        def soma(sql): return c.execute(sql,(inicio,fim)).fetchone()[0] or 0
        entradas=soma("SELECT SUM(valor_centavos) FROM movimentos_financeiros WHERE valor_centavos>0 AND categoria!='Transferência' AND data BETWEEN ? AND ?")
        saidas=-soma("SELECT SUM(valor_centavos) FROM movimentos_financeiros WHERE valor_centavos<0 AND categoria!='Transferência' AND data BETWEEN ? AND ?")
        aportes=soma("SELECT SUM(valor_centavos) FROM movimentos_financeiros WHERE categoria='Aporte' AND data BETWEEN ? AND ?")
        retiradas=soma("SELECT SUM(valor_centavos) FROM movimentos_financeiros WHERE categoria='Retirada' AND data BETWEEN ? AND ?")
        vendas=soma('SELECT SUM(valor_total) FROM vendas WHERE cancelada=0 AND date(data_hora) BETWEEN ? AND ?')
        cmv=soma('SELECT SUM(i.quantidade*i.custo_unitario) FROM itens_venda i JOIN vendas v ON v.id=i.venda_id WHERE v.cancelada=0 AND date(v.data_hora) BETWEEN ? AND ?')
        sem_custo=soma('SELECT COUNT(*) FROM itens_venda i JOIN vendas v ON v.id=i.venda_id WHERE v.cancelada=0 AND i.custo_unitario IS NULL AND date(v.data_hora) BETWEEN ? AND ?')
        consumo=soma('SELECT SUM(valor_total) FROM consumo_interno WHERE date(data_hora) BETWEEN ? AND ?')
        perdas=soma('SELECT SUM(valor_total) FROM perdas WHERE date(data_hora) BETWEEN ? AND ?')
        despesas=soma("SELECT SUM(valor_centavos)/100.0 FROM contas_pagar WHERE cancelada=0 AND categoria NOT IN ('Mercadoria para revenda','Investimento') AND competencia BETWEEN ? AND ?")
        taxas=soma('SELECT SUM(taxa_paga) FROM vendas WHERE cancelada=0 AND date(data_hora) BETWEEN ? AND ?')
        # Taxas de cartão efetivas substituem as estimadas para as vendas novas.
        taxas_cartao=soma("SELECT SUM(r.taxa_centavos)/100.0 FROM recebiveis_cartao r JOIN vendas v ON r.origem='venda' AND r.referencia=CAST(v.id AS TEXT) WHERE v.cancelada=0 AND date(v.data_hora) BETWEEN ? AND ?")
        taxas_estimadas=soma("SELECT SUM(v.taxa_paga) FROM vendas v WHERE v.cancelada=0 AND EXISTS(SELECT 1 FROM recebiveis_cartao r WHERE r.origem='venda' AND r.referencia=CAST(v.id AS TEXT)) AND date(v.data_hora) BETWEEN ? AND ?")
        taxas+=taxas_cartao-taxas_estimadas
        encargos_recebidos=soma("SELECT SUM(encargos_centavos)/100.0 FROM pagamentos_fiado WHERE tipo='recebimento' AND estornado=0 AND date(data_hora) BETWEEN ? AND ?")
        encargos_pagos=soma('SELECT SUM(encargos_centavos-desconto_centavos)/100.0 FROM pagamentos_contas WHERE estornado=0 AND data BETWEEN ? AND ?')
        taxas_fiado=soma("SELECT SUM(r.taxa_centavos)/100.0 FROM recebiveis_cartao r JOIN pagamentos_fiado p ON r.origem='fiado' AND r.referencia=CAST(p.id AS TEXT) WHERE p.estornado=0 AND date(p.data_hora) BETWEEN ? AND ?")
        outras_receitas=soma("SELECT SUM(valor_centavos)/100.0 FROM movimentos_financeiros WHERE categoria='Outras receitas' AND data BETWEEN ? AND ?")
        n=soma('SELECT COUNT(*) FROM vendas WHERE cancelada=0 AND date(data_hora) BETWEEN ? AND ?')
        return dict(entradas=entradas/100,saidas=saidas/100,fluxo=(entradas-saidas)/100,fluxo_livre=(entradas-saidas-aportes-retiradas)/100,vendas=vendas,cmv=cmv,
                    consumo=consumo,perdas=perdas,despesas=despesas,taxas=taxas+taxas_fiado,encargos_recebidos=encargos_recebidos,
                    encargos_pagos=encargos_pagos,outras_receitas=outras_receitas,
                    resultado=vendas-cmv-consumo-perdas-despesas-taxas-taxas_fiado+encargos_recebidos-encargos_pagos+outras_receitas,
                    margem=(vendas-cmv)/vendas*100 if vendas else 0,ticket=vendas/n if n else 0,sem_custo=sem_custo)
    finally: c.close()


def _hash_senha(senha, salt):
    return hashlib.pbkdf2_hmac('sha256', senha.encode(), bytes.fromhex(salt), 260000).hex()


def tem_usuarios():
    """True se já existe ao menos um usuário ativo cadastrado."""
    return bool(consultar('SELECT 1 FROM usuarios WHERE ativo=1 LIMIT 1'))


def criar_usuario(nome,senha,perfil):
    # O primeiro usuário (gerente) é criado no primeiro acesso, quando ainda
    # não existe nenhum — só aí o cadastro é liberado sem autenticação prévia.
    # Depois disso, criar usuários exige permissão de configuração.
    if tem_usuarios():
        permitir('configurar')
    elif perfil!='gerente':
        raise ErroGestao('O primeiro usuário do sistema precisa ser gerente.')
    if len(senha)<8 or not nome.strip() or perfil not in PERMISSOES: raise ErroGestao('Nome, perfil e senha com pelo menos 8 caracteres são obrigatórios.')
    salt=secrets.token_hex(16)
    hashed=_hash_senha(senha,salt)
    with transacao() as c:
        c.execute('INSERT INTO usuarios(nome,perfil,salt,senha_hash) VALUES(?,?,?,?)',(nome.strip(),perfil,salt,hashed))
        auditar(c,'criar','usuario',nome,{'perfil':perfil})


def autenticar(nome,senha):
    global USUARIO,PERFIL
    rows=consultar('SELECT * FROM usuarios WHERE nome=? AND ativo=1',(nome,))
    if rows:
        r=rows[0]; hashed=_hash_senha(senha,r['salt'])
        if secrets.compare_digest(hashed,r['senha_hash']):
            USUARIO,PERFIL=r['nome'],r['perfil']; return True
    return False


def sair():
    """Encerra a sessão do usuário: volta ao estado não autenticado, sem
    nenhuma permissão, até que alguém entre novamente."""
    global USUARIO,PERFIL
    USUARIO,PERFIL='Sistema local',None


def alterar_senha(usuario,senha_nova,senha_atual=None):
    """Troca a senha de um usuário do banco (fonte única de autenticação).
    Um gerente pode redefinir a senha de outro usuário; trocar a própria
    senha exige informar a senha atual."""
    global USUARIO,PERFIL
    if len(senha_nova or '')<8: raise ErroGestao('A nova senha deve ter pelo menos 8 caracteres.')
    rows=consultar('SELECT * FROM usuarios WHERE nome=? AND ativo=1',(usuario,))
    if not rows: raise ErroGestao('Usuário não encontrado.')
    r=rows[0]
    proprio=USUARIO==usuario
    if proprio:
        if senha_atual is None: raise ErroGestao('Informe a senha atual para alterá-la.')
        if not secrets.compare_digest(_hash_senha(senha_atual,r['salt']),r['senha_hash']):
            raise ErroGestao('Senha atual incorreta.')
    else:
        permitir('configurar')
    salt=secrets.token_hex(16)
    with transacao() as c:
        c.execute('UPDATE usuarios SET salt=?,senha_hash=? WHERE id=?',(salt,_hash_senha(senha_nova,salt),r['id']))
        auditar(c,'alterar_senha','usuario',usuario)


def exportar_csv(caminho,rows):
    if not rows: raise ErroGestao('Não há registros para exportar.')
    with open(caminho,'w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter=';')
        writer.writeheader(); writer.writerows(rows)


def validar_codigo(codigo):
    if not codigo:
        return  # SKU interno gerado para produção/granel.
    codigo=str(codigo).strip()
    if not codigo.isdigit() or len(codigo) not in (8,12,13,14):
        raise ErroGestao('Código comercial deve ter 8, 12, 13 ou 14 dígitos. Deixe vazio para usar SKU interno.')
    soma=sum(int(n)*(3 if i%2==0 else 1) for i,n in enumerate(reversed(codigo[:-1])))
    if (10-soma%10)%10!=int(codigo[-1]):
        raise ErroGestao('Dígito verificador do código de barras inválido.')


def reconciliar_titulos(c,cliente_id):
    """Ajustes não monetários são alocados FIFO, sem criar entradas financeiras."""
    pagamentos=centavos(c.execute('SELECT COALESCE(SUM(valor),0) FROM pagamentos_fiado WHERE cliente_id=? AND estornado=0',(cliente_id,)).fetchone()[0])
    for t in c.execute('SELECT * FROM titulos_receber WHERE cliente_id=? AND cancelado=0 ORDER BY id',(cliente_id,)).fetchall():
        recebido=min(t['valor_centavos'],max(0,pagamentos)); pagamentos-=recebido
        c.execute('UPDATE titulos_receber SET recebido_centavos=? WHERE id=?',(recebido,t['id']))


def ajustar_estoque(produto_id,qtd,tipo='entrada',observacao='',validade=None,custo=None):
    permitir('estoque')
    qtd=float(str(qtd).replace(',','.'))
    if not math.isfinite(qtd) or qtd<0 or (qtd==0 and tipo!='ajuste') or tipo not in ('entrada','saida','ajuste'):
        raise ErroGestao('Tipo ou quantidade inválidos.')
    if not observacao.strip(): raise ErroGestao('Informe o documento ou motivo da movimentação.')
    if validade: validade=data_iso(validade)
    with transacao() as c:
        p=c.execute('SELECT * FROM produtos WHERE id=?',(produto_id,)).fetchone()
        if not p: raise ErroGestao('Produto não encontrado.')
        delta=qtd-p['quantidade_estoque'] if tipo=='ajuste' else (qtd if tipo=='entrada' else -qtd)
        if tipo=='ajuste':
            c.execute('INSERT INTO inventarios(produto_id,antes,contado,motivo,usuario) VALUES(?,?,?,?,?)',(produto_id,p['quantidade_estoque'],qtd,observacao,USUARIO))
        if delta<0:
            baixar_estoque(c,produto_id,-delta,'Inventário' if tipo=='ajuste' else 'Ajuste',observacao,True)
        elif delta>0:
            if p['perecivel'] and not validade: raise ErroGestao('Informe a validade do recebimento perecível.')
            novo_custo=p['preco_custo']
            if custo is not None:
                if centavos(custo)<0: raise ErroGestao('Custo inválido.')
                novo_custo=custo_medio_entrada(p['quantidade_estoque'],p['preco_custo'],delta,float(custo))
            c.execute('UPDATE produtos SET quantidade_estoque=round(quantidade_estoque+?,3),preco_custo=? WHERE id=?',(delta,novo_custo,produto_id))
            c.execute("INSERT INTO movimentacoes_estoque(produto_id,tipo,quantidade,observacao) VALUES(?,'entrada',?,?)",(produto_id,delta,observacao))
            if validade:
                c.execute('INSERT INTO lotes_validade(produto_id,quantidade,data_validade,observacao) VALUES(?,?,?,?)',(produto_id,delta,validade,observacao))
        auditar(c,tipo,'estoque',produto_id,{'delta':delta,'motivo':observacao})
        return round(p['quantidade_estoque']+delta,3)


def registrar_producao(receita_id,multiplicador,observacao='',validade=None,rendimento_real=None,responsavel=None,chave=None):
    permitir('estoque')
    mult=quantidade(multiplicador)
    if not validade: raise ErroGestao('Informe a validade do lote produzido.')
    validade=data_iso(validade)
    if validade<date.today().isoformat(): raise ErroGestao('Produção não pode entrar com validade vencida.')
    chave=chave or uuid.uuid4().hex
    with transacao() as c:
        existente=c.execute('SELECT id,quantidade_produzida,custo_total,custo_unitario FROM producoes WHERE chave=?',(chave,)).fetchone()
        if existente:
            return {'id':existente['id'],'quantidade_produzida':existente['quantidade_produzida'],
                    'custo_total':existente['custo_total'],'custo_unitario':existente['custo_unitario'],
                    'insumos_usados':[],'duplicado':True}
        r=c.execute('SELECT * FROM receitas WHERE id=? AND ativo=1',(receita_id,)).fetchone()
        if not r: raise ErroGestao('Receita não encontrada.')
        p=c.execute('SELECT * FROM produtos WHERE id=? AND ativo=1',(r['produto_id'],)).fetchone()
        if not p: raise ErroGestao('Produto final inativo ou inexistente.')
        itens=c.execute('SELECT insumo_id,SUM(quantidade) quantidade FROM receita_itens WHERE receita_id=? GROUP BY insumo_id',(receita_id,)).fetchall()
        if not itens: raise ErroGestao('Cadastre os insumos da receita.')
        produzido=quantidade(rendimento_real if rendimento_real is not None else mult*r['rendimento'])
        pid=c.execute('INSERT INTO producoes(receita_id,multiplicador,quantidade_produzida,observacao,responsavel,validade,rendimento_real,chave) VALUES(?,?,?,?,?,?,?,?)',
                      (receita_id,mult,produzido,observacao,responsavel or USUARIO,validade,produzido,chave)).lastrowid
        custo,usados=Decimal(0),[]
        for it in itens:
            if it['insumo_id']==p['id']: raise ErroGestao('Produto final não pode consumir a si mesmo.')
            qtd=quantidade(mult*it['quantidade'])
            insumo=baixar_estoque(c,it['insumo_id'],qtd,'Produção',pid)
            custo+=Decimal(str(insumo['preco_custo']))*Decimal(str(qtd))
            usados.append(dict(insumo_id=insumo['id'],nome=insumo['nome'],quantidade=qtd))
            c.execute('INSERT INTO insumos_producao(producao_id,produto_id,nome,unidade,quantidade,custo_unitario) VALUES(?,?,?,?,?,?)',
                      (pid,insumo['id'],insumo['nome'],insumo['unidade'],qtd,insumo['preco_custo']))
        custo=centavos(custo)/100; unitario=custo/produzido
        medio=custo_medio_entrada(p['quantidade_estoque'],p['preco_custo'],produzido,unitario)
        c.execute('UPDATE produtos SET quantidade_estoque=round(quantidade_estoque+?,3),preco_custo=?,perecivel=1 WHERE id=?',(produzido,medio,p['id']))
        c.execute('INSERT INTO lotes_validade(produto_id,quantidade,data_validade,observacao) VALUES(?,?,?,?)',(p['id'],produzido,validade,f'Produção #{pid}'))
        c.execute("INSERT INTO movimentacoes_estoque(produto_id,tipo,quantidade,observacao) VALUES(?,'entrada',?,?)",(p['id'],produzido,f'Produção #{pid}'))
        c.execute('UPDATE producoes SET custo_total=?,custo_unitario=? WHERE id=?',(custo,unitario,pid))
        auditar(c,'produção','producoes',pid,{'custo':custo,'rendimento':produzido,'validade':validade})
        return dict(id=pid,produto_id=p['id'],produto_nome=p['nome'],quantidade_produzida=produzido,custo_total=custo,custo_unitario=unitario,insumos_usados=usados)


def estornar_movimento(c,mid,motivo):
    if not mid: return
    m=c.execute('SELECT * FROM movimentos_financeiros WHERE id=?',(mid,)).fetchone()
    if c.execute('SELECT 1 FROM movimentos_financeiros WHERE estorno_de=?',(mid,)).fetchone(): raise ErroGestao('Movimento já estornado.')
    novo=movimento(c,m['conta_id'],-m['valor_centavos'],m['categoria'],'Estorno: '+motivo,'estorno',mid)
    c.execute('UPDATE movimentos_financeiros SET estorno_de=? WHERE id=?',(mid,novo))


def estornar_recebimento(pid,motivo):
    permitir('estornar')
    if not motivo.strip(): raise ErroGestao('Justifique o estorno.')
    with transacao() as c:
        p=c.execute("SELECT * FROM pagamentos_fiado WHERE id=? AND estornado=0 AND tipo='recebimento'",(pid,)).fetchone()
        if not p: raise ErroGestao('Recebimento inexistente, antigo ou já estornado.')
        estornar_movimento(c,p['movimento_id'],motivo)
        for r in c.execute("SELECT * FROM recebiveis_cartao WHERE origem='fiado' AND referencia=?",(str(pid),)).fetchall():
            estornar_movimento(c,r['movimento_id'],motivo)
        c.execute("UPDATE recebiveis_cartao SET liquidado='ESTORNADO' WHERE origem='fiado' AND referencia=?",(str(pid),))
        c.execute('UPDATE pagamentos_fiado SET estornado=1 WHERE id=?',(pid,))
        reconciliar_titulos(c,p['cliente_id'])
        auditar(c,'estornar','recebimento',pid,{'motivo':motivo})


def estornar_pagamento(pid,motivo):
    permitir('estornar')
    if not motivo.strip(): raise ErroGestao('Justifique o estorno.')
    with transacao() as c:
        p=c.execute('SELECT * FROM pagamentos_contas WHERE id=? AND estornado=0',(pid,)).fetchone()
        if not p: raise ErroGestao('Pagamento não encontrado ou já estornado.')
        estornar_movimento(c,p['movimento_id'],motivo)
        c.execute('UPDATE pagamentos_contas SET estornado=1 WHERE id=?',(pid,))
        auditar(c,'estornar','pagamento',pid,{'motivo':motivo})


def cancelar_venda(vid,motivo):
    permitir('estornar')
    if not motivo.strip(): raise ErroGestao('Justifique o cancelamento.')
    with transacao() as c:
        v=c.execute('SELECT * FROM vendas WHERE id=? AND cancelada=0',(vid,)).fetchone()
        if not v: raise ErroGestao('Venda não encontrada ou já cancelada.')
        if v['usuario']=='Legado': raise ErroGestao('Venda anterior à migração: requer conferência manual do histórico financeiro e dos lotes.')
        if c.execute('SELECT 1 FROM titulos_receber WHERE venda_id=? AND recebido_centavos>0',(vid,)).fetchone():
            raise ErroGestao('Estorne os recebimentos desta venda antes de cancelar.')
        for m in c.execute("SELECT id FROM movimentos_financeiros WHERE origem='venda' AND referencia=?",(str(vid),)).fetchall(): estornar_movimento(c,m['id'],motivo)
        for r in c.execute("SELECT * FROM recebiveis_cartao WHERE origem='venda' AND referencia=?",(str(vid),)).fetchall(): estornar_movimento(c,r['movimento_id'],motivo)
        c.execute("UPDATE recebiveis_cartao SET liquidado='ESTORNADO' WHERE origem='venda' AND referencia=?",(str(vid),))
        for it in c.execute('SELECT * FROM itens_venda WHERE venda_id=?',(vid,)).fetchall():
            c.execute('UPDATE produtos SET quantidade_estoque=quantidade_estoque+? WHERE id=?',(it['quantidade'],it['produto_id']))
            c.execute("INSERT INTO movimentacoes_estoque(produto_id,tipo,quantidade,observacao) VALUES(?,'entrada',?,?)",(it['produto_id'],it['quantidade'],f'Cancelamento venda #{vid}: {motivo}'))
        for l in c.execute("SELECT * FROM baixas_lotes WHERE origem='Venda' AND referencia=?",(str(vid),)).fetchall():
            c.execute('UPDATE lotes_validade SET quantidade=quantidade+? WHERE id=?',(l['quantidade'],l['lote_id']))
        c.execute('UPDATE vendas SET cancelada=1 WHERE id=?',(vid,))
        c.execute('UPDATE titulos_receber SET cancelado=1 WHERE venda_id=?',(vid,))
        auditar(c,'cancelar','venda',vid,{'motivo':motivo})


def definir_saldo_inicial(conta_id,valor):
    permitir('financeiro')
    with transacao() as c:
        conta=c.execute('SELECT * FROM contas_financeiras WHERE id=?',(conta_id,)).fetchone()
        if conta['conferida']: raise ErroGestao('Saldo já conferido. Use um ajuste identificado, preservando a auditoria.')
        c.execute('UPDATE contas_financeiras SET saldo_inicial_centavos=?,conferida=1 WHERE id=?',(centavos(valor),conta_id))
        auditar(c,'saldo_inicial','conta',conta_id,{'valor':centavos(valor),'data_base':conta['data_base']})


def duplicatas():
    from difflib import SequenceMatcher
    produtos=consultar('SELECT id,nome,sku,unidade,quantidade_estoque FROM produtos WHERE ativo=1 ORDER BY nome')
    result=[]
    for i,a in enumerate(produtos):
        for b in produtos[i+1:]:
            if a['unidade']==b['unidade'] and SequenceMatcher(None,normalizar(a['nome']),normalizar(b['nome'])).ratio()>=.87:
                result.append({'principal':a['id'],'nome':a['nome'],'duplicado':b['id'],'nome_similar':b['nome'],'saldo_a':a['quantidade_estoque'],'saldo_b':b['quantidade_estoque']})
    return result


def consolidar_produtos(principal,duplicado,somar_estoque=False):
    permitir('configurar')
    if principal==duplicado: raise ErroGestao('Selecione dois produtos diferentes.')
    with transacao() as c:
        a=c.execute('SELECT * FROM produtos WHERE id=? AND ativo=1',(principal,)).fetchone()
        b=c.execute('SELECT * FROM produtos WHERE id=? AND ativo=1',(duplicado,)).fetchone()
        if not a or not b or a['unidade']!=b['unidade']: raise ErroGestao('Produtos devem estar ativos e ter a mesma unidade.')
        if not somar_estoque and b['quantidade_estoque']:
            raise ErroGestao('Faça inventário do duplicado ou confirme explicitamente a soma dos estoques físicos.')
        if c.execute('SELECT 1 FROM receitas WHERE produto_id=?',(duplicado,)).fetchone():
            raise ErroGestao('Produto duplicado tem receita. Revise a produção antes de consolidar.')
        if c.execute('SELECT 1 FROM receita_itens ri JOIN receitas r ON r.id=ri.receita_id WHERE ri.insumo_id=? AND r.produto_id=?',(duplicado,principal)).fetchone():
            raise ErroGestao('A consolidação faria o produto consumir a si mesmo.')
        total=a['quantidade_estoque']+b['quantidade_estoque']
        # Sem ponderar quando um dos saldos não é positivo (estoque negativo é
        # erro de registro): usa o custo do produto que tem saldo real.
        if a['quantidade_estoque']>0 and b['quantidade_estoque']>0:
            custo=(a['quantidade_estoque']*a['preco_custo']+b['quantidade_estoque']*b['preco_custo'])/total
        elif a['quantidade_estoque']>0:
            custo=a['preco_custo']
        elif b['quantidade_estoque']>0:
            custo=b['preco_custo']
        else:
            custo=a['preco_custo']
        c.execute('UPDATE produtos SET quantidade_estoque=?,preco_custo=? WHERE id=?',(total,custo,principal))
        # Histórico de vendas permanece no ID original. Somente estoque futuro é consolidado.
        c.execute('UPDATE lotes_validade SET produto_id=? WHERE produto_id=?',(principal,duplicado))
        c.execute('UPDATE receita_itens SET insumo_id=? WHERE insumo_id=?',(principal,duplicado))
        c.execute('UPDATE produtos SET quantidade_estoque=0,ativo=0 WHERE id=?',(duplicado,))
        for pid,tipo,qtd in ((principal,'entrada',b['quantidade_estoque']),(duplicado,'saida',b['quantidade_estoque'])):
            c.execute('INSERT INTO movimentacoes_estoque(produto_id,tipo,quantidade,observacao) VALUES(?,?,?,?)',(pid,tipo,qtd,f'Consolidação {duplicado} → {principal}'))
        auditar(c,'consolidar','produto',principal,{'origem':dict(b),'destino_antes':dict(a)})


def alterar_produtos_lote(ids,categoria=None,ativo=None,percentual=None):
    permitir('estoque')
    with transacao() as c:
        for pid in ids:
            p=c.execute('SELECT * FROM produtos WHERE id=?',(pid,)).fetchone()
            if not p: raise ErroGestao('Produto não encontrado.')
            if categoria is not None: c.execute('UPDATE produtos SET categoria=? WHERE id=?',(categoria,pid))
            if ativo is not None: c.execute('UPDATE produtos SET ativo=? WHERE id=?',(int(bool(ativo)),pid))
            if percentual is not None:
                novo=centavos(Decimal(str(p['preco_venda']))*(1+Decimal(str(percentual))/100))/100
                if novo<0: raise ErroGestao('Preço não pode ser negativo.')
                c.execute('UPDATE produtos SET preco_venda=? WHERE id=?',(novo,pid))
                c.execute('INSERT INTO historico_precos(produto_id,anterior,novo,usuario) VALUES(?,?,?,?)',(pid,p['preco_venda'],novo,USUARIO))
            auditar(c,'alterar_lote','produto',pid,{'categoria':categoria,'ativo':ativo,'percentual':percentual})


def importar_extrato(caminho,conta_id):
    permitir('financeiro')
    with open(caminho,encoding='utf-8-sig',newline='') as f:
        linhas=list(csv.DictReader(f,delimiter=';'))
    with transacao() as c:
        total=0
        for row in linhas:
            if not {'data','descricao','valor','identificador'}<=row.keys(): raise ErroGestao('CSV deve conter data;descricao;valor;identificador. Use o identificador único fornecido pelo banco.')
            if not row['identificador'].strip(): raise ErroGestao('Identificador bancário obrigatório para evitar duplicidade.')
            cur=c.execute('INSERT OR IGNORE INTO extrato_bancario(conta_id,data,descricao,valor_centavos,identificador) VALUES(?,?,?,?,?)',
                          (conta_id,data_iso(row['data']),row['descricao'],centavos(row['valor']),row['identificador']))
            total+=cur.rowcount
        auditar(c,'importar','extrato',conta_id,{'linhas':total})
        return total


def conciliar(extrato_id,movimento_id):
    permitir('financeiro')
    with transacao() as c:
        e=c.execute('SELECT * FROM extrato_bancario WHERE id=? AND movimento_id IS NULL',(extrato_id,)).fetchone()
        m=c.execute('SELECT * FROM movimentos_financeiros WHERE id=? AND conciliado=0',(movimento_id,)).fetchone()
        if not e or not m or e['conta_id']!=m['conta_id'] or e['valor_centavos']!=m['valor_centavos']:
            raise ErroGestao('Extrato e lançamento devem ter a mesma conta e valor, sem conciliação anterior.')
        c.execute('UPDATE extrato_bancario SET movimento_id=? WHERE id=?',(movimento_id,extrato_id))
        c.execute('UPDATE movimentos_financeiros SET conciliado=1 WHERE id=?',(movimento_id,))
        auditar(c,'conciliar','extrato',extrato_id,{'movimento':movimento_id})


def receber_compra(itens,fornecedor,documento,vencimento,forma='A prazo',conta_id=2,chave=None):
    """Recebimento + custo médio + lote + obrigação/pagamento, atomicamente."""
    permitir('estoque'); permitir('financeiro')
    if not fornecedor.strip() or not documento.strip() or not itens: raise ErroGestao('Informe fornecedor, documento e itens.')
    vencimento=data_iso(vencimento); chave=chave or uuid.uuid4().hex
    if forma not in ('A prazo','À vista'): raise ErroGestao('Forma de compra inválida.')
    with transacao() as c:
        anterior=c.execute('SELECT id FROM compras_estoque WHERE chave=?',(chave,)).fetchone()
        if anterior: return anterior[0]
        if c.execute('SELECT 1 FROM compras_estoque WHERE fornecedor=? AND documento=?',(fornecedor,documento)).fetchone():
            raise ErroGestao('Compra já recebida para este fornecedor e documento.')
        total=0; processados=[]
        for it in itens:
            p=c.execute('SELECT * FROM produtos WHERE id=? AND ativo=1',(it['produto_id'],)).fetchone()
            if not p: raise ErroGestao('Produto não encontrado.')
            qtd=quantidade(it['quantidade']); custo=Decimal(str(it['custo']).replace(',','.'))
            if not custo.is_finite() or custo<0: raise ErroGestao('Custo inválido.')
            validade=data_iso(it['validade']) if it.get('validade') else None
            if p['perecivel'] and not validade: raise ErroGestao('Validade obrigatória para '+p['nome'])
            if validade and validade<date.today().isoformat(): raise ErroGestao('Não receba mercadoria vencida para venda.')
            total+=centavos(Decimal(str(qtd))*custo);processados.append((p,qtd,float(custo),validade))
        if total<=0: raise ErroGestao('A compra precisa ter valor maior que zero.')
        credor=c.execute('SELECT id FROM credores WHERE lower(nome)=lower(?)',(fornecedor,)).fetchone()
        cid=credor[0] if credor else c.execute('INSERT INTO credores(nome) VALUES(?)',(fornecedor,)).lastrowid
        if c.execute('SELECT 1 FROM contas_pagar WHERE credor_id=? AND documento=? AND cancelada=0',(cid,documento)).fetchone():
            raise ErroGestao('Já existe conta com esse documento. Receba somente o estoque usando ajuste identificado ou revise a obrigação.')
        hoje=date.today().isoformat()
        tid=c.execute("INSERT INTO contas_pagar(credor_id,descricao,categoria,documento,valor_centavos,emissao,vencimento,competencia,compra_ref,usuario) VALUES(?,?,'Mercadoria para revenda',?,?,?,?,?,?,?)",
                      (cid,'Compra '+documento,documento,total,hoje,vencimento,hoje,documento,USUARIO)).lastrowid
        comp=c.execute('INSERT INTO compras_estoque(documento,fornecedor,data,valor_centavos,titulo_id,usuario,chave) VALUES(?,?,?,?,?,?,?)',(documento,fornecedor,hoje,total,tid,USUARIO,chave)).lastrowid
        for p,qtd,custo,validade in processados:
            # Read again to support repeated product lines in the same document.
            atual=c.execute('SELECT quantidade_estoque,preco_custo FROM produtos WHERE id=?',(p['id'],)).fetchone()
            media=custo_medio_entrada(atual['quantidade_estoque'],atual['preco_custo'],qtd,custo)
            c.execute('UPDATE produtos SET quantidade_estoque=round(quantidade_estoque+?,3),preco_custo=?,fornecedor=? WHERE id=?',(qtd,media,fornecedor,p['id']))
            c.execute('INSERT INTO itens_compra(compra_id,produto_id,quantidade,custo_unitario,validade) VALUES(?,?,?,?,?)',(comp,p['id'],qtd,custo,validade))
            c.execute("INSERT INTO movimentacoes_estoque(produto_id,tipo,quantidade,observacao) VALUES(?,'entrada',?,?)",(p['id'],qtd,f'Compra #{comp} / {documento}'))
            if validade: c.execute('INSERT INTO lotes_validade(produto_id,quantidade,data_validade,observacao) VALUES(?,?,?,?)',(p['id'],qtd,validade,f'Compra #{comp}'))
        if forma=='À vista':
            mid=movimento(c,conta_id,-total,'Mercadoria para revenda','Compra '+documento,'conta_pagar',tid)
            c.execute('INSERT INTO pagamentos_contas(titulo_id,principal_centavos,data,metodo,movimento_id,chave) VALUES(?,?,?,?,?,?)',(tid,total,hoje,'À vista',mid,uuid.uuid4().hex))
        auditar(c,'receber_compra','compra',comp,{'total':total,'documento':documento})
        return comp


def relatorio_reposicao(dias=30,prazo=7):
    inicio=(date.today()-timedelta(days=dias-1)).isoformat()
    rows=consultar('''SELECT p.id,p.nome,p.categoria,p.quantidade_estoque estoque,p.estoque_minimo,p.preco_custo,
       COALESCE(SUM(CASE WHEN v.cancelada=0 AND date(v.data_hora)>=? THEN i.quantidade ELSE 0 END),0) vendido,
       SUM(CASE WHEN v.cancelada=0 AND date(v.data_hora)>=? THEN i.quantidade*i.custo_unitario ELSE 0 END) cmv,
       SUM(CASE WHEN v.cancelada=0 AND date(v.data_hora)>=? AND i.custo_unitario IS NULL THEN 1 ELSE 0 END) custos_ausentes
       FROM produtos p LEFT JOIN itens_venda i ON i.produto_id=p.id LEFT JOIN vendas v ON v.id=i.venda_id
       WHERE p.ativo=1 GROUP BY p.id ORDER BY vendido DESC''',(inicio,inicio,inicio))
    for r in rows:
        delta=consultar("SELECT COALESCE(SUM(CASE tipo WHEN 'entrada' THEN quantidade WHEN 'saida' THEN -quantidade ELSE quantidade END),0) delta FROM movimentacoes_estoque WHERE produto_id=? AND date(data_hora)>=?",(r['id'],inicio))[0]['delta']
        inicial=r['estoque']-delta
        medio=(max(0,inicial)+r['estoque'])/2*r['preco_custo']
        r['media_diaria']=round(r['vendido']/dias,3)
        r['repor']=round(max(0,max(r['estoque_minimo'],r['media_diaria']*prazo)-r['estoque']),3)
        r['giro_cmv_estimado']=round((r['cmv'] or 0)/medio,3) if medio and not r['custos_ausentes'] else None
        r['criterio']='Estoque médio inicial/final ao custo atual; estimativa' if not r['custos_ausentes'] else 'CMV histórico incompleto'
    return rows


def preco_vigente(produto_id):
    r=consultar("SELECT p.preco_venda, (SELECT MIN(preco) FROM promocoes WHERE produto_id=p.id AND inicio<=date('now','localtime') AND fim>=date('now','localtime')) oferta FROM produtos p WHERE p.id=?",(produto_id,))[0]
    return min(r['preco_venda'],r['oferta']) if r['oferta'] is not None else r['preco_venda']
