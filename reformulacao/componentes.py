"""Widgets reutilizáveis da nova interface (Tkinter/ttk).

Padronizam o que o operador vê em todas as telas: período, busca com seleção
explícita, cartões, tabelas e campos. Nenhuma regra de negócio aqui.
"""
from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk

from . import tema


def _cores():
    return tema.cores()


def _fonte():
    return tema.fonte()


def rotulo_produto(p):
    codigo = (p.get('codigo_barras') or p.get('sku') or '') if p else ''
    extra = f' · {codigo}' if codigo else ''
    un = p.get('unidade', 'UN') if p else 'UN'
    return f"{p['nome']} ({un}){extra}" if p else ''


class Periodo(tk.Frame):
    """Seletor de período com presets e datas personalizadas. `intervalo()`
    devolve (inicio, fim) em AAAA-MM-DD."""

    PRESETS = [('Hoje', 'hoje'), ('7 dias', '7dias'), ('30 dias', '30dias'),
               ('Este mês', 'mes'), ('Tudo', 'tudo')]

    def __init__(self, master, comando=None, padrao='mes'):
        C = _cores()
        super().__init__(master, bg=C['papel'])
        self.comando = comando
        self.var = tk.StringVar(value=padrao)
        self.inicio = tk.StringVar(value=date.today().replace(day=1).isoformat())
        self.fim = tk.StringVar(value=date.today().isoformat())
        for texto, valor in self.PRESETS:
            ttk.Radiobutton(self, text=texto, value=valor, variable=self.var,
                            command=self._mudou).pack(side='left', padx=3)
        tk.Label(self, text='de', bg=C['papel'], fg=C['cinza'], font=(_fonte(), 8)).pack(side='left', padx=(12, 2))
        tk.Entry(self, textvariable=self.inicio, width=11, font=(_fonte(), 9)).pack(side='left')
        tk.Label(self, text='até', bg=C['papel'], fg=C['cinza'], font=(_fonte(), 8)).pack(side='left', padx=(4, 2))
        tk.Entry(self, textvariable=self.fim, width=11, font=(_fonte(), 9)).pack(side='left')
        ttk.Button(self, text='Aplicar', style='Secondary.TButton', command=self._aplicar).pack(side='left', padx=6)

    def _mudou(self):
        if self.var.get() == 'tudo':
            self.inicio.set(''); self.fim.set('')
        if self.comando:
            self.comando()

    def _aplicar(self):
        self.var.set('personalizado')
        if self.comando:
            self.comando()

    def intervalo(self):
        hoje = date.today()
        chave = self.var.get()
        if chave == 'hoje':
            return hoje.isoformat(), hoje.isoformat()
        if chave == '7dias':
            return (hoje - timedelta(days=6)).isoformat(), hoje.isoformat()
        if chave == '30dias':
            return (hoje - timedelta(days=29)).isoformat(), hoje.isoformat()
        if chave == 'mes':
            return hoje.replace(day=1).isoformat(), hoje.isoformat()
        if chave == 'tudo':
            return None, None
        ini = self.inicio.get().strip() or None
        fim = self.fim.get().strip() or None
        return ini, fim

    def rotulo(self):
        ini, fim = self.intervalo()
        if not ini and not fim:
            return 'Todo o período'
        if ini == fim:
            return ini
        return f'{ini or "início"} a {fim or "hoje"}'


class Card(tk.Frame):
    """Cartão com título e valor grande."""

    def __init__(self, master, titulo, valor='—', destaque=False, nota=''):
        C = _cores()
        bg = C['verde2'] if destaque else C['branco']
        fg = 'white' if destaque else C['verde2']
        super().__init__(master, bg=bg, highlightbackground=C['linha'], highlightthickness=(0 if destaque else 1))
        tk.Label(self, text=titulo.upper(), bg=bg, fg=(fg if destaque else C['cinza']),
                 font=(_fonte(), 8, 'bold')).pack(anchor='w', padx=12, pady=(10, 2))
        self.lbl = tk.Label(self, text=valor, bg=bg, fg=fg, font=('Consolas', 16, 'bold'))
        self.lbl.pack(anchor='w', padx=12)
        self.nota = tk.Label(self, text=nota, bg=bg, fg=(fg if destaque else C['cinza']), font=(_fonte(), 8))
        self.nota.pack(anchor='w', padx=12, pady=(0, 10))

    def definir(self, valor, nota=None):
        self.lbl.config(text=valor)
        if nota is not None:
            self.nota.config(text=nota)


