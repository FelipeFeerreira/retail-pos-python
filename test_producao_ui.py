"""Teste de GUI (Tkinter) da seleção de produto/insumo na tela de receita.

Reproduz o defeito: escolher um insumo e depois editar o texto de forma que a
busca não encontre mais nada não pode conservar o ID antigo (salvaria o insumo
errado). Usa banco temporário e não toca em periféricos.
"""
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import database as db
import gestao as g
import operacoes as op


def _filhos(widget):
    for c in widget.winfo_children():
        yield c
        yield from _filhos(c)


def _entries(widget):
    return [w for w in _filhos(widget) if isinstance(w, tk.Entry)]


def _listboxes(widget):
    return [w for w in _filhos(widget) if isinstance(w, tk.Listbox)]


def _botao(widget, texto):
    return next((w for w in _filhos(widget)
                 if isinstance(w, ttk.Button) and texto in str(w.cget('text'))), None)


def main():
    with tempfile.TemporaryDirectory() as pasta:
        db.DB_PATH = str(Path(pasta) / 'ui.db')
        import app
        app.backup_diario = lambda *a: (None, False)
        app.registrar_fiado_recente = lambda *_: None
        app.App._iniciar_balanca = lambda self: setattr(self, 'balanca', None)
        app.App._tela_cheia = lambda self: self.geometry('1000x700+0+0')
        app.App._login_gestao = lambda self: None
        app.App._tarefas_30min = lambda self: None

        erros = []
        app.messagebox.showerror = lambda *a, **k: erros.append(a[0] if a else '')
        root = app.App()
        root.update()
        g.USUARIO, g.PERFIL = 'Teste', 'gerente'

        op.criar_produto('PAO FRANCES', preco_custo=1, preco_venda=10, quantidade_estoque=0)
        op.criar_produto('PAO DE QUEIJO', preco_custo=1, preco_venda=10, quantidade_estoque=0)
        op.criar_produto('FARINHA DE TRIGO', preco_custo=1, preco_venda=2, quantidade_estoque=50)
        op.criar_produto('FARINHA DE MILHO', preco_custo=1, preco_venda=2, quantidade_estoque=50)

        root._modal_nova_receita()
        root.update()
        dlg = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
        dlg.focus_force(); root.update()

        ents = _entries(dlg)
        lbs = _listboxes(dlg)
        ent_produto, ent_rendimento, ent_insumo, ent_qtd = ents[0], ents[1], ents[2], ents[3]
        lb_produto, lb_insumo = lbs[0], lbs[1]

        def digitar(entry, texto):
            entry.focus_set()
            entry.delete(0, 'end')
            entry.insert(0, texto)
            entry.event_generate('<KeyRelease>', when='now')
            root.update()

        def selecionar(listbox):
            listbox.selection_set(0)
            listbox.event_generate('<<ListboxSelect>>', when='now')
            root.update()

        # Produto final: escolhe uma sugestão e depois edita o texto.
        digitar(ent_produto, 'PAO')
        assert lb_produto.size() >= 2, 'sugestões do produto final não apareceram'
        selecionar(lb_produto)
        escolhido = ent_produto.get()
        digitar(ent_produto, 'PAO ZZZ INEXISTENTE')
        # Insumo: escolhe, depois edita o texto para algo sem correspondência.
        digitar(ent_insumo, 'FARINHA')
        assert lb_insumo.size() >= 2, 'sugestões do insumo não apareceram'
        selecionar(lb_insumo)
        digitar(ent_insumo, 'FARINHA')  # deixa de ser exatamente o nome escolhido
        ent_rendimento.delete(0, 'end'); ent_rendimento.insert(0, '10')
        ent_qtd.delete(0, 'end'); ent_qtd.insert(0, '5')

        erros.clear()
        _botao(dlg, 'Salvar receita').invoke()
        root.update()

        # Nada deve ter sido gravado: o produto final e o insumo foram invalidados.
        receitas = g.consultar('SELECT COUNT(*) n FROM receitas')[0]['n']
        assert receitas == 0, f'receita foi gravada indevidamente (escolhido={escolhido!r})'
        assert erros, 'esperava um erro avisando que a seleção é inválida'

        dlg.destroy(); root.destroy()
        print('OK: edição de texto invalida a seleção e não grava insumo/produto errado.')


if __name__ == '__main__':
    main()
