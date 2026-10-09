import sqlite3
from datetime import date, timedelta
import database as db
import gestao as g

class ErroOperacao(Exception): pass

def listar_produtos(busca=''):
    conn=db.get_conn()
    try:
        if busca:
            like=f'%{busca}%'; rows=conn.execute('SELECT * FROM produtos WHERE ativo=1 AND (nome LIKE ? OR codigo_barras LIKE ? OR sku LIKE ?) ORDER BY nome',(like,like,like)).fetchall()
        else: rows=conn.execute('SELECT * FROM produtos WHERE ativo=1 ORDER BY nome').fetchall()
        return [dict(r) for r in rows]
    finally: conn.close()

def obter_produto(produto_id):
    conn=db.get_conn()
    try:
        r=conn.execute('SELECT * FROM produtos WHERE id=?',(produto_id,)).fetchone(); return dict(r) if r else None
    finally: conn.close()

def buscar_por_codigo(codigo):
    conn=db.get_conn()
    try:
        r=conn.execute('SELECT * FROM produtos WHERE (codigo_barras=? OR sku=?) AND ativo=1',(str(codigo or '').strip(),str(codigo or '').strip())).fetchone(); return dict(r) if r else None
    finally: conn.close()

def criar_produto(nome,codigo_barras=None,categoria=None,unidade='UN',preco_custo=0,preco_venda=0,quantidade_estoque=0,estoque_minimo=3):
    g.permitir('estoque')
    nome=(nome or '').strip()
    g.validar_codigo(codigo_barras)
    if not nome: raise ErroOperacao('Informe o nome do produto.')
    if unidade not in ('UN','KG'): unidade='UN'
    if any(v<0 for v in (preco_custo,preco_venda,quantidade_estoque,estoque_minimo)): raise ErroOperacao('Valores negativos não são permitidos.')
    conn=db.get_conn()
    try:
        conn.execute('BEGIN IMMEDIATE')
        if any(g.normalizar(r['nome'])==g.normalizar(nome) for r in conn.execute('SELECT nome FROM produtos WHERE ativo=1')):
            raise ErroOperacao('Já existe um produto com esse nome. Confira unidade/embalagem e use um nome distinto.')
        try: cur=conn.execute('INSERT INTO produtos(codigo_barras,nome,categoria,unidade,preco_custo,preco_venda,quantidade_estoque,estoque_minimo) VALUES(?,?,?,?,?,?,?,?)',(codigo_barras or None,nome,categoria or None,unidade,preco_custo,preco_venda,quantidade_estoque,estoque_minimo))
        except sqlite3.IntegrityError: raise ErroOperacao('Já existe um produto com esse código de barras.')
        pid=cur.lastrowid
        conn.execute('UPDATE produtos SET sku=? WHERE id=?',(f'INT-{pid:06d}',pid))
        g.auditar(conn,'criar','produto',pid,{'nome':nome})
        if quantidade_estoque: conn.execute("INSERT INTO movimentacoes_estoque(produto_id,tipo,quantidade,observacao) VALUES(?,'entrada',?,'Estoque inicial')",(pid,quantidade_estoque))
        conn.commit(); return pid
    finally: conn.close()

