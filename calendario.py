"""
calendario.py

Calendário do mercadinho: feriados e dias de pagamento.

A ideia é classificar cada dia de venda em algo que ajude a decidir compra e
escala de atendimento — e não em "data comemorativa". O que realmente muda o
movimento de um mercadinho de bairro é:

  - o dia da semana (domingo de manhã não é terça à tarde);
  - feriado e véspera de feriado (o cliente estoca antes e some no dia);
  - dia de pagamento (5º dia útil, dia 15, fim do mês) — quando o bairro
    tem dinheiro no bolso.

Os feriados móveis (Carnaval, Sexta-feira Santa, Corpus Christi) são
calculados a partir da Páscoa, sem depender de internet nem de tabela fixa
que vence todo ano.

Feriados municipais variam de cidade pra cidade: dá pra acrescentar os de
Salto (ou de onde o mercadinho estiver) no config.json, na chave
"feriados_municipais", como uma lista de datas "AAAA-MM-DD" ou "--MM-DD"
(o "--" serve pra data que repete todo ano). Exemplo:

    "feriados_municipais": ["--08-15", "2026-09-21"]
"""
from __future__ import annotations

from datetime import date, timedelta

from impressora import carregar_config

# Dias do mês em que o bairro normalmente recebe. É só o padrão inicial —
# pode ser trocado no config.json na chave "dias_pagamento".
DIAS_PAGAMENTO_PADRAO = [5, 15, 20, 30]

CLASSE_FERIADO = 'Feriado'
CLASSE_VESPERA = 'Véspera de feriado'
CLASSE_PAGAMENTO = 'Dia de pagamento'
CLASSE_FIM_SEMANA = 'Fim de semana'
CLASSE_NORMAL = 'Dia normal'

ORDEM_CLASSES = [CLASSE_FERIADO, CLASSE_VESPERA, CLASSE_PAGAMENTO, CLASSE_FIM_SEMANA, CLASSE_NORMAL]


def _pascoa(ano: int) -> date:
    """Domingo de Páscoa pelo algoritmo de Meeus/Jones/Butcher."""
    a = ano % 19
    b = ano // 100
    c = ano % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


def feriados_nacionais(ano: int) -> dict:
    """Feriados nacionais (e o estadual de SP) do ano, como {data: nome}.

    Inclui o Dia da Consciência Negra (20/11), que passou a ser feriado
    nacional a partir de 2024, e o 9 de julho de São Paulo. Carnaval e
    Corpus Christi são ponto facultativo por lei, mas na prática o
    comércio de bairro sente os dois como feriado — então entram aqui.
    """
    pascoa = _pascoa(ano)
    itens = {
        date(ano, 1, 1): 'Confraternização Universal',
        pascoa - timedelta(days=48): 'Carnaval (segunda)',
        pascoa - timedelta(days=47): 'Carnaval (terça)',
        pascoa - timedelta(days=2): 'Sexta-feira Santa',
        pascoa: 'Páscoa',
        date(ano, 4, 21): 'Tiradentes',
        date(ano, 5, 1): 'Dia do Trabalho',
        pascoa + timedelta(days=60): 'Corpus Christi',
        date(ano, 7, 9): 'Revolução Constitucionalista (SP)',
        date(ano, 9, 7): 'Independência do Brasil',
        date(ano, 10, 12): 'Nossa Senhora Aparecida',
        date(ano, 11, 2): 'Finados',
        date(ano, 11, 15): 'Proclamação da República',
        date(ano, 12, 25): 'Natal',
    }
    if ano >= 2024:
        itens[date(ano, 11, 20)] = 'Consciência Negra'
    return itens


