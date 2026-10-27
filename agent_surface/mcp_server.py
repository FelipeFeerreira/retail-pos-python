#!/usr/bin/env python3
"""mcp_server — expõe o PDV como ferramentas para agentes (MCP, stdio).

Requer o SDK do MCP 2.x (a API antiga FastMCP virou MCPServer):
    pip install "mcp>=2,<3"
Rodar:
    python3 mcp_server.py            (stdio)
    mcp dev mcp_server.py            (inspector)

Todas as ferramentas são somente-leitura e reutilizam pos_query.py, para que
a regra de negócio (saldo de fiado, estoque mínimo, validade) viva em um só
lugar.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from mcp.server.mcpserver import MCPServer

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(AQUI, "pos_query.py")

mcp = MCPServer("mercadinho-pos")


def _consultar(comando: str, *extra: str) -> dict:
    banco = os.environ.get("POS_DB", "")
    args = [sys.executable, SCRIPT]
    if banco:
        args += ["--db", banco]
    args += [comando, *extra]
    saida = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if saida.returncode != 0:
        return {"erro": saida.stderr.strip() or "falha ao consultar"}
    return json.loads(saida.stdout)["dados"]


@mcp.tool()
def estoque_baixo(limite: int = 20) -> dict:
    """Produtos ativos no ou abaixo do estoque mínimo, do mais crítico ao menos."""
    return {"itens": _consultar("estoque-baixo", "--limite", str(limite))}


@mcp.tool()
def fiado_em_aberto(limite: int = 20) -> dict:
    """Clientes com saldo de fiado em aberto, maior saldo primeiro."""
    return {"clientes": _consultar("fiado", "--limite", str(limite))}


@mcp.tool()
def validade_proxima(dias: int = 7) -> dict:
    """Lotes com quantidade em estoque vencendo em até N dias (inclui vencidos)."""
    return {"lotes": _consultar("validade", "--dias", str(dias))}


@mcp.tool()
def resumo_do_dia() -> dict:
    """Total vendido hoje, quantidade de vendas e quanto foi a prazo."""
    return _consultar("resumo-hoje")


if __name__ == "__main__":
    mcp.run()
