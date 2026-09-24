"""
validade.py

Controle de validade por lote: o mesmo produto pode ter partes do estoque
vencendo em datas diferentes (ex.: 2 unidades pro dia 5, mais 3 pro dia 7
de uma entrega diferente). Cada "lote" é uma linha com quantidade + data de
validade; `produtos.quantidade_estoque` continua sendo o total oficial.

Uso típico: toda vez que entra mercadoria com validade, registra um lote
(além do ajuste de estoque normal). Nas vendas/consumo/produção, o sistema
tenta baixar primeiro dos lotes que vencem mais cedo (FEFO — first expire,
first out), sem travar a operação principal se algo não bater exatamente
(produto sem lote cadastrado, por exemplo).
"""
from __future__ import annotations

from datetime import date, timedelta

import database as db
import gestao as g


class ErroValidade(Exception):
    pass


def registrar_lote(produto_id, quantidade, data_validade=None, observacao=''):
    """Registra um novo lote de validade pro produto. Não mexe no estoque
    total — isso é feito separadamente por ajustar_estoque/entrada de
    mercadoria; esse lote é só o detalhamento de validade."""
    g.permitir('estoque')
    quantidade = g.quantidade(quantidade)
    if quantidade <= 0:
        raise ErroValidade('Informe uma quantidade maior que zero.')
    if data_validade:
        try:
            date.fromisoformat(data_validade)
        except ValueError:
            raise ErroValidade('Data de validade inválida (use AAAA-MM-DD).')
    conn = db.get_conn()
    try:
        conn.execute('BEGIN IMMEDIATE')
        p = conn.execute('SELECT * FROM produtos WHERE id = ?', (produto_id,)).fetchone()
        if not p:
            raise ErroValidade('Produto não encontrado.')
        if p['perecivel'] and not data_validade: raise ErroValidade('Informe a validade do perecível.')
        existente=conn.execute('SELECT COALESCE(SUM(quantidade),0) FROM lotes_validade WHERE produto_id=?',(produto_id,)).fetchone()[0]
        if existente+quantidade>p['quantidade_estoque']+.001:
            raise ErroValidade('Os lotes não podem exceder o estoque total. Para nova compra use Receber mercadoria.')
        cur = conn.execute(
            'INSERT INTO lotes_validade (produto_id, quantidade, data_validade, observacao) VALUES (?, ?, ?, ?)',
            (produto_id, quantidade, data_validade, observacao or ''))
        g.auditar(conn,'cadastrar','lote',cur.lastrowid,{'produto':produto_id,'quantidade':quantidade,'validade':data_validade})
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def lotes_produto(produto_id, incluir_sem_validade=True):
    """Lotes em aberto de um produto, do vencimento mais próximo pro mais
    distante. Lotes sem data de validade (None) vão por último."""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            '''SELECT id, quantidade, data_validade, data_entrada, observacao
               FROM lotes_validade WHERE produto_id = ? AND quantidade > 0
               ORDER BY (data_validade IS NULL), data_validade''', (produto_id,)).fetchall()
        lotes = [dict(r) for r in rows]
        if not incluir_sem_validade:
            lotes = [l for l in lotes if l['data_validade']]
        return lotes
    finally:
        conn.close()


def editar_lote(lote_id, quantidade=None, data_validade=None, observacao=None):
    g.permitir('estoque')
    conn = db.get_conn()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM lotes_validade WHERE id = ?', (lote_id,)).fetchone()
        if not row:
            raise ErroValidade('Lote não encontrado.')
        nova_qtd = round(float(quantidade), 3) if quantidade is not None else row['quantidade']
        nova_data = data_validade if data_validade is not None else row['data_validade']
        nova_obs = observacao if observacao is not None else row['observacao']
        if nova_qtd < 0:
            raise ErroValidade('Quantidade não pode ser negativa.')
        if nova_data: g.data_iso(nova_data)
        p=conn.execute('SELECT * FROM produtos WHERE id=?',(row['produto_id'],)).fetchone()
        if p['perecivel'] and not nova_data: raise ErroValidade('Informe a validade do perecível.')
        outros=conn.execute('SELECT COALESCE(SUM(quantidade),0) FROM lotes_validade WHERE produto_id=? AND id!=?',(row['produto_id'],lote_id)).fetchone()[0]
        if outros+nova_qtd>p['quantidade_estoque']+.001: raise ErroValidade('Lotes excedem o estoque do produto.')
        conn.execute('UPDATE lotes_validade SET quantidade = ?, data_validade = ?, observacao = ? WHERE id = ?',
                     (nova_qtd, nova_data, nova_obs, lote_id))
        g.auditar(conn,'editar','lote',lote_id,{'antes':dict(row),'quantidade':nova_qtd,'validade':nova_data})
        conn.commit()
    finally:
        conn.close()


