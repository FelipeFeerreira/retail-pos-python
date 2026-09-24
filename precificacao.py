"""
precificacao.py

Precificação por categoria, com o lucro como prioridade.

A conta é sempre a mesma: **preço = custo + uma porcentagem em cima do custo**,
e essa porcentagem depende da categoria do produto (por isso as categorias
vazias tinham que acabar primeiro — sem categoria não existe margem).

Duas porcentagens diferentes aparecem aqui, e vale não confundir:

  - **Margem sobre o custo (markup)**: o que você acrescenta em cima do que
    pagou. Pagou 10, margem de 40% -> vende a 14.
  - **Lucro sobre a venda**: quanto do que o cliente paga sobra pra você.
    No mesmo exemplo: 4 de 14 = 28,6%.

A planilha mostra as duas, e ainda mostra o que sobra depois da taxa da
maquininha — porque 30% de lucro que vira 24% no crédito muda a decisão.

O arredondamento nunca puxa o preço pra baixo: sempre sobe até a
terminação escolhida (padrão: terminar em 9, que é o padrão dos preços
que já estão no sistema).
"""
from __future__ import annotations

import math
import os
from datetime import datetime

import database as db
from categorias import CATEGORIAS
from impressora import carregar_config, salvar_config

try:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation
except ImportError:
    openpyxl = None

# Margem inicial sugerida por categoria (% em cima do custo).
# São pontos de partida pensados pra mercadinho de bairro: item de giro
# rápido e comparável (cerveja, refrigerante) segura margem menor porque o
# cliente sabe o preço; o que tem perda, trabalho ou é compra por impulso
# segura margem maior. Tudo isso é editável na aba "Margens" da planilha e
# fica salvo no config.json.
MARGENS_PADRAO = {
    'Mercearia Geral': 30.0,
    'Panificação': 40.0,
    'Doces e Biscoitos': 40.0,
    'Salgadinhos e Snacks': 45.0,
    'Bebidas': 35.0,
    'Bebidas Alcoólicas': 25.0,
    'Balança': 50.0,
    'Frios e Congelados': 32.0,
    'Prontos do Dia': 70.0,
    'Limpeza de Casa': 35.0,
    'Higiene Pessoal': 40.0,
    'Bazar e Utilidades': 60.0,
}

MARGEM_FALLBACK = 30.0

# Como arredondar o preço final. 'termina_9' deixa 7,23 virar 7,29.
ARREDONDAMENTOS = {
    'termina_9': 'Sempre terminar em 9 (ex.: 7,29 / 12,99)',
    '0.05': 'Arredondar pra cima de 5 em 5 centavos',
    '0.10': 'Arredondar pra cima de 10 em 10 centavos',
    '0.01': 'Centavo exato, sem arredondar',
}

COR_CABECALHO = '1B5240'
COR_TITULO = 'F3B22B'
COR_PREENCHER = 'FFF9C4'   # amarelo: coluna que o dono preenche
COR_CALCULADO = 'E4EFE7'   # verde claro: coluna calculada
COR_ALERTA = 'FBE8E4'


# ----------------------------------------------------------------------
# Configuração (fica no mesmo config.json da impressora/balança)
# ----------------------------------------------------------------------
def carregar_margens():
    """Margens salvas, completadas com os padrões pra categoria nova."""
    salvas = carregar_config().get('margens_categoria', {}) or {}
    margens = dict(MARGENS_PADRAO)
    for categoria, valor in salvas.items():
        try:
            margens[categoria] = float(valor)
        except (TypeError, ValueError):
            continue
    for categoria in CATEGORIAS:
        margens.setdefault(categoria, MARGEM_FALLBACK)
    return margens


def salvar_margens(margens):
    limpas = {}
    for categoria, valor in (margens or {}).items():
        try:
            limpas[categoria] = round(float(valor), 2)
        except (TypeError, ValueError):
            continue
    salvar_config({'margens_categoria': limpas})
    return limpas


