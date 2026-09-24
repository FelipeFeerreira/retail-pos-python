import os
import json
import textwrap
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')

# Largura em caracteres: 80 mm normalmente cabem 42 colunas e 58 mm cabem 32.
_LARGURAS = {'80': 42, '58': 32}


def carregar_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def salvar_config(dados):
    atual = carregar_config()
    atual.update(dados)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(atual, f, ensure_ascii=False, indent=2)


def impressoras_windows():
    """Lista as impressoras instaladas no Windows (locais e de rede)."""
    try:
        import win32print
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        return [p[2] for p in win32print.EnumPrinters(flags)]
    except Exception:
        return []


def largura_papel(papel='80'):
    """Quantidade de caracteres que cabem na linha do papel."""
    return _LARGURAS.get(str(papel), 42)


def _quebrar(texto, largura):
    """Quebra o texto para caber na largura da impressora sem cortar palavras."""
    if len(texto) <= largura:
        return [texto.rstrip()]
    linhas = textwrap.wrap(texto, width=largura, break_long_words=True, drop_whitespace=False)
    return linhas if linhas else [texto[:largura]]


def _codificar(texto):
    return texto.encode('cp850', errors='replace')


# Prefixos ESC/POS por estilo de linha: (comando, fator de largura da fonte)
#   'g'  = letra grande (altura x2 + largura x2) centralizada
#   'cb' = centro + negrito
#   'c'  = centro normal
#   'b'  = negrito à esquerda
#   'd'/'n' = normal à esquerda (divisor = texto comum)
_ESTILOS = {
    'g':  (b'\x1d!\x30\x1ba\x01\x1bE\x01', 0.5),
    'cb': (b'\x1d!\x00\x1ba\x01\x1bE\x01', 1.0),
    'c':  (b'\x1d!\x00\x1ba\x01\x1bE\x00', 1.0),
    'b':  (b'\x1d!\x00\x1ba\x00\x1bE\x01', 1.0),
}
_RESET = b'\x1d!\x00\x1ba\x00\x1bE\x00'


def _montar_escpos(linhas, papel='80'):
    """Transforma as linhas do cupom em bytes ESC/POS prontos para enviar."""
    larg = largura_papel(papel)
    out = bytearray(b'\x1b@')  # inicializa a impressora
    for item in linhas:
        estilo, texto = item if isinstance(item, tuple) else ('n', str(item))
        for t in str(texto).split('\n'):
            pre, fator = _ESTILOS.get(estilo, (b'\x1d!\x00\x1ba\x00\x1bE\x00', 1.0))
            wrap = max(1, int(larg * fator))
            for pedaco in _quebrar(t, wrap):
                out += pre + _codificar(pedaco) + b'\x0a' + _RESET
    out += b'\x1bd\x04'        # avança 4 linhas (evita cortar o texto)
    out += b'\x1dVA\x00'       # corte total do papel
    return bytes(out)


def imprimir_cupom(linhas, nome_impressora=None, vias=1, papel='80'):
    """Envia o cupom (lista de tuplas (estilo, texto)) à impressora térmica
    via spooler do Windows em modo RAW/ESC-POS.

    Estilos: 'g' grande centralizado, 'cb' centro negrito, 'c' centro,
             'b' negrito à esquerda, 'n'/'d' normal.
    """
    if os.name != 'nt':
        raise RuntimeError('A impressão térmica direta está configurada para Windows.')
    try:
        import win32print
    except ImportError:
        raise RuntimeError('Instale a dependência pywin32: pip install pywin32')

    config = carregar_config()
    nome_impressora = nome_impressora or config.get('impressora')
    if not nome_impressora:
        raise RuntimeError('Nenhuma impressora térmica foi configurada.')

    dados = _montar_escpos(linhas, papel)
    vias = max(1, int(vias or 1))

    h = win32print.OpenPrinter(nome_impressora)
    try:
        job = win32print.StartDocPrinter(h, 1, ('Cupom Mercadinho', None, 'RAW'))
        for _ in range(vias):
            win32print.StartPagePrinter(h)
            win32print.WritePrinter(h, dados)
            win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
    finally:
        win32print.ClosePrinter(h)


def testar_impressao(nome_impressora=None, papel='80'):
    """Imprime uma página de teste para conferir se a impressora está OK."""
    larg = largura_papel(papel)
    hoje = datetime.now().strftime('%d/%m/%Y %H:%M')
    linhas = [
        ('g', 'MERCADINHO'),
        ('cb', 'TESTE DE IMPRESSÃO'),
        ('c', f'Papel: {papel} mm'),
        ('d', '=' * larg),
        ('b', 'SE VOCE LEU ESTAS LINHAS, A IMPRESSORA ESTA FUNCIONANDO.'),
        ('n', 'Negrito: sim'),
        ('n', 'Centralizado: sim'),
        ('n', '1 x R$ 1,00' + '.' * max(1, larg - 13) + 'R$ 1,00'),
        ('d', '=' * larg),
        ('c', hoje),
        ('c', 'Bom trabalho!'),
        ('c', 'Fim do teste'),
    ]
    imprimir_cupom(linhas, nome_impressora, papel=papel)


def imprimir_texto(texto, nome_impressora=None):
    """Envia texto simples à impressora térmica configurada (modo cru).
    Mantido por compatibilidade; prefira imprimir_cupom().
    """
    imprimir_cupom([('n', linha) for linha in str(texto).split('\n')], nome_impressora)