def excluir_lote(lote_id):
    g.permitir('estoque')
    with g.transacao() as conn:
        lote=conn.execute('SELECT * FROM lotes_validade WHERE id=?',(lote_id,)).fetchone()
        if not lote: raise ErroValidade('Lote não encontrado.')
        if lote['quantidade']>0: raise ErroValidade('Lote com saldo não pode ser apagado. Registre perda, inventário ou corrija a distribuição dos lotes.')
        # Preservar referência das baixas e estornos; lotes zerados já ficam ocultos.
        g.auditar(conn,'arquivar','lote',lote_id)


def baixar_fefo(produto_id, quantidade):
    """Desconta 'quantidade' dos lotes do produto, começando pelo que vence
    mais cedo (FEFO). Não reclama se não tiver lote suficiente (ou nenhum) —
    esse controle é um detalhamento opcional, nunca deve travar uma venda,
    consumo ou produção por falta de lote cadastrado."""
    quantidade = round(float(quantidade or 0), 3)
    if quantidade <= 0:
        return
    conn = db.get_conn()
    try:
        lotes = conn.execute(
            '''SELECT id, quantidade FROM lotes_validade WHERE produto_id = ? AND quantidade > 0
               ORDER BY (data_validade IS NULL), data_validade''', (produto_id,)).fetchall()
        restante = quantidade
        for lote in lotes:
            if restante <= 0:
                break
            usar = min(restante, lote['quantidade'])
            nova = round(lote['quantidade'] - usar, 3)
            conn.execute('UPDATE lotes_validade SET quantidade = ? WHERE id = ?', (nova, lote['id']))
            restante = round(restante - usar, 3)
        conn.commit()
    except Exception:
        # Best-effort: se algo der errado aqui, a operação principal (venda,
        # consumo, produção) não pode ser afetada.
        conn.rollback()
    finally:
        conn.close()


def produtos_vencendo(dias=7):
    """Lotes que vencem dentro de N dias (ou já vencidos), com dados do
    produto, ordenados do mais urgente pro menos urgente."""
    limite = (date.today() + timedelta(days=dias)).isoformat()
    conn = db.get_conn()
    try:
        rows = conn.execute(
            '''SELECT l.id lote_id, l.quantidade, l.data_validade, p.id produto_id, p.nome, p.unidade
               FROM lotes_validade l JOIN produtos p ON p.id = l.produto_id
               WHERE l.quantidade > 0 AND l.data_validade IS NOT NULL AND l.data_validade <= ? AND p.ativo = 1
               ORDER BY l.data_validade''', (limite,)).fetchall()
        resultado = []
        hoje = date.today()
        for r in rows:
            d = dict(r)
            venc = date.fromisoformat(d['data_validade'])
            d['dias_restantes'] = (venc - hoje).days
            d['vencido'] = d['dias_restantes'] < 0
            resultado.append(d)
        return resultado
    finally:
        conn.close()


def todos_lotes_com_produto():
    """Todos os lotes em aberto, com nome do produto — pra tela de gestão
    geral de validades."""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            '''SELECT l.id lote_id, l.quantidade, l.data_validade, l.data_entrada, l.observacao,
                      p.id produto_id, p.nome, p.unidade
               FROM lotes_validade l JOIN produtos p ON p.id = l.produto_id
               WHERE l.quantidade > 0 AND p.ativo = 1
               ORDER BY (l.data_validade IS NULL), l.data_validade, p.nome''').fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