def config_precificacao():
    conf = carregar_config()
    taxas = [conf.get('taxa_credito', 0) or 0, conf.get('taxa_debito', 0) or 0]
    try:
        taxa_media = round(sum(float(t) for t in taxas) / 2, 2)
    except (TypeError, ValueError):
        taxa_media = 0.0
    return {
        'arredondamento': str(conf.get('arredondamento_preco', 'termina_9')),
        'taxa_cartao': float(conf.get('taxa_cartao_referencia', taxa_media) or 0),
    }


# ----------------------------------------------------------------------
# Cálculo
# ----------------------------------------------------------------------
def arredondar_para_cima(valor, modo='termina_9'):
    """Arredonda o preço SEMPRE pra cima, conforme o modo escolhido.
    Nunca devolve menos do que o valor cheio calculado."""
    valor = max(0.0, float(valor or 0))
    if valor == 0:
        return 0.0
    if modo == 'termina_9':
        centavos = round(valor * 100)
        candidato = math.ceil(centavos / 10.0) * 10 - 1
        # Sem esse ajuste, um preço cheio de R$ 10,00 viraria R$ 9,99 —
        # arredondamento pra baixo, exatamente o que não pode acontecer.
        if candidato < centavos:
            candidato += 10
        return round(candidato / 100, 2)
    try:
        passo = float(modo)
    except (TypeError, ValueError):
        passo = 0.01
    if passo <= 0:
        return round(valor, 2)
    return round(math.ceil(round(valor / passo, 6)) * passo, 2)


def margem_da_categoria(categoria, margens=None):
    margens = margens or carregar_margens()
    return float(margens.get((categoria or '').strip(), MARGEM_FALLBACK))


def calcular_preco(custo_unitario, categoria=None, margem_pct=None, margens=None, conf=None):
    """Recebe o custo unitário e devolve o preço sugerido e os indicadores
    de lucro. Se margem_pct vier preenchida, ela manda; senão usa a margem
    da categoria."""
    conf = conf or config_precificacao()
    custo = max(0.0, float(custo_unitario or 0))
    margem = float(margem_pct) if margem_pct is not None else margem_da_categoria(categoria, margens)

    preco_cheio = round(custo * (1 + margem / 100), 4)
    preco_sugerido = arredondar_para_cima(preco_cheio, conf['arredondamento'])

    lucro_unit = round(preco_sugerido - custo, 2)
    lucro_venda_pct = round(lucro_unit / preco_sugerido * 100, 2) if preco_sugerido else 0.0
    taxa = float(conf.get('taxa_cartao', 0) or 0)
    liquido_cartao = preco_sugerido * (1 - taxa / 100)
    lucro_cartao_pct = round((liquido_cartao - custo) / preco_sugerido * 100, 2) if preco_sugerido else 0.0

    return {
        'custo': round(custo, 2),
        'margem_pct': round(margem, 2),
        'preco_cheio': round(preco_cheio, 2),
        'preco_sugerido': preco_sugerido,
        'lucro_unitario': lucro_unit,
        'lucro_venda_pct': lucro_venda_pct,
        'lucro_cartao_pct': lucro_cartao_pct,
    }


