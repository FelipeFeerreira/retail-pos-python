"""
analises.py

Camada de análise de vendas do mercadinho: responde às perguntas de negócio
que interessam de verdade pro dono — o que mais vende, em qual dia da
semana, em que horário dá mais movimento, como foi cada dia/semana/mês e
como feriados e dias de pagamento pesam no caixa (bem mais do que datas
comemorativas soltas).

Segue o mesmo padrão de operacoes.py: funções puras que abrem e fecham sua
própria conexão e devolvem dicts/listas prontos pra interface, sem guardar
estado. Nenhuma função aqui grava no banco — é só leitura.

COMPATIBILIDADE COM QUALQUER mercadinho.db
------------------------------------------
Este módulo não exige nenhuma coluna nova. Antes de montar as consultas ele
verifica quais colunas existem de verdade no banco aberto (`taxa_paga`,
`voucher_marca`, `cliente_id`) e usa um valor neutro no lugar das que
faltarem. Então dá pra trocar o mercadinho.db por outro do mesmo aplicativo
— mais antigo, de outro período, um backup — e tudo aqui continua
respondendo, sem migração manual e sem editar código.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import database as db
import calendario as cal
from categorias import CATEGORIAS as CATEGORIAS_PADRAO
from operacoes import FORMAS_PAGAMENTO_VENDA, rotulo_forma_pagamento

NOMES_DIA_SEMANA = ['Domingo', 'Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado']
NOMES_DIA_SEMANA_ABREV = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb']
NOMES_MES = ['', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
             'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']

GRANULARIDADES = ['dia', 'semana', 'mes']

# Cache das colunas existentes, resetado quando o banco troca de caminho.
_cache_colunas = {'caminho': None, 'vendas': set()}


# ----------------------------------------------------------------------
# Compatibilidade: descobrir o que o banco aberto realmente tem
# ----------------------------------------------------------------------
def _colunas_vendas(conn):
    if _cache_colunas['caminho'] != db.DB_PATH or not _cache_colunas['vendas']:
        colunas = {r['name'] for r in conn.execute('PRAGMA table_info(vendas)').fetchall()}
        _cache_colunas['caminho'] = db.DB_PATH
        _cache_colunas['vendas'] = colunas
    return _cache_colunas['vendas']


def invalidar_cache():
    """Chamar se o arquivo do banco for trocado durante a execução."""
    _cache_colunas['caminho'] = None
    _cache_colunas['vendas'] = set()


def _expr_taxa(conn, alias='v'):
    """'v.taxa_paga' se a coluna existir; senão '0' — assim bancos antigos,
    sem controle de taxa de maquininha, continuam sendo analisados."""
    return f'{alias}.taxa_paga' if 'taxa_paga' in _colunas_vendas(conn) else '0'


def _tem_cliente(conn):
    return 'cliente_id' in _colunas_vendas(conn)


def diagnostico_banco():
    """Raio-X do banco aberto: o que ele tem, de quando até quando, e quais
    recursos opcionais estão disponíveis. Serve pra conferir na hora se um
    banco trazido de fora vai ser analisado por inteiro."""
    conn = db.get_conn()
    try:
        colunas = _colunas_vendas(conn)
        r = conn.execute(
            'SELECT COUNT(*) n, MIN(date(data_hora)) ini, MAX(date(data_hora)) fim FROM vendas'
        ).fetchone()
        produtos = conn.execute('SELECT COUNT(*) n FROM produtos WHERE ativo = 1').fetchone()['n']
        try:
            clientes = conn.execute('SELECT COUNT(*) n FROM clientes WHERE ativo = 1').fetchone()['n']
        except Exception:
            clientes = 0
        return {
            'caminho': db.DB_PATH,
            'produtos_ativos': produtos,
            'clientes_ativos': clientes,
            'total_vendas': r['n'],
            'primeira_venda': r['ini'],
            'ultima_venda': r['fim'],
            'tem_taxa_paga': 'taxa_paga' in colunas,
            'tem_voucher': 'voucher_marca' in colunas,
            'tem_cliente': 'cliente_id' in colunas,
        }
    finally:
        conn.close()


# ----------------------------------------------------------------------
# Períodos
# ----------------------------------------------------------------------
def dia_semana_hoje():
    """Índice de hoje no padrão SQLite/deste módulo: 0=Domingo ... 6=Sábado."""
    return (date.today().weekday() + 1) % 7


def periodo_preset(chave):
    """Converte um período com nome em (inicio, fim) no formato 'AAAA-MM-DD'.
    Para 'tudo' devolve (None, None) — sem filtro de data."""
    hoje = date.today()
    if chave == 'hoje':
        return hoje.isoformat(), hoje.isoformat()
    if chave == 'ontem':
        d = hoje - timedelta(days=1)
        return d.isoformat(), d.isoformat()
    if chave == '7dias':
        return (hoje - timedelta(days=6)).isoformat(), hoje.isoformat()
    if chave == '30dias':
        return (hoje - timedelta(days=29)).isoformat(), hoje.isoformat()
    if chave == '90dias':
        return (hoje - timedelta(days=89)).isoformat(), hoje.isoformat()
    if chave == 'mes':
        return hoje.replace(day=1).isoformat(), hoje.isoformat()
    if chave == 'mes_passado':
        primeiro_deste = hoje.replace(day=1)
        fim_passado = primeiro_deste - timedelta(days=1)
        return fim_passado.replace(day=1).isoformat(), fim_passado.isoformat()
    if chave == 'ano':
        return hoje.replace(month=1, day=1).isoformat(), hoje.isoformat()
    return None, None


def rotulo_periodo(inicio, fim):
    """Texto amigável do período, pra cabeçalho de tela e de relatório."""
    if not inicio and not fim:
        return 'Todo o histórico'

    def br(d):
        return datetime.strptime(d, '%Y-%m-%d').strftime('%d/%m/%Y')

    if inicio == fim:
        return br(inicio)
    if not inicio:
        return f'Até {br(fim)}'
    if not fim:
        return f'A partir de {br(inicio)}'
    return f'{br(inicio)} a {br(fim)}'


def _filtro_data(inicio, fim, alias='v', forma=None):
    """Monta a cláusula extra de WHERE (começando com AND) e a lista de parâmetros
    pro filtro de período, usando o alias informado para a tabela vendas. Se
    'forma' for informada, restringe a análise a uma forma de pagamento só
    (dinheiro, pix, cartao_debito...) — é o filtro que permite analisar como
    se comporta cada meio de pagamento separadamente."""
    clausulas, params = [f'{alias}.cancelada=0'], []
    if inicio:
        clausulas.append(f'date({alias}.data_hora) >= ?')
        params.append(inicio)
    if fim:
        clausulas.append(f'date({alias}.data_hora) <= ?')
        params.append(fim)
    if forma:
        clausulas.append(f'{alias}.forma_pagamento = ?')
        params.append(forma)
    return (' AND ' + ' AND '.join(clausulas)) if clausulas else '', params


def _custo_itens_venda(conn, venda_id):
    return conn.execute(
        """SELECT COALESCE(SUM(iv.quantidade * COALESCE(iv.custo_unitario, p.preco_custo)), 0) c
           FROM itens_venda iv JOIN produtos p ON p.id = iv.produto_id
           WHERE iv.venda_id = ?""", (venda_id,)).fetchone()['c'] or 0.0


def _eventos_fiado_reconhecidos(conn,inicio=None,fim=None):
    # Recebimentos são fluxo de caixa, não novas vendas por competência.
    return []


def _chave_periodo(data_str, granularidade):
    d = datetime.strptime(data_str, '%Y-%m-%d')
    if granularidade == 'semana':
        return d.strftime('%Y-%W')
    if granularidade == 'mes':
        return d.strftime('%Y-%m')
    return d.strftime('%Y-%m-%d')


def intervalo_dados():
    """Primeira e última data com venda no banco — usado pra sugerir o período
    quando o banco trazido é de outra época."""
    conn = db.get_conn()
    try:
        r = conn.execute(
            'SELECT MIN(date(data_hora)) ini, MAX(date(data_hora)) fim FROM vendas'
        ).fetchone()
        return r['ini'], r['fim']
    finally:
        conn.close()


# ----------------------------------------------------------------------
# Resumos
# ----------------------------------------------------------------------
def resumo_periodo(inicio=None, fim=None, forma=None):
    """Faturamento, número de vendas, itens vendidos, ticket médio, lucro
    estimado (já descontando taxa de maquininha/voucher) e quantos dias
    tiveram movimento dentro do período.

    Vendas à vista e fiado entram na data da venda (competência).
    Recebimentos são mostrados separadamente no financeiro.
    Custos anteriores à migração são estimados e sinalizados na interface.
    'forma' restringe tudo a uma forma de pagamento (ex.: só Pix)."""
    conn = db.get_conn()
    try:
        cond, params = _filtro_data(inicio, fim, forma=forma)
        taxa = _expr_taxa(conn)
        cond_pago = cond + " AND v.cancelada=0"
        r = conn.execute(
            f"""SELECT COUNT(*) n, COALESCE(SUM(v.valor_total), 0) total,
                       COALESCE(SUM({taxa}), 0) taxas,
                       COALESCE(SUM(v.desconto), 0) descontos
                FROM vendas v WHERE 1=1{cond_pago}""", params).fetchone()
        datas_pagas = {row['d'] for row in conn.execute(
            f"""SELECT DISTINCT date(v.data_hora) d FROM vendas v WHERE 1=1{cond_pago}""",
            params).fetchall()}
        margem = conn.execute(
            f"""SELECT COALESCE(SUM(iv.quantidade * (iv.preco_unitario - COALESCE(iv.custo_unitario, p.preco_custo))), 0) lucro
                FROM itens_venda iv
                JOIN vendas v ON v.id = iv.venda_id
                JOIN produtos p ON p.id = iv.produto_id
                WHERE 1=1{cond_pago}""", params).fetchone()['lucro']
        itens = conn.execute(
            f"""SELECT COALESCE(SUM(iv.quantidade), 0) t
                FROM itens_venda iv JOIN vendas v ON v.id = iv.venda_id
                WHERE 1=1{cond}""", params).fetchone()['t']

        eventos = _eventos_fiado_reconhecidos(conn, inicio, fim)
        fiado_valor = sum(e['valor'] for e in eventos)
        fiado_custo = sum(e['custo'] for e in eventos)
        vendas_fiado = {e['venda_id'] for e in eventos}
        datas_fiado = {e['data'] for e in eventos}

        n = r['n'] + len(vendas_fiado)
        total = round((r['total'] or 0) + fiado_valor, 2)
        dias = len(datas_pagas | datas_fiado)
        return {
            'faturamento': total,
            'numero_vendas': n,
            'itens_vendidos': round(itens, 3),
            'ticket_medio': round(total / n, 2) if n else 0.0,
            'taxas': round(r['taxas'], 2),
            'descontos': round(r['descontos'], 2),
            'lucro_estimado': round((margem or 0) + fiado_valor - fiado_custo - r['taxas'] - r['descontos'], 2),
            'dias_com_venda': dias,
            'media_por_dia': round(total / dias, 2) if dias else 0.0,
            'vendas_por_dia': round(n / dias, 1) if dias else 0.0,
        }
    finally:
        conn.close()


# ----------------------------------------------------------------------
# Séries temporais: dia, semana, mês
# ----------------------------------------------------------------------
def serie_temporal(granularidade='dia', inicio=None, fim=None, limite=None, forma=None):
    """Evolução do faturamento agrupada por dia, semana ou mês.

    Vendas fiado entram na data da venda (competência). Cada item traz chave
    (ordenável), rótulo pra exibição, número de vendas, faturamento, ticket
    médio, lucro estimado e o intervalo de datas do grupo.
    'forma' restringe a série a uma forma de pagamento."""
    if granularidade not in GRANULARIDADES:
        granularidade = 'dia'
    formato = {'dia': '%Y-%m-%d', 'semana': '%Y-%W', 'mes': '%Y-%m'}[granularidade]

    conn = db.get_conn()
    try:
        cond, params = _filtro_data(inicio, fim, forma=forma)
        taxa = _expr_taxa(conn)
        cond_pago = cond + " AND v.cancelada=0"
        rows = conn.execute(
            f"""SELECT strftime('{formato}', v.data_hora) chave,
                       MIN(date(v.data_hora)) primeiro, MAX(date(v.data_hora)) ultimo,
                       COUNT(*) n, COALESCE(SUM(v.valor_total), 0) total,
                       COALESCE(SUM({taxa}), 0) taxas, COALESCE(SUM(v.desconto),0) descontos
                FROM vendas v WHERE 1=1{cond_pago}
                GROUP BY chave ORDER BY chave""", params).fetchall()

        lucros = {r['chave']: r['lucro'] for r in conn.execute(
            f"""SELECT strftime('{formato}', v.data_hora) chave,
                       COALESCE(SUM(iv.quantidade * (iv.preco_unitario - COALESCE(iv.custo_unitario, p.preco_custo))), 0) lucro
                FROM itens_venda iv
                JOIN vendas v ON v.id = iv.venda_id
                JOIN produtos p ON p.id = iv.produto_id
                WHERE 1=1{cond_pago}
                GROUP BY chave""", params).fetchall()}

        base = {}
        for r in rows:
            base[r['chave']] = {
                'primeiro': r['primeiro'], 'ultimo': r['ultimo'],
                'n': r['n'], 'total': r['total'] or 0.0,
                'lucro': (lucros.get(r['chave'], 0) or 0) - (r['taxas'] or 0) - (r['descontos'] or 0),
            }

        grupos_fiado = {}
        for e in _eventos_fiado_reconhecidos(conn, inicio, fim):
            chave = _chave_periodo(e['data'], granularidade)
            g = grupos_fiado.setdefault(chave, {
                'total': 0.0, 'lucro': 0.0, 'vendas': set(),
                'primeiro': e['data'], 'ultimo': e['data'],
            })
            g['total'] += e['valor']
            g['lucro'] += e['valor'] - e['custo']
            g['vendas'].add(e['venda_id'])
            g['primeiro'] = min(g['primeiro'], e['data'])
            g['ultimo'] = max(g['ultimo'], e['data'])

        resultado = []
        for chave in sorted(set(base) | set(grupos_fiado)):
            b = base.get(chave)
            g = grupos_fiado.get(chave)
            n = (b['n'] if b else 0) + (len(g['vendas']) if g else 0)
            total = round((b['total'] if b else 0.0) + (g['total'] if g else 0.0), 2)
            lucro = round((b['lucro'] if b else 0.0) + (g['lucro'] if g else 0.0), 2)
            primeiro = min(x for x in (b['primeiro'] if b else None, g['primeiro'] if g else None) if x)
            ultimo = max(x for x in (b['ultimo'] if b else None, g['ultimo'] if g else None) if x)
            resultado.append({
                'chave': chave,
                'rotulo': _rotulo_grupo(granularidade, chave, primeiro, ultimo),
                'primeiro_dia': primeiro,
                'ultimo_dia': ultimo,
                'numero_vendas': n,
                'faturamento': total,
                'ticket_medio': round(total / n, 2) if n else 0.0,
                'lucro_estimado': lucro,
            })
        if limite:
            resultado = resultado[-limite:]
        return resultado
    finally:
        conn.close()


def _rotulo_grupo(granularidade, chave, primeiro, ultimo):
    try:
        if granularidade == 'dia':
            d = datetime.strptime(chave, '%Y-%m-%d')
            return f"{d.strftime('%d/%m')} ({NOMES_DIA_SEMANA_ABREV[(d.weekday() + 1) % 7]})"
        if granularidade == 'mes':
            ano, mes = chave.split('-')
            return f'{NOMES_MES[int(mes)]}/{ano}'
        ini = datetime.strptime(primeiro, '%Y-%m-%d').strftime('%d/%m')
        fim_ = datetime.strptime(ultimo, '%Y-%m-%d').strftime('%d/%m')
        return f'{ini}–{fim_}'
    except (ValueError, IndexError):
        return chave


def vendas_por_dia_semana(inicio=None, fim=None, forma=None):
    """Pra cada dia da semana (0=Domingo...6=Sábado): quantas vendas, faturamento,
    ticket médio e a média por ocorrência daquele dia no período. Sempre devolve
    os 7 dias, mesmo os que não tiveram venda.

    Vendas fiado entram no dia da venda (competência).
    'forma' restringe a uma forma de pagamento (ex.: só cartão de débito)."""
    conn = db.get_conn()
    try:
        cond, params = _filtro_data(inicio, fim, forma=forma)
        cond_pago = cond + " AND v.cancelada=0"
        linhas = conn.execute(
            f"""SELECT CAST(strftime('%w', v.data_hora) AS INTEGER) dia,
                       COUNT(*) n, COALESCE(SUM(v.valor_total), 0) total
                FROM vendas v WHERE 1=1{cond_pago}
                GROUP BY dia""", params).fetchall()
        por_dia = {r['dia']: r for r in linhas}

        datas_por_dia = {}
        for row in conn.execute(
                f"""SELECT DISTINCT CAST(strftime('%w', v.data_hora) AS INTEGER) dia,
                           date(v.data_hora) data
                    FROM vendas v WHERE 1=1{cond_pago}""", params).fetchall():
            datas_por_dia.setdefault(row['dia'], set()).add(row['data'])

        extra_por_dia = {}
        for e in _eventos_fiado_reconhecidos(conn, inicio, fim):
            d = (datetime.strptime(e['data'], '%Y-%m-%d').weekday() + 1) % 7
            extra = extra_por_dia.setdefault(d, {'total': 0.0, 'vendas': set(), 'datas': set()})
            extra['total'] += e['valor']
            extra['vendas'].add(e['venda_id'])
            extra['datas'].add(e['data'])

        resultado = []
        for d in range(7):
            r = por_dia.get(d)
            extra = extra_por_dia.get(d)
            n = (r['n'] if r else 0) + (len(extra['vendas']) if extra else 0)
            total = round((r['total'] if r else 0.0) + (extra['total'] if extra else 0.0), 2)
            ocorrencias = len(datas_por_dia.get(d, set()) | (extra['datas'] if extra else set()))
            resultado.append({
                'dia': d, 'nome': NOMES_DIA_SEMANA[d], 'abrev': NOMES_DIA_SEMANA_ABREV[d],
                'numero_vendas': n, 'faturamento': total,
                'ticket_medio': round(total / n, 2) if n else 0.0,
                'ocorrencias': ocorrencias,
                'media_por_ocorrencia': round(total / ocorrencias, 2) if ocorrencias else 0.0,
            })
        return resultado
    finally:
        conn.close()


def melhor_pior_dia(inicio=None, fim=None, forma=None):
    """Devolve (melhor_dia, pior_dia) por faturamento, ignorando dias sem venda.
    Se não houver nenhuma venda no período, devolve (None, None)."""
    dias = vendas_por_dia_semana(inicio, fim, forma=forma)
    validos = [d for d in dias if d['numero_vendas'] > 0]
    if not validos:
        return None, None
    return (max(validos, key=lambda d: d['faturamento']),
            min(validos, key=lambda d: d['faturamento']))


def vendas_por_hora(inicio=None, fim=None, forma=None):
    """Distribuição de vendas pelas 24 horas do dia, pra achar o horário de pico.
    'forma' restringe a uma forma de pagamento."""
    conn = db.get_conn()
    try:
        cond, params = _filtro_data(inicio, fim, forma=forma)
        linhas = conn.execute(
            f"""SELECT CAST(strftime('%H', v.data_hora) AS INTEGER) hora,
                       COUNT(*) n, COALESCE(SUM(v.valor_total), 0) total
                FROM vendas v WHERE 1=1{cond}
                GROUP BY hora""", params).fetchall()
        por_hora = {r['hora']: r for r in linhas}
        return [{
            'hora': h,
            'numero_vendas': por_hora[h]['n'] if h in por_hora else 0,
            'faturamento': round(por_hora[h]['total'], 2) if h in por_hora else 0.0,
        } for h in range(24)]
    finally:
        conn.close()


# ----------------------------------------------------------------------
# Produtos, categorias, clientes e pagamento
# ----------------------------------------------------------------------
def produtos_mais_vendidos(inicio=None, fim=None, limite=15, forma=None):
    """Ranking de produtos por quantidade vendida no período (com receita junto).
    'forma' permite ver o que mais vende quando o pagamento foi de um meio só."""
    conn = db.get_conn()
    try:
        cond, params = _filtro_data(inicio, fim, forma=forma)
        rows = conn.execute(
            f"""SELECT p.id, p.nome, p.unidade, COALESCE(p.categoria, 'Sem categoria') categoria,
                       SUM(iv.quantidade) qtd, SUM(iv.quantidade * iv.preco_unitario) receita,
                       COUNT(DISTINCT iv.venda_id) n_vendas
                FROM itens_venda iv
                JOIN vendas v ON v.id = iv.venda_id
                JOIN produtos p ON p.id = iv.produto_id
                WHERE 1=1{cond}
                GROUP BY p.id ORDER BY qtd DESC LIMIT ?""", params + [limite]).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def produtos_por_dia_semana(dia_semana, inicio=None, fim=None, limite=8, forma=None):
    """Top produtos vendidos especificamente num dia da semana (0=Domingo...6=Sábado).
    É a pergunta central do mercadinho de bairro: o que vende mais numa terça,
    numa sexta, num domingo. 'forma' restringe a uma forma de pagamento."""
    conn = db.get_conn()
    try:
        cond, params = _filtro_data(inicio, fim, forma=forma)
        rows = conn.execute(
            f"""SELECT p.nome, p.unidade, COALESCE(p.categoria, 'Sem categoria') categoria,
                       SUM(iv.quantidade) qtd, SUM(iv.quantidade * iv.preco_unitario) receita
                FROM itens_venda iv
                JOIN vendas v ON v.id = iv.venda_id
                JOIN produtos p ON p.id = iv.produto_id
                WHERE CAST(strftime('%w', v.data_hora) AS INTEGER) = ?{cond}
                GROUP BY p.id ORDER BY qtd DESC LIMIT ?""",
            [dia_semana] + params + [limite]).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def vendas_por_categoria(inicio=None, fim=None, forma=None):
    """Receita e quantidade por categoria de produto, do maior pro menor.
    'forma' restringe a uma forma de pagamento."""
    conn = db.get_conn()
    try:
        cond, params = _filtro_data(inicio, fim, forma=forma)
        rows = conn.execute(
            f"""SELECT COALESCE(NULLIF(TRIM(p.categoria), ''), 'Sem categoria') categoria,
                       SUM(iv.quantidade) qtd,
                       SUM(iv.quantidade * iv.preco_unitario) receita,
                       COUNT(DISTINCT iv.venda_id) n_vendas
                FROM itens_venda iv
                JOIN vendas v ON v.id = iv.venda_id
                JOIN produtos p ON p.id = iv.produto_id
                WHERE 1=1{cond}
                GROUP BY COALESCE(NULLIF(TRIM(p.categoria), ''), 'Sem categoria')
                ORDER BY receita DESC""", params).fetchall()
        itens = [dict(r) for r in rows]
        total = sum(i['receita'] for i in itens) or 1
        for i in itens:
            i['receita'] = round(i['receita'], 2)
            i['pct'] = round(i['receita'] / total * 100, 1)
        return itens
    finally:
        conn.close()


def vendas_por_forma_pagamento(inicio=None, fim=None):
    """Quanto entrou por dinheiro, pix, crédito, débito, voucher e fiado —
    com a taxa paga em cada forma, quando o banco tiver esse controle.
    Cada item traz também o rótulo amigável ('Débito' em vez de 'cartao_debito')
    e a ordem fixa das formas, pra ficar igual em todas as telas."""
    conn = db.get_conn()
    try:
        cond, params = _filtro_data(inicio, fim)
        taxa = _expr_taxa(conn)
        rows = conn.execute(
            f"""SELECT v.forma_pagamento forma, COUNT(*) n,
                       COALESCE(SUM(v.valor_total), 0) total,
                       COALESCE(SUM({taxa}), 0) taxas
                FROM vendas v WHERE 1=1{cond}
                GROUP BY v.forma_pagamento""", params).fetchall()
        por_forma = {r['forma']: dict(r) for r in rows}
        itens = []
        for chave, rotulo in FORMAS_PAGAMENTO_VENDA:
            d = por_forma.pop(chave, None)
            if d:
                d['rotulo'] = rotulo
                itens.append(d)
        for chave, d in sorted(por_forma.items(), key=lambda kv: -(kv[1]['total'] or 0)):
            d['rotulo'] = rotulo_forma_pagamento(chave)
            itens.append(d)
        total_geral = sum(i['total'] for i in itens) or 1
        for i in itens:
            i['total'] = round(i['total'], 2)
            i['taxas'] = round(i['taxas'], 2)
            i['liquido'] = round(i['total'] - i['taxas'], 2)
            i['pct'] = round(i['total'] / total_geral * 100, 1)
        return itens
    finally:
        conn.close()


def top_clientes(inicio=None, fim=None, limite=10, forma=None):
    """Ranking de clientes cadastrados por total gasto no período.
    'forma' restringe a uma forma de pagamento."""
    conn = db.get_conn()
    try:
        if not _tem_cliente(conn):
            return []
        cond, params = _filtro_data(inicio, fim, forma=forma)
        rows = conn.execute(
            f"""SELECT c.id, c.nome, COUNT(*) n_compras,
                       COALESCE(SUM(v.valor_total), 0) total,
                       MAX(date(v.data_hora)) ultima_compra
                FROM vendas v JOIN clientes c ON c.id = v.cliente_id
                WHERE 1=1{cond}
                GROUP BY c.id ORDER BY total DESC LIMIT ?""", params + [limite]).fetchall()
        itens = [dict(r) for r in rows]
        for i in itens:
            i['total'] = round(i['total'], 2)
            i['ticket_medio'] = round(i['total'] / i['n_compras'], 2) if i['n_compras'] else 0.0
        return itens
    finally:
        conn.close()


def curva_abc(inicio=None, fim=None, forma=None):
    """Classifica os produtos vendidos no período em A (≈80% da receita),
    B (até ≈95%) e C (o restante) — mostra onde vale concentrar reposição
    e atenção no dia a dia. 'forma' restringe a uma forma de pagamento."""
    produtos = produtos_mais_vendidos(inicio, fim, limite=100000, forma=forma)
    produtos.sort(key=lambda p: p['receita'], reverse=True)
    total = sum(p['receita'] for p in produtos) or 1
    acumulado = 0.0
    for p in produtos:
        acumulado += p['receita']
        pct_acumulado = acumulado / total * 100
        p['pct_receita'] = round(p['receita'] / total * 100, 2)
        p['pct_acumulado'] = round(pct_acumulado, 2)
        p['classe'] = 'A' if pct_acumulado <= 80 else ('B' if pct_acumulado <= 95 else 'C')
    return produtos


# ----------------------------------------------------------------------
# Tipo de dia: feriado, véspera, dia de pagamento, fim de semana
# ----------------------------------------------------------------------
# É isso — e não a data comemorativa em si — que de fato muda o movimento
# de um mercadinho de bairro no dia a dia.
def vendas_por_classe_dia(inicio=None, fim=None, forma=None):
    """Agrupa todo o histórico de vendas por tipo de dia: Feriado, Véspera
    de feriado, Dia de pagamento, Fim de semana ou Dia normal — em vez de
    por data comemorativa. Mostra também a média por dia de cada classe,
    porque feriado é raro e a soma sozinha enganaria a comparação.
    'forma' restringe a uma forma de pagamento."""
    conn = db.get_conn()
    try:
        cond, params = _filtro_data(inicio, fim, forma=forma)
        rows = conn.execute(
            f"""SELECT date(v.data_hora) dia, COUNT(*) n, COALESCE(SUM(v.valor_total), 0) total
                FROM vendas v WHERE 1=1{cond} GROUP BY dia""", params).fetchall()
    finally:
        conn.close()

    agregados = {c: {'numero_vendas': 0, 'faturamento': 0.0, 'dias': 0} for c in cal.ORDEM_CLASSES}
    for r in rows:
        classe = cal.classificar_dia(date.fromisoformat(r['dia']))
        a = agregados[classe]
        a['numero_vendas'] += r['n']
        a['faturamento'] += r['total']
        a['dias'] += 1

    resultado = []
    for classe in cal.ORDEM_CLASSES:
        a = agregados[classe]
        resultado.append({
            'classe': classe,
            'dias': a['dias'],
            'numero_vendas': a['numero_vendas'],
            'faturamento': round(a['faturamento'], 2),
            'media_por_dia': round(a['faturamento'] / a['dias'], 2) if a['dias'] else 0.0,
            'ticket_medio': round(a['faturamento'] / a['numero_vendas'], 2) if a['numero_vendas'] else 0.0,
        })
    return resultado


def proximos_eventos(dias=45):
    """Próximos feriados e dias de pagamento, pra planejar a compra da
    semana sem depender de decorar datário comercial."""
    eventos = cal.proximos_eventos(dias=dias)
    return [{
        'data': e['data'], 'data_br': e['data'].strftime('%d/%m/%Y'),
        'dia_semana': NOMES_DIA_SEMANA[(e['data'].weekday() + 1) % 7],
        'tipo': e['tipo'], 'nome': e['nome'],
        'dias_restantes': (e['data'] - date.today()).days,
    } for e in eventos]


# ----------------------------------------------------------------------
# Qualidade de cadastro
# ----------------------------------------------------------------------
def qualidade_dados():
    """Pequeno raio-x do cadastro de produtos: quantos estão sem categoria,
    quais categorias fogem do padrão oficial e quantos itens não têm código
    de barras (o que obriga a busca manual no caixa)."""
    conn = db.get_conn()
    try:
        sem_categoria = conn.execute(
            """SELECT COUNT(*) n FROM produtos
               WHERE ativo = 1 AND (categoria IS NULL OR TRIM(categoria) = '')"""
        ).fetchone()['n']
        marcadores = ','.join('?' for _ in CATEGORIAS_PADRAO)
        fora_padrao = conn.execute(
            f"""SELECT categoria, COUNT(*) n FROM produtos
                WHERE ativo = 1 AND categoria IS NOT NULL AND TRIM(categoria) <> ''
                  AND categoria NOT IN ({marcadores})
                GROUP BY categoria ORDER BY n DESC""", CATEGORIAS_PADRAO).fetchall()
        sem_codigo_un = conn.execute(
            """SELECT COUNT(*) n FROM produtos
               WHERE ativo = 1 AND unidade = 'UN'
                 AND (codigo_barras IS NULL OR TRIM(codigo_barras) = '')"""
        ).fetchone()['n']
        sem_codigo_balanca = conn.execute(
            """SELECT COUNT(*) n FROM produtos
               WHERE ativo = 1 AND categoria = 'Balança'
                 AND (codigo_barras IS NULL OR TRIM(codigo_barras) = '')"""
        ).fetchone()['n']
        sem_custo = conn.execute(
            """SELECT COUNT(*) n FROM produtos
               WHERE ativo = 1 AND (preco_custo IS NULL OR preco_custo <= 0)"""
        ).fetchone()['n']
        return {
            'sem_categoria': sem_categoria,
            'categorias_fora_padrao': [dict(r) for r in fora_padrao],
            'sem_codigo_un': sem_codigo_un,
            'sem_codigo_balanca': sem_codigo_balanca,
            'sem_preco_custo': sem_custo,
        }
    finally:
        conn.close()