def atualizar_produto(produto_id,nome=None,codigo_barras=None,categoria=None,unidade=None,preco_custo=None,preco_venda=None,estoque_minimo=None):
    g.permitir('estoque')
    conn=db.get_conn()
    try:
        p=conn.execute('SELECT * FROM produtos WHERE id=?',(produto_id,)).fetchone()
        if not p: raise ErroOperacao('Produto não encontrado.')
        novo_nome=nome if nome is not None else p['nome']
        novo_codigo=codigo_barras if codigo_barras is not None else p['codigo_barras']
        nova_categoria=categoria if categoria is not None else p['categoria']
        nova_unidade=unidade if unidade is not None else p['unidade']
        novo_custo=preco_custo if preco_custo is not None else p['preco_custo']
        novo_venda=preco_venda if preco_venda is not None else p['preco_venda']
        novo_minimo=estoque_minimo if estoque_minimo is not None else p['estoque_minimo']
        if not str(novo_nome).strip(): raise ErroOperacao('Informe o nome do produto.')
        if any(v is not None and v<0 for v in (novo_custo,novo_venda,novo_minimo)): raise ErroOperacao('Valores negativos não são permitidos.')
        if novo_codigo != p['codigo_barras']:
            g.validar_codigo(novo_codigo)
        if novo_venda != p['preco_venda']:
            conn.execute('INSERT INTO historico_precos(produto_id,anterior,novo,usuario) VALUES(?,?,?,?)',(produto_id,p['preco_venda'],novo_venda,g.USUARIO))
        g.auditar(conn,'editar','produto',produto_id,{'antes':dict(p),'nome':novo_nome,'preco':novo_venda})
        try:
            conn.execute(
                'UPDATE produtos SET codigo_barras=?,nome=?,categoria=?,unidade=?,preco_custo=?,preco_venda=?,estoque_minimo=? WHERE id=?',
                (novo_codigo,novo_nome,nova_categoria,nova_unidade,novo_custo,novo_venda,novo_minimo,produto_id)
            )
        except sqlite3.IntegrityError: raise ErroOperacao('Já existe outro produto com esse código de barras.')
        conn.commit()
    finally: conn.close()

def desativar_produto(produto_id):
    import gestao as _gestao
    _gestao.permitir('estoque')
    conn=db.get_conn()
    try: conn.execute('UPDATE produtos SET ativo=0 WHERE id=?',(produto_id,)); conn.commit()
    finally: conn.close()

def pode_excluir_produto_definitivamente(produto_id):
    """Só permite apagar de vez um produto que nunca apareceu numa venda,
    num consumo interno ou como insumo de receita — senão perderia história
    de vendas/produção de verdade. Devolve (pode:bool, motivo:str)."""
    conn=db.get_conn()
    try:
        n_vendas=conn.execute('SELECT COUNT(*) n FROM itens_venda WHERE produto_id=?',(produto_id,)).fetchone()['n']
        n_consumo=conn.execute('SELECT COUNT(*) n FROM itens_consumo_interno WHERE produto_id=?',(produto_id,)).fetchone()['n']
        n_receita=conn.execute('SELECT COUNT(*) n FROM receitas WHERE produto_id=?',(produto_id,)).fetchone()['n']
        n_insumo=conn.execute('SELECT COUNT(*) n FROM receita_itens WHERE insumo_id=?',(produto_id,)).fetchone()['n']
        bloqueios=[]
        if n_vendas: bloqueios.append(f'{n_vendas} venda(s)')
        if n_consumo: bloqueios.append(f'{n_consumo} consumo(s) interno(s)')
        if n_receita: bloqueios.append('é o produto final de uma receita')
        if n_insumo: bloqueios.append('é usado como insumo em uma receita')
        if bloqueios:
            return False, 'Esse produto tem histórico: ' + ', '.join(bloqueios) + '.'
        return True, ''
    finally: conn.close()

def excluir_produto_definitivo(produto_id, nome_confirmacao):
    """Apaga o produto DE VEZ do banco — só permitido sem histórico (venda,
    consumo interno ou receita), e só com o nome digitado batendo certinho
    como confirmação de segurança."""
    import gestao as _gestao
    _gestao.permitir('configurar')
    conn=db.get_conn()
    try:
        row=conn.execute('SELECT * FROM produtos WHERE id=?',(produto_id,)).fetchone()
        if not row: raise ErroOperacao('Produto não encontrado.')
        produto=dict(row)
        if (nome_confirmacao or '').strip().lower() != (produto['nome'] or '').strip().lower():
            raise ErroOperacao('O nome digitado não bate com o nome do produto. Nada foi apagado.')
        pode, motivo = pode_excluir_produto_definitivamente(produto_id)
        if not pode:
            raise ErroOperacao(motivo + ' Use "Desativar" em vez de excluir.')
        conn.execute('DELETE FROM movimentacoes_estoque WHERE produto_id=?',(produto_id,))
        conn.execute('DELETE FROM lotes_validade WHERE produto_id=?',(produto_id,))
        conn.execute('DELETE FROM produtos WHERE id=?',(produto_id,))
        conn.commit()
        return produto['nome']
    finally: conn.close()