def avaliar_linha(item, margens=None, conf=None):
    """Processa uma linha de entrada de mercadoria e devolve tudo já
    calculado, inclusive o aviso de quando o preço atual do sistema está
    abaixo do custo (prejuízo) ou muito acima do sugerido."""
    conf = conf or config_precificacao()
    margens = margens or carregar_margens()

    qtd = float(item.get('quantidade') or 0)
    custo_unit = item.get('custo_unitario')
    if custo_unit in (None, ''):
        total = float(item.get('custo_total') or 0)
        custo_unit = (total / qtd) if qtd else 0.0
    custo_unit = round(float(custo_unit or 0), 4)

    calculo = calcular_preco(custo_unit, item.get('categoria'), item.get('margem_pct'), margens, conf)
    preco_final = item.get('preco_final')
    if preco_final in (None, ''):
        preco_final = calculo['preco_sugerido']
    preco_final = round(float(preco_final), 2)

    lucro_unit = round(preco_final - custo_unit, 2)
    lucro_pct = round(lucro_unit / preco_final * 100, 2) if preco_final else 0.0

    avisos = []
    if custo_unit <= 0:
        avisos.append('custo não informado')
    if preco_final and custo_unit and preco_final <= custo_unit:
        avisos.append('PREJUÍZO: preço menor ou igual ao custo')
    atual = item.get('preco_atual')
    if atual not in (None, '') and custo_unit > 0:
        atual = float(atual)
        if atual > 0 and atual <= custo_unit:
            avisos.append(f'preço atual (R$ {atual:.2f}) está abaixo do custo novo')
        elif atual > 0:
            variacao = (preco_final - atual) / atual * 100
            if abs(variacao) >= 10:
                avisos.append(f'{"aumento" if variacao > 0 else "redução"} de {abs(variacao):.0f}% no preço')

    return {
        **calculo,
        'custo_unitario': custo_unit,
        'quantidade': qtd,
        'custo_total': round(custo_unit * qtd, 2),
        'preco_final': preco_final,
        'lucro_unitario_final': lucro_unit,
        'lucro_venda_pct_final': lucro_pct,
        'lucro_total_previsto': round(lucro_unit * qtd, 2),
        'avisos': avisos,
    }


# ----------------------------------------------------------------------
# Planilha de entrada de mercadoria
# ----------------------------------------------------------------------
COLUNAS_ENTRADA = [
    ('Código de barras', 20, 'preencher'),
    ('Produto', 42, 'preencher'),
    ('Categoria', 22, 'preencher'),
    ('Unidade', 10, 'preencher'),
    ('Qtd comprada', 13, 'preencher'),
    ('Custo total pago (R$)', 18, 'preencher'),
    ('Custo unitário (R$)', 17, 'calculado'),
    ('Margem % (sobre custo)', 19, 'calculado'),
    ('Preço cheio (R$)', 15, 'calculado'),
    ('Preço sugerido (R$)', 17, 'calculado'),
    ('Preço atual no sistema', 19, 'calculado'),
    ('PREÇO QUE VOU USAR', 19, 'preencher'),
    ('Lucro por unidade (R$)', 19, 'calculado'),
    ('Lucro % sobre a venda', 19, 'calculado'),
    ('Lucro % após cartão', 18, 'calculado'),
    ('Lucro total desta compra', 21, 'calculado'),
    ('Avisos', 44, 'calculado'),
]


def _produtos_para_consulta():
    conn = db.get_conn()
    try:
        return [dict(r) for r in conn.execute(
            """SELECT codigo_barras, nome, categoria, unidade, preco_custo, preco_venda
               FROM produtos WHERE ativo = 1 ORDER BY nome""")]
    finally:
        conn.close()


def _buscar_produto(codigo=None, nome=None):
    """Acha o produto pelo código de barras ou pelo nome exato."""
    conn = db.get_conn()
    try:
        if codigo and str(codigo).strip():
            row = conn.execute('SELECT * FROM produtos WHERE codigo_barras = ? AND ativo = 1',
                               (str(codigo).strip(),)).fetchone()
            if row:
                return dict(row)
        if nome and str(nome).strip():
            row = conn.execute('SELECT * FROM produtos WHERE UPPER(TRIM(nome)) = ? AND ativo = 1',
                               (str(nome).strip().upper(),)).fetchone()
            if row:
                return dict(row)
        return None
    finally:
        conn.close()


def _estilo_cabecalho(celula):
    celula.font = Font(bold=True, color='FFFFFF', size=9)
    celula.fill = PatternFill('solid', fgColor=COR_CABECALHO)
    celula.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)


