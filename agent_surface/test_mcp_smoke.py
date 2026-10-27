#!/usr/bin/env python3
"""Teste de fumaça do servidor MCP: sobe via stdio, lista ferramentas e chama uma.

Uso:
    python3 test_mcp_smoke.py
Requer POS_DB apontando para o mercadinho.db (ou o padrão do pos_query.py).
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

AQUI = os.path.dirname(os.path.abspath(__file__))


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=[os.path.join(AQUI, "mcp_server.py")],
        env={**os.environ, "POS_DB": os.environ.get("POS_DB", "")},
    )
    async with stdio_client(params) as (leitura, escrita):
        async with ClientSession(leitura, escrita) as sessao:
            await sessao.initialize()
            ferramentas = await sessao.list_tools()
            nomes = [f.name for f in ferramentas.tools]
            print("ferramentas:", nomes)

            resultado = await sessao.call_tool("resumo_do_dia", {})
            texto = resultado.content[0].text
            dados = json.loads(texto)
            print("resumo_do_dia:", json.dumps(dados, ensure_ascii=False))

            esperadas = {"estoque_baixo", "fiado_em_aberto", "validade_proxima", "resumo_do_dia"}
            faltando = esperadas - set(nomes)
            if faltando:
                print("FALTANDO:", sorted(faltando))
                return 1
            print("OK: 4 ferramentas expostas e uma chamada bem-sucedida")
            return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