def ajustar_estoque(produto_id,quantidade,tipo='entrada',observacao=''):
    try: return g.ajustar_estoque(produto_id,quantidade,tipo,observacao)
    except g.ErroGestao as exc: raise ErroOperacao(str(exc)) from exc


def registrar_venda(itens,forma_pagamento='dinheiro',desconto=0,cliente_id=None,taxa_paga=0,voucher_marca=None,**kwargs):
    try:
        return g.registrar_venda(itens,forma_pagamento,desconto,cliente_id,taxa_paga,voucher_marca,**kwargs)
    except (g.ErroGestao, ValueError) as exc:
        raise ErroOperacao(str(exc)) from exc


# Formas de pagamento usadas nas vendas, na ordem em que aparecem no resumo
# do histórico. 'fiado' fica por último porque não é dinheiro recebido — é a receber.
FORMAS_PAGAMENTO_VENDA = [
    ('dinheiro', 'Dinheiro'),
    ('pix', 'Pix'),
    ('cartao_debito', 'Débito'),
    ('cartao_credito', 'Crédito'),
    ('voucher', 'Voucher'),
    ('fiado', 'Fiado'),
]
ROTULOS_PAGAMENTO = dict(FORMAS_PAGAMENTO_VENDA)
ROTULOS_PAGAMENTO['cartao'] = 'Cartão'


def rotulo_forma_pagamento(forma):
    """Nome amigável da forma de pagamento (evita mostrar 'cartao_debito' cru
    no histórico). Formas desconhecidas caem num rótulo legível."""
    return ROTULOS_PAGAMENTO.get(forma) or (forma or '').replace('_', ' ').strip().capitalize() or '—'


def resumo_por_forma_pagamento(periodo='hoje'):
    """Totais de vendas separados por forma de pagamento (dinheiro, pix, débito,
    crédito, voucher, fiado...) no período pedido, pra identificar de relance
    quanto entrou em cada meio de pagamento. 'periodo' pode ser
    'hoje', 'semana', 'mes' ou 'tudo'."""
    hoje=date.today()
    cond, params='', []
    if periodo=='hoje':
        cond='AND date(v.data_hora)=?'; params=[hoje.isoformat()]
    elif periodo=='semana':
        cond='AND date(v.data_hora) BETWEEN ? AND ?'
        params=[(hoje-timedelta(days=hoje.weekday())).isoformat(), hoje.isoformat()]
    elif periodo=='mes':
        cond='AND date(v.data_hora) BETWEEN ? AND ?'
        params=[hoje.replace(day=1).isoformat(), hoje.isoformat()]
    conn=db.get_conn()
    try:
        rows=conn.execute(
            f'''SELECT v.forma_pagamento AS forma, COUNT(*) AS n,
                       COALESCE(SUM(v.valor_total),0) AS total,
                       COALESCE(SUM(v.taxa_paga),0) AS taxa
                FROM vendas v WHERE v.cancelada=0 {cond}
                GROUP BY v.forma_pagamento''', params).fetchall()
        por_forma={r['forma']: {'forma':r['forma'],'n':r['n'],'total':round(r['total'],2),'taxa':round(r['taxa'],2)} for r in rows}
        itens=[]
        for chave, rotulo in FORMAS_PAGAMENTO_VENDA:
            d=por_forma.pop(chave, None)
            if d: d['rotulo']=rotulo; itens.append(d)
        for chave, d in sorted(por_forma.items(), key=lambda kv:-kv[1]['total']):
            d['rotulo']=rotulo_forma_pagamento(chave); itens.append(d)
        return {'itens':itens,'total':round(sum(i['total'] for i in itens),2),'periodo':periodo}
    finally: conn.close()