class BuscaProduto(tk.Frame):
    """Busca com SELEÇÃO EXPLÍCITA: nunca escolhe o primeiro resultado sozinho.
    Ao editar o texto, a seleção é invalidada até nova escolha."""

    def __init__(self, master, ao_selecionar=None, largura=42):
        C = _cores()
        super().__init__(master, bg=C['branco'])
        self.ao_selecionar = ao_selecionar
        self.produto = None
        self.ent = tk.Entry(self, font=(_fonte(), 11), relief='solid', bd=1, width=largura)
        self.ent.pack(fill='x', ipady=4)
        self.ent.bind('<KeyRelease>', self._buscar)
        self.lista = tk.Listbox(self, height=6, font=(_fonte(), 9), activestyle='none')
        self.lista.bind('<<ListboxSelect>>', self._escolher)
        self.lista.bind('<Double-1>', self._escolher)
        self.lista.bind('<Return>', self._escolher)
        self._achados = []
        self._deb = None

    def _buscar(self, event=None):
        import operacoes as op
        # Qualquer edição invalida a seleção anterior.
        if self.produto and self.ent.get().strip() != rotulo_produto(self.produto):
            self.produto = None
        termo = self.ent.get().strip()
        self.lista.delete(0, 'end')
        if len(termo) < 2:
            self.lista.pack_forget()
            return
        achados = op.listar_produtos(termo)[:10]
        if not achados:
            self.lista.pack_forget()
            return
        for p in achados:
            self.lista.insert('end', rotulo_produto(p))
        self._achados = achados
        self.lista.pack(fill='x', pady=(2, 0))

    def _escolher(self, event=None):
        sel = self.lista.curselection()
        if not sel:
            return
        p = self._achados[sel[0]]
        self.produto = p
        self.ent.delete(0, 'end')
        self.ent.insert(0, rotulo_produto(p))
        self.lista.pack_forget()
        if self.ao_selecionar:
            self.ao_selecionar(p)

    def limpar(self):
        self.produto = None
        self.ent.delete(0, 'end')
        self.lista.delete(0, 'end')
        self.lista.pack_forget()


def tabela(master, colunas, altura=12):
    """Cria uma Treeview com cabeçalhos. colunas = [(chave, titulo, largura, anchor)]."""
    C = _cores()
    tv = ttk.Treeview(master, columns=[c[0] for c in colunas], show='headings', height=altura)
    for chave, titulo, largura, anchor in colunas:
        tv.heading(chave, text=titulo)
        tv.column(chave, width=largura, anchor=anchor)
    tv.tag_configure('par', background=C['branco'])
    tv.tag_configure('impar', background=C['zebra'])
    tv.tag_configure('alerta', background=C['amareloclaro'], foreground=C['ambar'])
    tv.tag_configure('ruim', background=C['vermelhoclaro'], foreground=C['vermelho'])
    return tv


def campo(master, rotulo, valor='', largura=None):
    """Rótulo + Entry empilhados. Devolve o Entry."""
    C = _cores()
    tk.Label(master, text=rotulo, bg=C['branco'], fg=C['cinza'], font=(_fonte(), 8, 'bold')).pack(anchor='w', pady=(8, 2))
    e = tk.Entry(master, font=(_fonte(), 10), relief='solid', bd=1)
    if largura:
        e.config(width=largura)
    e.pack(fill='x', ipady=4)
    if valor != '':
        e.insert(0, str(valor))
    return e


def combo(master, rotulo, valores, padrao=None):
    C = _cores()
    tk.Label(master, text=rotulo, bg=C['branco'], fg=C['cinza'], font=(_fonte(), 8, 'bold')).pack(anchor='w', pady=(8, 2))
    var = tk.StringVar(value=padrao if padrao is not None else (valores[0] if valores else ''))
    cb = ttk.Combobox(master, textvariable=var, values=valores, state='readonly', font=(_fonte(), 10))
    cb.pack(fill='x')
    return var


def parse_float(texto, padrao=0.0):
    try:
        return float(str(texto).replace(',', '.').strip())
    except (TypeError, ValueError):
        return padrao
