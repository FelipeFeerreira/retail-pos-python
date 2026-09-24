"""
importar_planilha.py

Importa produtos de uma planilha Excel (no formato usado pelo sistema antigo,
com uma aba por categoria) para o banco de dados do mercadinho.

É seguro rodar de novo no futuro: produtos que já existem (mesmo código de
barras, ou mesmo nome+categoria para itens de balança) são ATUALIZADOS
(nome, categoria, unidade, preço de venda) sem apagar o estoque nem o preço
de custo que você já tiver preenchido no sistema. Produtos novos são
cadastrados com estoque 0, para você contar e lançar de verdade.

Uso:
    python importar_planilha.py caminho/da/planilha.xlsx
"""
import sys
from pathlib import Path

try:
    import openpyxl
except ImportError:
    print("Este script precisa do pacote openpyxl. Rode: pip install openpyxl")
    sys.exit(1)

import database as db

# Descrições que são placeholders genéricos da balança no sistema antigo,
# não produtos de verdade — não são importadas.
DESCRICOES_IGNORADAS = {"PROD. SEM CODIGO", "DIVERSOS BALANCA"}


def limpar_codigo(valor):
    if valor is None:
        return None
    texto = str(valor).strip()
    if texto in ("", "nan", "0", "#NAME?"):
        return None
    return texto


def achar_coluna(cabecalho, padroes):
    for i, titulo in enumerate(cabecalho):
        t = titulo.upper()
        if any(p in t for p in padroes):
            return i
    return None


def importar(caminho_planilha):
    import gestao as _gestao
    _gestao.permitir('estoque')
    wb = openpyxl.load_workbook(caminho_planilha, data_only=True)
    conn = db.get_conn()

    inseridos = 0
    atualizados = 0
    ignorados = []
    avisos_codigo_repetido = []

    for nome_aba in wb.sheetnames:
        ws = wb[nome_aba]
        eh_balanca = nome_aba.strip().upper() == "BALANÇA"
        categoria = "Balança" if eh_balanca else nome_aba.strip()

        primeira_linha = next(ws.iter_rows(min_row=1, max_row=1))
        cabecalho = [str(c.value).strip() if c.value else "" for c in primeira_linha]

        col_desc = achar_coluna(cabecalho, ["DESCRIÇÃO", "DESCRICAO", "PRODUTO", "NOME"])
        col_preco = achar_coluna(cabecalho, ["PREÇO", "PRECO", "VALOR"])
        col_unidade = achar_coluna(cabecalho, ["UNIDADE"])
        col_codigo = None if eh_balanca else achar_coluna(cabecalho, ["EAN", "BARRAS", "CÓDIGO", "CODIGO"])

        if col_desc is None or col_preco is None:
            ignorados.append((categoria, "(aba inteira)", "não encontrei as colunas de descrição/preço nessa aba"))
            continue

        for linha in ws.iter_rows(min_row=2, values_only=True):
            if linha is None or all(v is None for v in linha):
                continue
            descricao = str(linha[col_desc] or "").strip()
            if not descricao:
                continue
            if descricao.upper() in DESCRICOES_IGNORADAS:
                ignorados.append((categoria, descricao, "item genérico/placeholder da balança, sem preço real"))
                continue

            preco_bruto = linha[col_preco]
            try:
                preco = round(float(preco_bruto), 2)
            except (TypeError, ValueError):
                ignorados.append((categoria, descricao, f"preço inválido ({preco_bruto!r})"))
                continue

            unidade = "KG" if eh_balanca else "UN"
            if col_unidade is not None:
                valor_unidade = str(linha[col_unidade] or "").strip().upper()
                if valor_unidade in ("UN", "KG"):
                    unidade = valor_unidade

            codigo_barras = limpar_codigo(linha[col_codigo]) if col_codigo is not None else None

            existente = None
            if codigo_barras:
                existente = conn.execute(
                    "SELECT id FROM produtos WHERE codigo_barras = ?", (codigo_barras,)
                ).fetchone()
                if existente:
                    avisos_codigo_repetido.append((categoria, descricao, codigo_barras))
            else:
                existente = conn.execute(
                    "SELECT id FROM produtos WHERE nome = ? AND categoria = ?", (descricao, categoria)
                ).fetchone()

            if existente:
                conn.execute(
                    """UPDATE produtos SET nome = ?, categoria = ?, unidade = ?, preco_venda = ?,
                       codigo_barras = COALESCE(?, codigo_barras)
                       WHERE id = ?""",
                    (descricao, categoria, unidade, preco, codigo_barras, existente["id"]),
                )
                atualizados += 1
            else:
                conn.execute(
                    """INSERT INTO produtos
                       (codigo_barras, nome, categoria, unidade, preco_custo, preco_venda, quantidade_estoque, estoque_minimo)
                       VALUES (?, ?, ?, ?, 0, ?, 0, ?)""",
                    (codigo_barras, descricao, categoria, unidade, preco, 2 if unidade == "KG" else 5),
                )
                inseridos += 1

    conn.commit()
    conn.close()

    return {
        "inseridos": inseridos,
        "atualizados": atualizados,
        "ignorados": [{"categoria": c, "produto": d, "motivo": m} for c, d, m in ignorados],
        "codigos_repetidos": [{"categoria": c, "produto": d, "codigo": cod} for c, d, cod in avisos_codigo_repetido],
    }


def importar_e_imprimir(caminho_planilha):
    resultado = importar(caminho_planilha)
    print(f"Produtos novos cadastrados: {resultado['inseridos']}")
    print(f"Produtos já existentes, atualizados: {resultado['atualizados']}")
    print(f"Linhas ignoradas: {len(resultado['ignorados'])}")
    for item in resultado['ignorados']:
        print(f"  - [{item['categoria']}] {item['produto']}: {item['motivo']}")
    if resultado['codigos_repetidos']:
        print(f"\nCódigo de barras repetido na planilha ({len(resultado['codigos_repetidos'])}x) — ficou valendo a última ocorrência:")
        for item in resultado['codigos_repetidos']:
            print(f"  - [{item['categoria']}] {item['produto']} ({item['codigo']})")
    return resultado


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python importar_planilha.py caminho/da/planilha.xlsx")
        sys.exit(1)
    caminho = sys.argv[1]
    if not Path(caminho).exists():
        print(f"Arquivo não encontrado: {caminho}")
        sys.exit(1)
    db.init_db()
    importar_e_imprimir(caminho)
    print("\nImportação concluída! Preço de custo e estoque continuam 0 para os produtos novos — é só preencher aos poucos.")
