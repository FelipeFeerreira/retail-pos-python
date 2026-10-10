"""
importar_planilha.py

Importa produtos de uma planilha Excel (no formato usado pelo sistema antigo,
com uma aba por categoria) para o banco de dados do mercadinho.

É seguro rodar de novo no futuro: produtos que já existem (mesmo código de
barras, ou mesmo nome+categoria para itens de balança) são ATUALIZADOS
(nome, categoria, unidade, preço de venda) sem apagar o estoque nem o preço
de custo que você já tiver preenchido no sistema. Produtos novos são
cadastrados com estoque 0, para você contar e lançar de verdade.

Duas etapas, sempre: nada é gravado sem passar pela pré-visualização.

    pre_visualizar(caminho)   -> só lê e monta o que SERIA feito
    aplicar(caminho, plano)   -> faz backup e grava numa única transação

Uso:
    python importar_planilha.py caminho/da/planilha.xlsx
"""
import os
import sqlite3
import sys
from datetime import datetime
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


def _backup_antes_de_gravar():
    """Backup consistente (API do SQLite) antes de qualquer gravação."""
    pasta = os.path.join(os.path.dirname(os.path.abspath(db.DB_PATH)), 'backups')
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, f'mercadinho_antes_planilha_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db')
    origem = sqlite3.connect(db.DB_PATH)
    copia = sqlite3.connect(destino)
    try:
        origem.backup(copia)
        if copia.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Backup não íntegro antes da importação da planilha.')
    finally:
        origem.close()
        copia.close()
    return destino


def _montar_plano(caminho_planilha):
    """Lê a planilha e monta o plano, SEM gravar nada. Cada item já vem com
    a ação (cadastrar/atualizar), o produto existente e os avisos."""
    wb = openpyxl.load_workbook(caminho_planilha, data_only=True)
    conn = db.get_conn()
    itens, ignorados = [], []
    try:
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
                ignorados.append({"categoria": categoria, "produto": "(aba inteira)",
                                  "motivo": "não encontrei as colunas de descrição/preço nessa aba"})
                continue

            for linha in ws.iter_rows(min_row=2, values_only=True):
                if linha is None or all(v is None for v in linha):
                    continue
                descricao = str(linha[col_desc] or "").strip()
                if not descricao:
                    continue
                if descricao.upper() in DESCRICOES_IGNORADAS:
                    ignorados.append({"categoria": categoria, "produto": descricao,
                                      "motivo": "item genérico/placeholder da balança, sem preço real"})
                    continue

                preco_bruto = linha[col_preco]
                try:
                    preco = round(float(preco_bruto), 2)
                except (TypeError, ValueError):
                    ignorados.append({"categoria": categoria, "produto": descricao,
                                      "motivo": f"preço inválido ({preco_bruto!r})"})
                    continue
                if preco < 0:
                    ignorados.append({"categoria": categoria, "produto": descricao,
                                      "motivo": f"preço negativo ({preco:.2f})"})
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
                        "SELECT id FROM produtos WHERE codigo_barras = ?", (codigo_barras,)).fetchone()
                else:
                    existente = conn.execute(
                        "SELECT id FROM produtos WHERE nome = ? AND categoria = ?",
                        (descricao, categoria)).fetchone()

                avisos = []
                if preco == 0:
                    avisos.append('preço zero — confira depois')
                itens.append({
                    'categoria': categoria, 'descricao': descricao, 'preco': preco,
                    'unidade': unidade, 'codigo_barras': codigo_barras,
                    'acao': 'atualizar' if existente else 'cadastrar',
                    'produto_id': existente['id'] if existente else None,
                    'avisos': avisos,
                })
    finally:
        conn.close()
    return {
        'itens': itens,
        'ignorados': ignorados,
        'inseridos_previstos': sum(1 for i in itens if i['acao'] == 'cadastrar'),
        'atualizados_previstos': sum(1 for i in itens if i['acao'] == 'atualizar'),
    }


def pre_visualizar(caminho_planilha):
    """Monta o plano de importação para conferir antes de gravar."""
    import gestao as _gestao
    _gestao.permitir('estoque')
    return _montar_plano(caminho_planilha)


def aplicar(caminho_planilha, plano=None):
    """Grava o plano numa única transação (tudo ou nada). Faz backup antes."""
    import gestao as _gestao
    _gestao.permitir('estoque')
    plano = plano or _montar_plano(caminho_planilha)
    backup = _backup_antes_de_gravar()

    inseridos = atualizados = 0
    conn = db.get_conn()
    try:
        conn.execute('BEGIN IMMEDIATE')
        for item in plano['itens']:
            if item['acao'] == 'atualizar':
                conn.execute(
                    """UPDATE produtos SET nome = ?, categoria = ?, unidade = ?, preco_venda = ?,
                       codigo_barras = COALESCE(?, codigo_barras) WHERE id = ?""",
                    (item['descricao'], item['categoria'], item['unidade'], item['preco'],
                     item['codigo_barras'], item['produto_id']))
                atualizados += 1
            else:
                conn.execute(
                    """INSERT INTO produtos
                       (codigo_barras, nome, categoria, unidade, preco_custo, preco_venda, quantidade_estoque, estoque_minimo)
                       VALUES (?, ?, ?, ?, 0, ?, 0, ?)""",
                    (item['codigo_barras'], item['descricao'], item['categoria'], item['unidade'],
                     item['preco'], 2 if item['unidade'] == 'KG' else 5))
                inseridos += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        'backup': backup,
        'inseridos': inseridos,
        'atualizados': atualizados,
        'ignorados': plano['ignorados'],
        'codigos_repetidos': [],
    }


def importar(caminho_planilha):
    """Compatibilidade: pré-visualiza e aplica numa chamada só."""
    plano = _montar_plano(caminho_planilha)
    return aplicar(caminho_planilha, plano)


def importar_e_imprimir(caminho_planilha):
    resultado = importar(caminho_planilha)
    print(f"Produtos novos cadastrados: {resultado['inseridos']}")
    print(f"Produtos já existentes, atualizados: {resultado['atualizados']}")
    print(f"Linhas ignoradas: {len(resultado['ignorados'])}")
    for item in resultado['ignorados']:
        print(f"  - [{item['categoria']}] {item['produto']}: {item['motivo']}")
    print(f"\nBackup do banco em: {resultado['backup']}")
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