def gerar_planilha_entrada(caminho_destino, itens=None, linhas_em_branco=40):
    """Gera a planilha de entrada de mercadoria.

    Se `itens` vier preenchido (por exemplo, os produtos lidos de uma foto
    da nota), a planilha sai com tudo já calculado em número puro — pronta
    pra importar direto, sem depender de o Excel recalcular fórmula.

    Se `itens` for None, sai um modelo em branco com as fórmulas prontas,
    pra preencher à mão.

    `itens` é uma lista de dicts com: codigo_barras, nome, categoria,
    unidade, quantidade, custo_total (ou custo_unitario) e, opcionalmente,
    margem_pct e preco_final.
    """
    if openpyxl is None:
        raise RuntimeError('Este recurso precisa do pacote openpyxl. Rode: pip install openpyxl')

    margens = carregar_margens()
    conf = config_precificacao()
    wb = openpyxl.Workbook()

    # ---------------- Aba: Como usar ----------------
    ajuda = wb.active
    ajuda.title = 'Como usar'
    ajuda['A1'] = 'ENTRADA DE MERCADORIA E PRECIFICAÇÃO'
    ajuda['A1'].font = Font(size=16, bold=True, color=COR_CABECALHO)
    texto_ajuda = [
        '',
        'Pra que serve: lançar a compra que chegou e já sair com o preço de venda calculado,',
        'com a porcentagem de lucro de cada categoria aplicada em cima do custo.',
        '',
        'PASSO 1 — Confira a aba "Margens". É lá que fica a porcentagem de cada categoria.',
        '          Mudou a margem ali, a planilha toda recalcula.',
        '',
        'PASSO 2 — Na aba "Entrada", preencha as colunas AMARELAS:',
        '          código de barras (se tiver), produto, categoria, unidade, quantidade',
        '          e o custo total pago naquele item.',
        '          O custo unitário, o preço sugerido e o lucro saem automáticos.',
        '',
        'PASSO 3 — A coluna "PREÇO QUE VOU USAR" já vem com o preço sugerido.',
        '          Se quiser cobrar outro valor, é só sobrescrever essa coluna:',
        '          o lucro recalcula e a planilha avisa se ficar abaixo do custo.',
        '',
        'PASSO 4 — No sistema: Arquivo -> Importar entrada de mercadoria.',
        '          Ele atualiza custo, atualiza preço de venda e dá entrada no estoque,',
        '          mostrando antes tudo o que vai fazer, pra você confirmar.',
        '',
        'Produto que não existir ainda é cadastrado na hora da importação.',
        '',
        'A aba "Produtos (consulta)" tem tudo o que já está no sistema, com preço atual —',
        'serve pra conferir o que você está comprando e por quanto vende hoje.',
        '',
        'Duas porcentagens diferentes, pra não confundir:',
        '  - "Margem % sobre custo": o que você põe em cima do que pagou (pagou 10, +40% = 14).',
        '  - "Lucro % sobre a venda": quanto sobra do que o cliente paga (4 de 14 = 28,6%).',
        '  - "Lucro % após cartão": o mesmo lucro, já descontando a taxa da maquininha.',
    ]
    for i, linha in enumerate(texto_ajuda, start=2):
        ajuda.cell(row=i, column=1, value=linha)
    ajuda.column_dimensions['A'].width = 100

    # ---------------- Aba: Margens ----------------
    aba_m = wb.create_sheet('Margens')
    aba_m['A1'] = 'MARGEM POR CATEGORIA'
    aba_m['A1'].font = Font(size=13, bold=True, color=COR_CABECALHO)
    aba_m['A2'] = 'Mude a coluna B. É ela que a aba "Entrada" usa pra calcular o preço.'
    aba_m['A2'].font = Font(size=9, italic=True)

    for c, titulo in enumerate(['Categoria', 'Margem % sobre o custo', 'Vira que lucro na venda?',
                                'Exemplo: custo R$ 10,00 vende a'], start=1):
        _estilo_cabecalho(aba_m.cell(row=4, column=c, value=titulo))
    for i, categoria in enumerate(CATEGORIAS):
        linha = 5 + i
        aba_m.cell(row=linha, column=1, value=categoria)
        cel_margem = aba_m.cell(row=linha, column=2, value=round(margens.get(categoria, MARGEM_FALLBACK), 2))
        cel_margem.fill = PatternFill('solid', fgColor=COR_PREENCHER)
        cel_margem.number_format = '0.0"%"'
        aba_m.cell(row=linha, column=3, value=f'=IF(B{linha}=0,0,B{linha}/(100+B{linha}))').number_format = '0.0%'
        aba_m.cell(row=linha, column=4, value=f'=ROUND(10*(1+B{linha}/100),2)').number_format = 'R$ #,##0.00'
    ultima_margem = 4 + len(CATEGORIAS)

    linha_cfg = ultima_margem + 2
    aba_m.cell(row=linha_cfg, column=1, value='Taxa média da maquininha (%)').font = Font(bold=True)
    cel_taxa = aba_m.cell(row=linha_cfg, column=2, value=round(conf['taxa_cartao'], 2))
    cel_taxa.fill = PatternFill('solid', fgColor=COR_PREENCHER)
    aba_m.cell(row=linha_cfg + 1, column=1,
               value='(vem das taxas de crédito/débito configuradas no sistema)').font = Font(size=8, italic=True)
    aba_m.cell(row=linha_cfg + 3, column=1, value='Arredondamento do preço').font = Font(bold=True)
    aba_m.cell(row=linha_cfg + 3, column=2, value=ARREDONDAMENTOS.get(conf['arredondamento'], conf['arredondamento']))
    aba_m.cell(row=linha_cfg + 4, column=1,
               value='O preço nunca é arredondado pra baixo — só pra cima.').font = Font(size=8, italic=True)
    for col, largura in zip('ABCD', [26, 22, 24, 28]):
        aba_m.column_dimensions[col].width = largura

    ref_taxa = f"Margens!$B${linha_cfg}"
    ref_margens = f"Margens!$A$5:$B${ultima_margem}"

    # ---------------- Aba: Entrada ----------------
    aba_e = wb.create_sheet('Entrada')
    aba_e['A1'] = f'ENTRADA DE MERCADORIA — {datetime.now().strftime("%d/%m/%Y")}'
    aba_e['A1'].font = Font(size=13, bold=True, color=COR_CABECALHO)
    aba_e['A2'] = 'Preencha as colunas amarelas. As verdes se calculam sozinhas.'
    aba_e['A2'].font = Font(size=9, italic=True)

    linha_cab = 4
    for c, (titulo, largura, tipo) in enumerate(COLUNAS_ENTRADA, start=1):
        _estilo_cabecalho(aba_e.cell(row=linha_cab, column=c, value=titulo))
        aba_e.column_dimensions[get_column_letter(c)].width = largura
    aba_e.freeze_panes = f'A{linha_cab + 1}'
    aba_e.row_dimensions[linha_cab].height = 42

    itens = itens or []
    total_linhas = max(len(itens), 0) + linhas_em_branco
    primeira = linha_cab + 1

    for i in range(total_linhas):
        linha = primeira + i
        item = itens[i] if i < len(itens) else None

        if item:
            produto_existente = _buscar_produto(item.get('codigo_barras'), item.get('nome'))
            if produto_existente:
                item.setdefault('preco_atual', produto_existente['preco_venda'])
                item.setdefault('categoria', produto_existente['categoria'])
                item.setdefault('unidade', produto_existente['unidade'])
            resultado = avaliar_linha(item, margens, conf)

            aba_e.cell(row=linha, column=1, value=str(item.get('codigo_barras') or ''))
            aba_e.cell(row=linha, column=2, value=item.get('nome') or '')
            aba_e.cell(row=linha, column=3, value=item.get('categoria') or '')
            aba_e.cell(row=linha, column=4, value=item.get('unidade') or 'UN')
            aba_e.cell(row=linha, column=5, value=resultado['quantidade'])
            aba_e.cell(row=linha, column=6, value=resultado['custo_total'])
            aba_e.cell(row=linha, column=7, value=resultado['custo_unitario'])
            aba_e.cell(row=linha, column=8, value=resultado['margem_pct'])
            aba_e.cell(row=linha, column=9, value=resultado['preco_cheio'])
            aba_e.cell(row=linha, column=10, value=resultado['preco_sugerido'])
            aba_e.cell(row=linha, column=11, value=item.get('preco_atual') if item.get('preco_atual') is not None else '')
            aba_e.cell(row=linha, column=12, value=resultado['preco_final'])
            aba_e.cell(row=linha, column=13, value=resultado['lucro_unitario_final'])
            aba_e.cell(row=linha, column=14, value=resultado['lucro_venda_pct_final'] / 100)
            aba_e.cell(row=linha, column=15, value=resultado['lucro_cartao_pct'] / 100)
            aba_e.cell(row=linha, column=16, value=resultado['lucro_total_previsto'])
            aba_e.cell(row=linha, column=17, value='; '.join(resultado['avisos']))
            if resultado['avisos']:
                for c in range(1, 18):
                    aba_e.cell(row=linha, column=c).fill = PatternFill('solid', fgColor=COR_ALERTA)
        else:
            # Linha em branco: entra com as fórmulas prontas.
            aba_e.cell(row=linha, column=7, value=f'=IF(OR(E{linha}="",F{linha}=""),"",ROUND(F{linha}/E{linha},4))')
            aba_e.cell(row=linha, column=8, value=f'=IFERROR(VLOOKUP(C{linha},{ref_margens},2,FALSE),"")')
            aba_e.cell(row=linha, column=9, value=f'=IF(OR(G{linha}="",H{linha}=""),"",ROUND(G{linha}*(1+H{linha}/100),2))')
            aba_e.cell(row=linha, column=10, value=(
                f'=IF(I{linha}="","",'
                f'IF(MOD(ROUND(I{linha}*100,0),10)=0,ROUND(I{linha}*100,0)+9,'
                f'CEILING(ROUND(I{linha}*100,0),10)-1)/100)'))
            aba_e.cell(row=linha, column=11, value=f'=IFERROR(VLOOKUP(B{linha},\'Produtos (consulta)\'!$B:$F,5,FALSE),"")')
            aba_e.cell(row=linha, column=12, value=f'=IF(J{linha}="","",J{linha})')
            aba_e.cell(row=linha, column=13, value=f'=IF(OR(L{linha}="",G{linha}=""),"",ROUND(L{linha}-G{linha},2))')
            aba_e.cell(row=linha, column=14, value=f'=IF(OR(L{linha}="",L{linha}=0,M{linha}=""),"",M{linha}/L{linha})')
            aba_e.cell(row=linha, column=15, value=f'=IF(OR(L{linha}="",L{linha}=0,G{linha}=""),"",(L{linha}*(1-{ref_taxa}/100)-G{linha})/L{linha})')
            aba_e.cell(row=linha, column=16, value=f'=IF(OR(M{linha}="",E{linha}=""),"",ROUND(M{linha}*E{linha},2))')
            aba_e.cell(row=linha, column=17,
                       value=f'=IF(OR(L{linha}="",G{linha}=""),"",IF(L{linha}<=G{linha},"PREJUIZO: preco menor ou igual ao custo",""))')

        for c, (_t, _l, tipo) in enumerate(COLUNAS_ENTRADA, start=1):
            cel = aba_e.cell(row=linha, column=c)
            if not cel.fill or cel.fill.fgColor.rgb in (None, '00000000'):
                cel.fill = PatternFill('solid', fgColor=COR_PREENCHER if tipo == 'preencher' else COR_CALCULADO)
        for c in (6, 7, 9, 10, 11, 12, 13, 16):
            aba_e.cell(row=linha, column=c).number_format = 'R$ #,##0.00'
        aba_e.cell(row=linha, column=8).number_format = '0.0"%"'
        for c in (14, 15):
            aba_e.cell(row=linha, column=c).number_format = '0.0%'

    ultima_linha = primeira + total_linhas - 1

    dv_cat = DataValidation(type='list', formula1=f'"{",".join(CATEGORIAS)}"', allow_blank=True,
                            error='Use uma das categorias do sistema.', errorTitle='Categoria inválida')
    aba_e.add_data_validation(dv_cat)
    dv_cat.add(f'C{primeira}:C{ultima_linha}')

    dv_un = DataValidation(type='list', formula1='"UN,KG"', allow_blank=True)
    aba_e.add_data_validation(dv_un)
    dv_un.add(f'D{primeira}:D{ultima_linha}')

    linha_total = ultima_linha + 2
    aba_e.cell(row=linha_total, column=5, value='TOTAIS').font = Font(bold=True)
    cel_custo = aba_e.cell(row=linha_total, column=6, value=f'=SUM(F{primeira}:F{ultima_linha})')
    cel_custo.font = Font(bold=True)
    cel_custo.number_format = 'R$ #,##0.00'
    cel_lucro = aba_e.cell(row=linha_total, column=16, value=f'=SUM(P{primeira}:P{ultima_linha})')
    cel_lucro.font = Font(bold=True)
    cel_lucro.number_format = 'R$ #,##0.00'
    aba_e.cell(row=linha_total + 1, column=5, value='(custo total da compra e lucro previsto se vender tudo)').font = Font(size=8, italic=True)

    # ---------------- Aba: Produtos (consulta) ----------------
    aba_p = wb.create_sheet('Produtos (consulta)')
    for c, titulo in enumerate(['Código de barras', 'Produto', 'Categoria', 'Unidade',
                                'Custo no sistema', 'Preço de venda atual'], start=1):
        _estilo_cabecalho(aba_p.cell(row=1, column=c, value=titulo))
    for r, p in enumerate(_produtos_para_consulta(), start=2):
        aba_p.cell(row=r, column=1, value=p['codigo_barras'] or '')
        aba_p.cell(row=r, column=2, value=p['nome'])
        aba_p.cell(row=r, column=3, value=p['categoria'] or '')
        aba_p.cell(row=r, column=4, value=p['unidade'])
        aba_p.cell(row=r, column=5, value=p['preco_custo']).number_format = 'R$ #,##0.00'
        aba_p.cell(row=r, column=6, value=p['preco_venda']).number_format = 'R$ #,##0.00'
    aba_p.auto_filter.ref = f'A1:F{aba_p.max_row}'
    aba_p.freeze_panes = 'A2'
    for col, largura in zip('ABCDEF', [20, 44, 22, 10, 17, 19]):
        aba_p.column_dimensions[col].width = largura

    os.makedirs(os.path.dirname(os.path.abspath(caminho_destino)) or '.', exist_ok=True)
    wb.save(caminho_destino)
    return {
        'caminho': caminho_destino,
        'linhas_preenchidas': len(itens),
        'linhas_em_branco': linhas_em_branco,
        'categorias': len(CATEGORIAS),
    }


if __name__ == '__main__':
    import sys
    db.init_db()
    destino = sys.argv[1] if len(sys.argv) > 1 else f'Entrada_Mercadoria_{datetime.now().strftime("%Y-%m-%d")}.xlsx'
    r = gerar_planilha_entrada(destino)
    print(f"Planilha de entrada gerada em: {r['caminho']}")
    print(f"{r['linhas_em_branco']} linhas em branco prontas pra preencher.")