def listar_vendas(data=None,limite=200,forma_pagamento=None):
    conn=db.get_conn()
    try:
        sql='SELECT v.*,c.nome AS cliente_nome FROM vendas v LEFT JOIN clientes c ON c.id=v.cliente_id'
        conds, params=[], []
        if data: conds.append('date(v.data_hora)=?'); params.append(data)
        if forma_pagamento: conds.append('v.forma_pagamento=?'); params.append(forma_pagamento)
        if conds: sql+=' WHERE '+' AND '.join(conds)
        sql+=' ORDER BY v.data_hora DESC LIMIT ?'; params.append(limite)
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally: conn.close()

def detalhar_venda(venda_id):
    conn=db.get_conn()
    try:
        v=conn.execute('SELECT v.*,c.nome AS cliente_nome FROM vendas v LEFT JOIN clientes c ON c.id=v.cliente_id WHERE v.id=?',(venda_id,)).fetchone()
        if not v: raise ErroOperacao('Venda não encontrada.')
        its=conn.execute('SELECT p.nome,p.unidade,iv.quantidade,iv.preco_unitario FROM itens_venda iv JOIN produtos p ON p.id=iv.produto_id WHERE iv.venda_id=?',(venda_id,)).fetchall(); r=dict(v); r['itens']=[dict(x) for x in its]; return r
    finally: conn.close()

def listar_clientes(busca=''):
    conn=db.get_conn()
    try:
        if busca: like=f'%{busca}%'; rows=conn.execute('SELECT * FROM clientes WHERE ativo=1 AND (nome LIKE ? OR telefone LIKE ?) ORDER BY nome',(like,like)).fetchall()
        else: rows=conn.execute('SELECT * FROM clientes WHERE ativo=1 ORDER BY nome').fetchall()
        out=[]
        for r in rows:
            c=dict(r); c['saldo_fiado']=saldo_fiado(c['id']); out.append(c)
        return out
    finally: conn.close()

def obter_cliente(cliente_id):
    conn=db.get_conn()
    try:
        r=conn.execute('SELECT * FROM clientes WHERE id=? AND ativo=1',(cliente_id,)).fetchone(); return dict(r) if r else None
    finally: conn.close()

def criar_cliente(nome,telefone='',observacao='',documento_tipo='',documento='',endereco=''):
    import gestao as _gestao
    _gestao.permitir('venda')
    nome=(nome or '').strip()
    if not nome: raise ErroOperacao('Informe o nome do cliente.')
    conn=db.get_conn()
    try:
        cur=conn.execute(
            'INSERT INTO clientes(nome,telefone,documento_tipo,documento,endereco,observacao) VALUES(?,?,?,?,?,?)',
            (nome,telefone or '',documento_tipo or '',documento or '',endereco or '',observacao or ''))
        conn.commit(); return cur.lastrowid
    finally: conn.close()

def atualizar_cliente(cliente_id,nome,telefone='',observacao='',documento_tipo='',documento='',endereco=''):
    import gestao as _gestao
    _gestao.permitir('venda')
    if not (nome or '').strip(): raise ErroOperacao('Informe o nome do cliente.')
    conn=db.get_conn()
    try:
        conn.execute(
            'UPDATE clientes SET nome=?,telefone=?,documento_tipo=?,documento=?,endereco=?,observacao=? WHERE id=?',
            (nome.strip(),telefone or '',documento_tipo or '',documento or '',endereco or '',observacao or '',cliente_id))
        conn.commit()
    finally: conn.close()

def desativar_cliente(cliente_id):
    import gestao as _gestao
    _gestao.permitir('credito')
    conn=db.get_conn()
    try: conn.execute('UPDATE clientes SET ativo=0 WHERE id=?',(cliente_id,)); conn.commit()
    finally: conn.close()

