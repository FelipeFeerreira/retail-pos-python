"""
cascos.py

Controle de casco (garrafa retornável) emprestado pro cliente — mesmo
espírito do fiado em dinheiro, só que contando cascos em vez de reais.

Convenção do sinal (igual ao saldo_fiado): positivo = cliente deve (pegou
casco emprestado e ainda não devolveu); negativo = cliente tem crédito
(devolveu ou deixou casco a mais); zero = em dia.

O tipo de casco é texto livre (padrão "Coca") pra dar pra separar por
tamanho/marca se um dia precisar (ex.: "Coca 2L", "Coca 600ml", "Skol"),
sem obrigar a escolher isso logo de cara.
"""
from __future__ import annotations

import database as db


class ErroCasco(Exception):
    pass


TIPOS_PADRAO = ['Coca', 'Coca 600ml', 'Coca 2L', 'Coca 1L', 'Outro']


def saldo_casco(cliente_id, tipo_casco=None):
    """Saldo de casco do cliente. Se tipo_casco vier None, soma todos os tipos."""
    conn = db.get_conn()
    try:
        if tipo_casco:
            r = conn.execute(
                'SELECT COALESCE(SUM(quantidade), 0) t FROM movimentos_casco WHERE cliente_id = ? AND tipo_casco = ?',
                (cliente_id, tipo_casco)).fetchone()
        else:
            r = conn.execute(
                'SELECT COALESCE(SUM(quantidade), 0) t FROM movimentos_casco WHERE cliente_id = ?',
                (cliente_id,)).fetchone()
        return int(r['t'])
    finally:
        conn.close()


def saldos_por_tipo(cliente_id):
    """Saldo detalhado por tipo de casco (só os tipos com saldo diferente de zero)."""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            '''SELECT tipo_casco, COALESCE(SUM(quantidade), 0) saldo
               FROM movimentos_casco WHERE cliente_id = ?
               GROUP BY tipo_casco HAVING saldo <> 0
               ORDER BY tipo_casco''', (cliente_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def registrar_movimento(cliente_id, tipo_casco, quantidade, direcao, observacao=''):
    """direcao: 'pegou' (cliente levou casco emprestado, aumenta a dívida) ou
    'devolveu' (cliente devolveu ou deixou casco a mais, diminui a dívida ou
    vira crédito). quantidade é sempre um número positivo aqui — o sinal
    real é decidido pela direção."""
    import gestao as _gestao
    _gestao.permitir('venda')
    quantidade = int(quantidade)
    if quantidade <= 0:
        raise ErroCasco('Informe uma quantidade de casco maior que zero.')
    if direcao not in ('pegou', 'devolveu'):
        raise ErroCasco('Direção inválida.')
    tipo_casco = (tipo_casco or 'Coca').strip() or 'Coca'
    valor = quantidade if direcao == 'pegou' else -quantidade
    conn = db.get_conn()
    try:
        cli = conn.execute('SELECT id FROM clientes WHERE id = ? AND ativo = 1', (cliente_id,)).fetchone()
        if not cli:
            raise ErroCasco('Cliente não encontrado.')
        conn.execute(
            'INSERT INTO movimentos_casco (cliente_id, tipo_casco, quantidade, observacao) VALUES (?, ?, ?, ?)',
            (cliente_id, tipo_casco, valor, observacao or ''))
        conn.commit()
    finally:
        conn.close()


def historico_casco(cliente_id, tipo_casco=None):
    """Histórico de movimentos do cliente, mais recente primeiro."""
    conn = db.get_conn()
    try:
        if tipo_casco:
            rows = conn.execute(
                '''SELECT id, tipo_casco, quantidade, data_hora, observacao
                   FROM movimentos_casco WHERE cliente_id = ? AND tipo_casco = ?
                   ORDER BY data_hora DESC''', (cliente_id, tipo_casco)).fetchall()
        else:
            rows = conn.execute(
                '''SELECT id, tipo_casco, quantidade, data_hora, observacao
                   FROM movimentos_casco WHERE cliente_id = ?
                   ORDER BY data_hora DESC''', (cliente_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def listar_clientes_com_casco():
    """Clientes ativos que têm saldo de casco diferente de zero (deve ou tem
    crédito), com o total (todos os tipos somados) e o detalhamento por tipo."""
    conn = db.get_conn()
    try:
        clientes = conn.execute(
            '''SELECT DISTINCT c.id, c.nome FROM clientes c
               JOIN movimentos_casco m ON m.cliente_id = c.id
               WHERE c.ativo = 1 ORDER BY c.nome''').fetchall()
    finally:
        conn.close()
    resultado = []
    for c in clientes:
        total = saldo_casco(c['id'])
        if total == 0:
            detalhado = saldos_por_tipo(c['id'])
            if not detalhado:
                continue
        resultado.append({'id': c['id'], 'nome': c['nome'], 'saldo_total': total, 'por_tipo': saldos_por_tipo(c['id'])})
    return resultado


def texto_saldo(saldo):
    if saldo > 0:
        return f'Deve {saldo} casco(s)'
    if saldo < 0:
        return f'Crédito de {abs(saldo)} casco(s)'
    return 'Em dia'