def feriados_municipais(ano: int) -> dict:
    """Lê do config.json os feriados locais que o dono cadastrar."""
    bruto = carregar_config().get('feriados_municipais', []) or []
    itens = {}
    for entrada in bruto:
        texto = str(entrada).strip()
        try:
            if texto.startswith('--'):
                mes, dia = texto[2:].split('-')
                itens[date(ano, int(mes), int(dia))] = 'Feriado municipal'
            else:
                d = date.fromisoformat(texto)
                if d.year == ano:
                    itens[d] = 'Feriado municipal'
        except (ValueError, TypeError):
            continue
    return itens


def feriados_do_ano(ano: int) -> dict:
    itens = feriados_nacionais(ano)
    itens.update(feriados_municipais(ano))
    return itens


def nome_feriado(dia: date):
    """Nome do feriado naquele dia, ou None se for dia comum."""
    return feriados_do_ano(dia.year).get(dia)


def eh_feriado(dia: date) -> bool:
    return nome_feriado(dia) is not None


def eh_vespera_de_feriado(dia: date) -> bool:
    return eh_feriado(dia + timedelta(days=1)) and not eh_feriado(dia)


def dias_pagamento_configurados():
    conf = carregar_config().get('dias_pagamento')
    if isinstance(conf, list) and conf:
        try:
            return sorted({int(d) for d in conf if 1 <= int(d) <= 31})
        except (TypeError, ValueError):
            pass
    return list(DIAS_PAGAMENTO_PADRAO)


def quinto_dia_util(ano: int, mes: int) -> date:
    """5º dia útil do mês — a data clássica de pagamento de salário.
    Considera sábado, domingo e feriado como dia não útil."""
    uteis = 0
    dia = date(ano, mes, 1)
    while True:
        if dia.weekday() < 5 and not eh_feriado(dia):
            uteis += 1
            if uteis == 5:
                return dia
        dia += timedelta(days=1)


def ultimo_dia_mes(ano: int, mes: int) -> date:
    if mes == 12:
        return date(ano, 12, 31)
    return date(ano, mes + 1, 1) - timedelta(days=1)


def eh_dia_pagamento(dia: date) -> bool:
    """Dia em que o bairro normalmente está com dinheiro: um dos dias
    configurados, o 5º dia útil, ou o último dia do mês quando o dia
    configurado (ex.: 30) não existe naquele mês (fevereiro)."""
    configurados = dias_pagamento_configurados()
    if dia.day in configurados:
        return True
    if dia == quinto_dia_util(dia.year, dia.month):
        return True
    fim = ultimo_dia_mes(dia.year, dia.month)
    if dia == fim and any(d > fim.day for d in configurados):
        return True
    return False


def classificar_dia(dia: date) -> str:
    """Classifica o dia numa das categorias que interessam pro movimento.
    A ordem importa: feriado ganha de véspera, que ganha de dia de
    pagamento, que ganha de fim de semana."""
    if eh_feriado(dia):
        return CLASSE_FERIADO
    if eh_vespera_de_feriado(dia):
        return CLASSE_VESPERA
    if eh_dia_pagamento(dia):
        return CLASSE_PAGAMENTO
    if dia.weekday() >= 5:
        return CLASSE_FIM_SEMANA
    return CLASSE_NORMAL


def proximos_eventos(a_partir_de=None, dias=45):
    """Lista os feriados e dias de pagamento que vêm aí, pra ajudar a
    programar a compra da semana. Devolve [{'data','tipo','nome'}]."""
    inicio = a_partir_de or date.today()
    eventos = []
    for i in range(dias + 1):
        dia = inicio + timedelta(days=i)
        nome = nome_feriado(dia)
        if nome:
            eventos.append({'data': dia, 'tipo': CLASSE_FERIADO, 'nome': nome})
        elif eh_dia_pagamento(dia):
            rotulo = 'Dia de pagamento'
            if dia == quinto_dia_util(dia.year, dia.month):
                rotulo = '5º dia útil (pagamento)'
            eventos.append({'data': dia, 'tipo': CLASSE_PAGAMENTO, 'nome': rotulo})
    return eventos