def extrato_cliente(cliente_id):
    """Extrato completo do cliente, mais recente primeiro: cada compra já com
    os itens (o que comprou, quando, por quanto) e cada pagamento/ajuste de
    fiado — tudo junto, pra ver de olho 'o que e quando a pessoa comprou'.
    Cada evento tem 'tipo' = 'compra' ou 'pagamento'."""
    conn=db.get_conn()
    try:
        vendas=conn.execute(
            '''SELECT id,data_hora,valor_total,desconto,forma_pagamento
               FROM vendas WHERE cliente_id=? ORDER BY data_hora DESC''',(cliente_id,)).fetchall()
        eventos=[]
        for v in vendas:
            itens=conn.execute(
                '''SELECT p.nome,p.unidade,iv.quantidade,iv.preco_unitario
                   FROM itens_venda iv JOIN produtos p ON p.id=iv.produto_id
                   WHERE iv.venda_id=? ORDER BY p.nome''',(v['id'],)).fetchall()
            eventos.append({
                'tipo':'compra','data_hora':v['data_hora'],'venda_id':v['id'],
                'valor':round(v['valor_total'],2),'desconto':round(v['desconto'] or 0,2),
                'forma_pagamento':v['forma_pagamento'],'itens':[dict(i) for i in itens],
            })
        pagamentos=conn.execute(
            '''SELECT id,data_hora,valor,forma_pagamento,observacao FROM pagamentos_fiado
               WHERE cliente_id=? ORDER BY data_hora DESC''',(cliente_id,)).fetchall()
        for p in pagamentos:
            eventos.append({
                'tipo':'pagamento','data_hora':p['data_hora'],'pagamento_id':p['id'],
                'valor':round(p['valor'],2),'forma_pagamento':p['forma_pagamento'] or '',
                'observacao':p['observacao'] or '',
            })
        eventos.sort(key=lambda e:e['data_hora'], reverse=True)
        return eventos
    finally: conn.close()

def pode_excluir_definitivamente(cliente_id):
    """Um cliente só pode ser apagado de vez do banco se nunca teve nenhuma
    venda nem pagamento/ajuste de fiado registrado — senão apagaria história
    financeira de verdade. Devolve (pode:bool, motivo:str, n_vendas, n_pagamentos)."""
    conn=db.get_conn()
    try:
        n_vendas=conn.execute('SELECT COUNT(*) n FROM vendas WHERE cliente_id=?',(cliente_id,)).fetchone()['n']
        n_pag=conn.execute('SELECT COUNT(*) n FROM pagamentos_fiado WHERE cliente_id=?',(cliente_id,)).fetchone()['n']
        if n_vendas or n_pag:
            return False, f'Esse cliente tem {n_vendas} venda(s) e {n_pag} pagamento(s) registrados — apagar de vez perderia esse histórico.', n_vendas, n_pag
        return True, '', n_vendas, n_pag
    finally: conn.close()

def excluir_cliente_definitivo(cliente_id, nome_confirmacao):
    """Apaga o cliente DE VEZ do banco (não é o 'desativar' de sempre) — só
    permitido se ele nunca teve venda ou pagamento, e só se o nome digitado
    bater exatamente com o nome cadastrado, como confirmação de segurança."""
    import gestao as _gestao
    _gestao.permitir('configurar')
    cliente=conn=None
    conn=db.get_conn()
    try:
        row=conn.execute('SELECT * FROM clientes WHERE id=?',(cliente_id,)).fetchone()
        if not row: raise ErroOperacao('Cliente não encontrado.')
        cliente=dict(row)
        if (nome_confirmacao or '').strip().lower() != (cliente['nome'] or '').strip().lower():
            raise ErroOperacao('O nome digitado não bate com o nome do cliente. Nada foi apagado.')
        pode, motivo, _n_v, _n_p = pode_excluir_definitivamente(cliente_id)
        if not pode:
            raise ErroOperacao(motivo + ' Use "Desativar" em vez de excluir.')
        conn.execute('DELETE FROM clientes WHERE id=?',(cliente_id,))
        conn.commit()
        return cliente['nome']
    finally:
        if conn: conn.close()

def saldo_fiado(cliente_id):
    conn=db.get_conn()
    try: return g.saldo_cliente(conn,cliente_id)/100
    finally: conn.close()

FORMAS_PAGAMENTO_FIADO = ['Dinheiro', 'Cartão de crédito', 'Cartão de débito', 'Pix']


