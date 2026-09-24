from __future__ import annotations

import sqlite3
import database as db


class ErroCliente(Exception):
    pass


def listar_clientes(busca=""):
    conn = db.get_conn()
    try:
        if busca:
            like = f"%{busca}%"
            rows = conn.execute(
                "SELECT * FROM clientes WHERE ativo = 1 AND (nome LIKE ? OR telefone LIKE ?) ORDER BY nome",
                (like, like),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM clientes WHERE ativo = 1 ORDER BY nome").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def obter_cliente(cliente_id):
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM clientes WHERE id = ? AND ativo = 1", (cliente_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def criar_cliente(nome, telefone="", observacao="", documento_tipo="", documento="", endereco=""):
    import gestao as _gestao
    _gestao.permitir('venda')
    nome = (nome or "").strip()
    if not nome:
        raise ErroCliente("Informe o nome do cliente.")
    conn = db.get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO clientes (nome, telefone, documento_tipo, documento, endereco, observacao) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                nome, (telefone or "").strip(), (documento_tipo or "").strip(),
                (documento or "").strip(), (endereco or "").strip(), (observacao or "").strip(),
            ),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError as exc:
        raise ErroCliente(str(exc))
    finally:
        conn.close()


def atualizar_cliente(cliente_id, nome, telefone="", observacao="", documento_tipo="", documento="", endereco=""):
    import gestao as _gestao
    _gestao.permitir('venda')
    nome = (nome or "").strip()
    if not nome:
        raise ErroCliente("Informe o nome do cliente.")
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE clientes SET nome = ?, telefone = ?, documento_tipo = ?, documento = ?, "
            "endereco = ?, observacao = ? WHERE id = ?",
            (
                nome, (telefone or "").strip(), (documento_tipo or "").strip(),
                (documento or "").strip(), (endereco or "").strip(), (observacao or "").strip(), cliente_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def desativar_cliente(cliente_id):
    import gestao as _gestao
    _gestao.permitir('credito')
    conn = db.get_conn()
    try:
        conn.execute("UPDATE clientes SET ativo = 0 WHERE id = ?", (cliente_id,))
        conn.commit()
    finally:
        conn.close()


def registrar_pagamento(cliente_id, valor, observacao='', forma_pagamento='Dinheiro'):
    import operacoes
    return operacoes.registrar_pagamento_fiado(cliente_id,valor,observacao,forma_pagamento)


def saldo_fiado(cliente_id):
    import operacoes
    return operacoes.saldo_fiado(cliente_id)


def listar_dividas():
    clientes = listar_clientes()
    for c in clientes:
        c["saldo_fiado"] = saldo_fiado(c["id"])
    return [c for c in clientes if c["saldo_fiado"] > 0]


def historico_fiado(cliente_id):
    conn = db.get_conn()
    try:
        vendas = conn.execute(
            "SELECT id, data_hora, valor_total, desconto FROM vendas WHERE cliente_id = ? AND forma_pagamento = 'fiado' ORDER BY data_hora DESC",
            (cliente_id,),
        ).fetchall()
        pagamentos = conn.execute(
            "SELECT id, data_hora, valor, forma_pagamento, observacao FROM pagamentos_fiado WHERE cliente_id = ? ORDER BY data_hora DESC",
            (cliente_id,),
        ).fetchall()
        return {"vendas": [dict(r) for r in vendas], "pagamentos": [dict(r) for r in pagamentos], "saldo": saldo_fiado(cliente_id)}
    finally:
        conn.close()
