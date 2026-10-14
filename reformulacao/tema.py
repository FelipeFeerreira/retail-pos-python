"""Paleta e fontes compartilhadas. Reaproveita a paleta do app atual para a
nova interface ficar visualmente consistente, respeitando o tema salvo."""
from __future__ import annotations


def cores():
    import app
    return app.COR


def fonte():
    import app
    return app.FONTE


def moeda(valor):
    from decimal import Decimal, ROUND_HALF_UP
    try:
        valor = Decimal(str(valor or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except Exception:
        valor = Decimal('0')
    return f'R$ {valor:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def formatq(valor, unidade='UN'):
    try:
        v = float(valor or 0)
    except (TypeError, ValueError):
        v = 0.0
    texto = f'{v:.3f}'.rstrip('0').rstrip('.') or '0'
    return f'{texto} {"kg" if unidade == "KG" else "un"}'