def registrar_pagamento_fiado(cliente_id,valor,observacao='',forma_pagamento='dinheiro',**kwargs):
    try:
        return g.receber_fiado(cliente_id,valor,observacao,forma_pagamento,**kwargs)
    except g.ErroGestao as exc:
        raise ErroOperacao(str(exc)) from exc


def ajustar_saldo_cliente(cliente_id,valor,observacao='',forma_pagamento=''):
    g.permitir('credito')
    valor=g.centavos(valor)/100
    if not observacao.strip() or not valor: raise ErroOperacao('Informe valor e justificativa do ajuste. Ajustes não representam recebimentos.')
    with g.transacao() as conn:
        conn.execute("INSERT INTO pagamentos_fiado(cliente_id,valor,forma_pagamento,observacao,tipo,usuario) VALUES(?,?,'',?,'ajuste',?)",(cliente_id,valor,observacao,g.USUARIO))
        g.reconciliar_titulos(conn,cliente_id)
        g.auditar(conn,'ajuste_saldo','cliente',cliente_id,{'valor':valor,'motivo':observacao})


def _resumo_periodo(conn, data_ini, data_fim):
    d=g.resumo_financeiro(data_ini,data_fim)
    r=conn.execute('SELECT COUNT(*) FROM vendas WHERE cancelada=0 AND date(data_hora) BETWEEN ? AND ?',(data_ini,data_fim)).fetchone()
    itens=conn.execute('SELECT COALESCE(SUM(iv.quantidade),0) FROM itens_venda iv JOIN vendas v ON v.id=iv.venda_id WHERE v.cancelada=0 AND date(v.data_hora) BETWEEN ? AND ?',(data_ini,data_fim)).fetchone()[0]
    return dict(vendido=d['vendas'],numero_vendas=r[0],produtos_vendidos=itens,taxas=d['taxas'],lucro_estimado=d['vendas']-d['cmv'],lucro_liquido=d['resultado'])


def obter_dashboard():
    hoje=date.today()
    inicio_semana=hoje-timedelta(days=hoje.weekday())  # segunda-feira desta semana
    inicio_mes=hoje.replace(day=1)
    hoje_iso=hoje.isoformat()
    conn=db.get_conn()
    try:
        dia=_resumo_periodo(conn,hoje_iso,hoje_iso)
        semana=_resumo_periodo(conn,inicio_semana.isoformat(),hoje_iso)
        mes=_resumo_periodo(conn,inicio_mes.isoformat(),hoje_iso)
        mv=conn.execute('SELECT p.nome,p.unidade,SUM(iv.quantidade) qtd FROM itens_venda iv JOIN vendas v ON v.id=iv.venda_id JOIN produtos p ON p.id=iv.produto_id WHERE date(v.data_hora)=? GROUP BY p.id ORDER BY qtd DESC',(hoje_iso,)).fetchall()
        eb=conn.execute('SELECT nome,unidade,quantidade_estoque,estoque_minimo FROM produtos WHERE ativo=1 AND quantidade_estoque>0 AND quantidade_estoque<estoque_minimo ORDER BY quantidade_estoque').fetchall()
        ez=conn.execute('SELECT nome,unidade,quantidade_estoque FROM produtos WHERE ativo=1 AND quantidade_estoque<=0 ORDER BY nome').fetchall()
        return {'dia':dia,'semana':semana,'mes':mes,'mais_vendidos':[dict(x) for x in mv],'estoque_acabando':[dict(x) for x in eb],'estoque_zerado':[dict(x) for x in ez]}
    finally: conn.close()

def consumo_cliente(cliente_id, ano_mes=None):
    """Retorna o que o cliente comprou, agrupado por produto, e o total por mês.
    ano_mes: 'AAAA-MM' pra filtrar um mês específico; None traz tudo."""
    conn=db.get_conn()
    try:
        base='''SELECT p.nome,p.unidade,SUM(iv.quantidade) qtd,SUM(iv.quantidade*iv.preco_unitario) total
                FROM itens_venda iv JOIN vendas v ON v.id=iv.venda_id JOIN produtos p ON p.id=iv.produto_id
                WHERE v.cliente_id=?'''
        params=[cliente_id]
        if ano_mes:
            base+=" AND strftime('%Y-%m',v.data_hora)=?"; params.append(ano_mes)
        base+=' GROUP BY p.id ORDER BY qtd DESC'
        produtos=conn.execute(base,params).fetchall()

        meses=conn.execute('''SELECT strftime('%Y-%m',data_hora) mes,COUNT(*) n,SUM(valor_total) total
                               FROM vendas WHERE cliente_id=? GROUP BY mes ORDER BY mes DESC''',(cliente_id,)).fetchall()
        return {'produtos':[dict(x) for x in produtos],'meses':[dict(x) for x in meses]}
    finally: conn.close()

