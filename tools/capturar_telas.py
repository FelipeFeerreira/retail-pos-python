"""Captura as telas da interface reformulada com DADOS FICTÍCIOS.

Usa `mss` (captura X11 direto, sem scrot/import). Cria um banco temporário com
dados sintéticos, abre cada página e salva PNGs em docs/capturas/.

Uso: .venv/bin/python tools/capturar_telas.py

OBS.: no ambiente de desenvolvimento atual o framebuffer X é UNIFORME (tela
virtual/XWayland sem compositor), então as imagens saem em branco. O script
fica pronto para uso quando houver uma sessão gráfica real; nenhuma captura
foi aprovada visualmente até então.
"""
import os
import tempfile
import time
from pathlib import Path

# banco temporário antes de qualquer import que leia o banco
_tmp = tempfile.TemporaryDirectory()
import database as db
db.DB_PATH = str(Path(_tmp.name) / 'capturas.db')

import gestao as g
import operacoes as op
import producao as prod
from datetime import date, timedelta

SAIDA = Path(__file__).resolve().parent.parent / 'docs' / 'capturas'


def _dados():
    g.USUARIO, g.PERFIL = 'Gerente Demo', 'gerente'
    db.init_db()
    g.abrir_caixa(200)
    g.salvar_politica(None, 500, 30, 1, 1)
    pao = op.criar_produto('PAO FRANCES', preco_custo=6, preco_venda=12, quantidade_estoque=40)
    leite = op.criar_produto('LEITE 1L', preco_custo=4, preco_venda=7, quantidade_estoque=60)
    farinha = op.criar_produto('FARINHA DE TRIGO', preco_custo=5, preco_venda=8, quantidade_estoque=100)
    cli = op.criar_cliente('MARIA DA SILVA', telefone='(11) 99999-0000')
    op.registrar_venda([{'produto_id': pao, 'quantidade': 10}], 'dinheiro')
    op.registrar_venda([{'produto_id': leite, 'quantidade': 5}], 'pix')
    op.registrar_venda([{'produto_id': leite, 'quantidade': 2}], 'fiado', cliente_id=cli)
    op.registrar_consumo_interno([{'produto_id': leite, 'quantidade': 1}], 'Limpeza', finalidade='operacional')
    op.registrar_perda([{'produto_id': farinha, 'quantidade': 2}], 'Quebra/avaria')
    rid = prod.criar_receita(pao, rendimento=10, itens=[{'insumo_id': farinha, 'quantidade': 5}])
    g.registrar_producao(rid, 1, validade=(date.today() + timedelta(days=5)).isoformat())
    g.criar_conta_pagar('Imobiliária', 'Aluguel', 1200, (date.today() + timedelta(days=5)).isoformat(),
                        categoria='Aluguel', competencia=date.today().isoformat())


def main():
    _dados()
    from reformulacao.shell import Shell, AREAS
    root = Shell()
    root.iniciar()
    root.geometry('1366x768+20+20')
    root.update(); root.lift(); root.focus_force()
    try:
        root.attributes('-topmost', True)
    except Exception:
        pass
    root.update(); time.sleep(0.6)

    try:
        import mss
    except ImportError:
        print('mss indisponível; sem captura.')
        return
    SAIDA.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        for nome, _ in AREAS:
            root.ir_para(nome); root.update(); time.sleep(0.4)
            x, y = root.winfo_rootx(), root.winfo_rooty()
            w, h = root.winfo_width(), root.winfo_height()
            img = sct.grab({'left': x, 'top': y, 'width': w, 'height': h})
            arquivo = SAIDA / (nome.lower().replace(' ', '_').replace('í', 'i').replace('ó', 'o') + '.png')
            mss.tools.to_png(img.rgb, img.size, output=str(arquivo))
            print('captura:', arquivo)
    root.destroy()
    _tmp.cleanup()


if __name__ == '__main__':
    main()
