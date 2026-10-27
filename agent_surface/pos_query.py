#!/usr/bin/env python3
"""pos_query — consultas somente-leitura no banco do PDV (mercadinho.db).

Objetivo: dar a um agente (ou a você no terminal) uma superfície estável,
em JSON, sem risco de escrita. Todas as conexões usam mode=ro.

Uso:
    python3 pos_query.py estoque-baixo [--limite 20]
    python3 pos_query.py fiado [--limite 20]
    python3 pos_query.py validade [--dias 7]
    python3 pos_query.py resumo-hoje
    python3 pos_query.py schema

O caminho do banco vem de --db, depois da variável POS_DB, depois do
mercadinho.db ao lado deste arquivo.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta

AQUI = os.path.dirname(os.path.abspath(__file__))


def caminho_banco(explicito: str | None) -> str:
    caminho = explicito or os.environ.get("POS_DB") or os.path.join(AQUI, "mercadinho.db")
    if not os.path.exists(caminho):
        raise SystemExit(f"banco não encontrado: {caminho}")
    return caminho


def conectar(caminho: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def estoque_baixo(conn: sqlite3.Connection, limite: int) -> list[dict]:
    sql = """
        SELECT id, nome, categoria, unidade,
               ROUND(quantidade_estoque, 3) AS quantidade,
               ROUND(estoque_minimo, 3) AS minimo,
               ROUND(estoque_minimo - quantidade_estoque, 3) AS falta
        FROM produtos
        WHERE ativo = 1
          AND quantidade_estoque <= estoque_minimo
        ORDER BY falta DESC, nome
        LIMIT ?
    """
    return [dict(r) for r in conn.execute(sql, (limite,))]


def fiado(conn: sqlite3.Connection, limite: int) -> list[dict]:
    """Saldo de fiado por cliente: compras a prazo menos pagamentos não estornados."""
    sql = """
        WITH compras AS (
            SELECT cliente_id, SUM(valor_total) AS total
            FROM vendas
            WHERE forma_pagamento = 'fiado'
              AND COALESCE(cancelada, 0) = 0
              AND cliente_id IS NOT NULL
            GROUP BY cliente_id
        ), pagos AS (
            SELECT cliente_id, SUM(valor) AS total
            FROM pagamentos_fiado
            WHERE COALESCE(estornado, 0) = 0
            GROUP BY cliente_id
        )
        SELECT c.id, c.nome,
               ROUND(COALESCE(compras.total, 0), 2) AS comprado,
               ROUND(COALESCE(pagos.total, 0), 2) AS pago,
               ROUND(COALESCE(compras.total, 0) - COALESCE(pagos.total, 0), 2) AS saldo,
               c.limite_credito,
               c.telefone
        FROM clientes c
        LEFT JOIN compras ON compras.cliente_id = c.id
        LEFT JOIN pagos   ON pagos.cliente_id = c.id
        WHERE COALESCE(compras.total, 0) - COALESCE(pagos.total, 0) > 0.004
        ORDER BY saldo DESC
        LIMIT ?
    """
    linhas = []
    for r in conn.execute(sql, (limite,)):
        item = dict(r)
        limite_credito = item.pop("limite_credito", None)
        if limite_credito:
            item["acima_do_limite"] = item["saldo"] > limite_credito
            item["limite_credito"] = limite_credito
        linhas.append(item)
    return linhas


def validade(conn: sqlite3.Connection, dias: int) -> list[dict]:
    limite = (date.today() + timedelta(days=dias)).isoformat()
    sql = """
        SELECT l.id, p.nome, ROUND(l.quantidade, 3) AS quantidade,
               l.data_validade,
               CAST(julianday(l.data_validade) - julianday('now') AS INTEGER) AS dias_restantes
        FROM lotes_validade l
        JOIN produtos p ON p.id = l.produto_id
        WHERE l.quantidade > 0
          AND date(l.data_validade) <= date(?)
        ORDER BY l.data_validade
    """
    return [dict(r) for r in conn.execute(sql, (limite,))]


def resumo_hoje(conn: sqlite3.Connection) -> dict:
    hoje = date.today().isoformat()
    sql = """
        SELECT COUNT(*) AS vendas,
               ROUND(COALESCE(SUM(valor_total), 0), 2) AS total,
               ROUND(COALESCE(SUM(CASE WHEN forma_pagamento = 'fiado' THEN valor_total END), 0), 2) AS fiado
        FROM vendas
        WHERE date(data_hora) = date(?)
          AND COALESCE(cancelada, 0) = 0
    """
    linha = conn.execute(sql, (hoje,)).fetchone()
    dados = dict(linha)
    dados["data"] = hoje
    dados["gerado_em"] = datetime.now().isoformat(timespec="seconds")
    return dados


def schema(conn: sqlite3.Connection) -> dict:
    tabelas = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )]
    return {"tabelas": tabelas, "total": len(tabelas)}


COMANDOS = {
    "estoque-baixo": ("Produtos no ou abaixo do estoque mínimo", estoque_baixo),
    "fiado": ("Clientes com saldo de fiado em aberto", fiado),
    "validade": ("Lotes vencendo no prazo informado", validade),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consultas somente-leitura no PDV")
    parser.add_argument("--db", help="caminho do mercadinho.db")
    parser.add_argument("comando", choices=[*COMANDOS, "resumo-hoje", "schema"])
    parser.add_argument("--limite", type=int, default=20)
    parser.add_argument("--dias", type=int, default=7)
    args = parser.parse_args(argv)

    conn = conectar(caminho_banco(args.db))
    try:
        if args.comando in COMANDOS:
            dados = COMANDOS[args.comando][1](conn, args.limite if args.comando != "validade" else args.dias)
        elif args.comando == "resumo-hoje":
            dados = resumo_hoje(conn)
        else:
            dados = schema(conn)
    finally:
        conn.close()

    json.dump({"comando": args.comando, "dados": dados}, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