# --- Consumo interno (o que a própria casa/família tira do estoque do mercadinho) ---
# Dá baixa no estoque pelo preço de CUSTO (não é venda, não entra na receita nem no lucro
# do painel), pra separar do que é vendido pro cliente e mostrar quanto em R$ (a preço de
# custo) a casa consumiu, com os itens usados em cada registro.

MOTIVOS_CONSUMO = ['Limpeza', 'Lanches da equipe', 'Embalagens e insumos operacionais (sacola, saco, filme)', 'Consumo pessoal/família', 'Outro']

def registrar_consumo_interno(itens,motivo='',observacao='',responsavel=None,centro_custo=''):
    try:
        return g.registrar_baixa(itens,motivo,observacao,False,responsavel,centro_custo)
    except g.ErroGestao as exc:
        raise ErroOperacao(str(exc)) from exc


def listar_consumo_interno(limite=200):
    conn=db.get_conn()
    try:
        rows=conn.execute('SELECT * FROM consumo_interno ORDER BY data_hora DESC LIMIT ?',(limite,)).fetchall()
        return [dict(r) for r in rows]
    finally: conn.close()

def detalhar_consumo_interno(consumo_id):
    conn=db.get_conn()
    try:
        c=conn.execute('SELECT * FROM consumo_interno WHERE id=?',(consumo_id,)).fetchone()
        if not c: return None
        itens=conn.execute('''SELECT ici.*,p.nome,p.unidade FROM itens_consumo_interno ici
                               JOIN produtos p ON p.id=ici.produto_id WHERE ici.consumo_id=?
                               ORDER BY ici.id''',(consumo_id,)).fetchall()
        d=dict(c); d['itens']=[dict(x) for x in itens]; return d
    finally: conn.close()

def resumo_consumo_interno():
    """Total consumido (a preço de custo) hoje, nesta semana (seg. a hoje) e neste mês."""
    hoje=date.today(); inicio_semana=hoje-timedelta(days=hoje.weekday()); inicio_mes=hoje.replace(day=1)
    hoje_iso=hoje.isoformat()
    conn=db.get_conn()
    try:
        def resumo(ini,fim):
            r=conn.execute('SELECT COUNT(*) n,COALESCE(SUM(valor_total),0) total FROM consumo_interno WHERE date(data_hora) BETWEEN ? AND ?',(ini,fim)).fetchone()
            return {'numero':r['n'],'valor_total':round(r['total'],2)}
        return {'dia':resumo(hoje_iso,hoje_iso),'semana':resumo(inicio_semana.isoformat(),hoje_iso),'mes':resumo(inicio_mes.isoformat(),hoje_iso)}
    finally: conn.close()

def resumo_consumo_por_motivo(inicio=None, fim=None):
    """Quanto foi gasto em cada motivo (produção, embalagem, consumo pessoal, outro)
    no período — é isso que separa 'quanto gastei de sacola' de 'quanto a família comeu'."""
    conn=db.get_conn()
    try:
        clausulas, params = [], []
        if inicio: clausulas.append('date(data_hora) >= ?'); params.append(inicio)
        if fim: clausulas.append('date(data_hora) <= ?'); params.append(fim)
        cond = (' AND ' + ' AND '.join(clausulas)) if clausulas else ''
        rows = conn.execute(
            f'''SELECT COALESCE(NULLIF(TRIM(motivo),''),'(sem motivo)') motivo, COUNT(*) n, COALESCE(SUM(valor_total),0) total
                FROM consumo_interno WHERE 1=1{cond} GROUP BY motivo ORDER BY total DESC''', params).fetchall()
        return [dict(r) for r in rows]
    finally: conn.close()

