"""Jornada real pela interface: abre a tela, pesquisa, seleciona no seletor de
lote REAL (sem substituir por mock), confirma e confere os efeitos no banco.
Banco temporário; não toca no banco operacional."""
import tempfile
import tkinter as tk
from datetime import date, timedelta
from pathlib import Path
from tkinter import ttk

import database as db
import gestao as g
import operacoes as op
import validade as val


def _filhos(w):
    for c in w.winfo_children():
        yield c
        yield from _filhos(c)


def _botao(w, texto):
    return next((b for b in _filhos(w) if isinstance(b, ttk.Button) and texto in str(b.cget('text'))), None)


def main():
    with tempfile.TemporaryDirectory() as pasta:
        db.DB_PATH = str(Path(pasta) / 'jornada.db')
        import app
        app.backup_diario = lambda *a: (None, False)
        app.registrar_fiado_recente = lambda *_: None
        app.App._iniciar_balanca = lambda self: setattr(self, 'balanca', None)
        app.App._tela_cheia = lambda self: self.geometry('1000x700+0+0')
        app.App._login_gestao = lambda self: None
        app.App._tarefas_30min = lambda self: None
        app.messagebox.askyesno = lambda *a, **k: True
        root = app.App()
        root.update()
        g.USUARIO, g.PERFIL = 'Teste', 'gerente'
        g.abrir_caixa(0)

        pid = op.criar_produto('IOGURTE JORNADA', preco_custo=3, preco_venda=6, quantidade_estoque=10)
        conn = db.get_conn()
        try:
            conn.execute('UPDATE produtos SET perecivel=1 WHERE id=?', (pid,))
            conn.commit()
        finally:
            conn.close()
        val.registrar_lote(pid, 2, (date.today() - timedelta(days=1)).isoformat())   # vencido
        val.registrar_lote(pid, 8, (date.today() + timedelta(days=10)).isoformat())
        produto = op.obter_produto(pid)

        # Jornada: adicionar item na aba Perdas e escolher o lote no seletor REAL.
        def usar_primeiro_lote():
            dlg = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
            tv = [w for w in _filhos(dlg) if isinstance(w, ttk.Treeview)][-1]
            tv.selection_set(tv.get_children()[0])   # primeiro lote = vencido (FEFO)
            _botao(dlg, 'Usar lote').invoke()

        root.after(80, usar_primeiro_lote)
        root._adicionar_perda(produto, 1)   # abre o seletor de verdade (wait_window)
        root.update()
        assert root.carrinho_perda and root.carrinho_perda[0].get('lote_id'), 'lote não foi escolhido no seletor real'

        root._confirmar_perda()
        root.update()

        assert op.obter_produto(pid)['quantidade_estoque'] == 9, 'estoque não baixou'
        perda = g.consultar('SELECT id,valor_total FROM perdas ORDER BY id DESC LIMIT 1')[0]
        assert perda['valor_total'] == 3.0, 'custo histórico da perda errado'
        rastreio = g.consultar("SELECT lote_id FROM baixas_lotes WHERE origem='Perda' AND referencia=?", (str(perda['id']),))
        assert rastreio, 'lote perdido não ficou rastreado'
        venc_lote = g.consultar('SELECT data_validade FROM lotes_validade WHERE id=?', (rastreio[0]['lote_id'],))[0]
        assert venc_lote['data_validade'] < date.today().isoformat(), 'deveria ter baixado o lote vencido'
        # Histórico exibe a perda.
        assert root.tree_hist_perda.get_children(), 'histórico de perdas vazio'

        root.destroy()
        print('OK: jornada real de perda com seletor de lote e efeitos conferidos no banco.')


if __name__ == '__main__':
    main()