# ----------------------------------------------------------------------
# PERDAS — produto jogado fora (venceu, estragou, quebrou): prejuízo puro,
# diferente do consumo interno porque ninguém aproveitou nada.
# ----------------------------------------------------------------------
MOTIVOS_PERDA = ['Validade vencida', 'Estragado/danificado', 'Quebra/avaria', 'Furto', 'Outro']

def registrar_perda(itens,motivo='',observacao='',responsavel=None):
    try:
        return g.registrar_baixa(itens,motivo,observacao,True,responsavel)
    except g.ErroGestao as exc:
        raise ErroOperacao(str(exc)) from exc


def listar_perdas(limite=200):
    conn=db.get_conn()
    try:
        rows=conn.execute('SELECT * FROM perdas ORDER BY data_hora DESC LIMIT ?',(limite,)).fetchall()
        return [dict(r) for r in rows]
    finally: conn.close()

def detalhar_perda(perda_id):
    conn=db.get_conn()
    try:
        p=conn.execute('SELECT * FROM perdas WHERE id=?',(perda_id,)).fetchone()
        if not p: return None
        itens=conn.execute('''SELECT ip.*,p.nome,p.unidade FROM itens_perda ip
                               JOIN produtos p ON p.id=ip.produto_id WHERE ip.perda_id=?
                               ORDER BY ip.id''',(perda_id,)).fetchall()
        d=dict(p); d['itens']=[dict(x) for x in itens]; return d
    finally: conn.close()

def total_perdas_periodo(inicio=None, fim=None):
    """Total perdido (a preço de custo) num período livre — usado na aba Análises,
    pra mostrar o quanto isso pesa no lucro real."""
    conn=db.get_conn()
    try:
        clausulas, params = [], []
        if inicio: clausulas.append('date(data_hora) >= ?'); params.append(inicio)
        if fim: clausulas.append('date(data_hora) <= ?'); params.append(fim)
        cond = (' AND ' + ' AND '.join(clausulas)) if clausulas else ''
        r = conn.execute(f'SELECT COUNT(*) n, COALESCE(SUM(valor_total),0) total FROM perdas WHERE 1=1{cond}', params).fetchone()
        return {'numero': r['n'], 'valor_total': round(r['total'], 2)}
    finally: conn.close()

def resumo_perdas():
    """Total perdido (a preço de custo) hoje, nesta semana e neste mês."""
    hoje=date.today(); inicio_semana=hoje-timedelta(days=hoje.weekday()); inicio_mes=hoje.replace(day=1)
    hoje_iso=hoje.isoformat()
    conn=db.get_conn()
    try:
        def resumo(ini,fim):
            r=conn.execute('SELECT COUNT(*) n,COALESCE(SUM(valor_total),0) total FROM perdas WHERE date(data_hora) BETWEEN ? AND ?',(ini,fim)).fetchone()
            return {'numero':r['n'],'valor_total':round(r['total'],2)}
        return {'dia':resumo(hoje_iso,hoje_iso),'semana':resumo(inicio_semana.isoformat(),hoje_iso),'mes':resumo(inicio_mes.isoformat(),hoje_iso)}
    finally: conn.close()

def resumo_perdas_por_motivo(inicio=None, fim=None):
    conn=db.get_conn()
    try:
        clausulas, params = [], []
        if inicio: clausulas.append('date(data_hora) >= ?'); params.append(inicio)
        if fim: clausulas.append('date(data_hora) <= ?'); params.append(fim)
        cond = (' AND ' + ' AND '.join(clausulas)) if clausulas else ''
        rows = conn.execute(
            f'''SELECT motivo, COUNT(*) n, COALESCE(SUM(valor_total),0) total
                FROM perdas WHERE 1=1{cond} GROUP BY motivo ORDER BY total DESC''', params).fetchall()
        return [dict(r) for r in rows]
    finally: conn.close()
