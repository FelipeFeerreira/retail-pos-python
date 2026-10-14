"""Janela principal da interface reformulada: navegação por áreas e roteamento
de páginas. Cada área é uma página funcional que reutiliza os serviços."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from . import tema
from . import paginas as pg

# Ordem do menu principal.
AREAS = [
    ('Início', pg.InicioPage),
    ('Vendas', pg.VendasPage),
    ('Produtos e estoque', pg.ProdutosPage),
    ('Compras', pg.ComprasPage),
    ('Operacional', pg.OperacionalPage),
    ('Financeiro', pg.FinanceiroPage),
    ('Resultados', pg.ResultadosPage),
    ('Diagnóstico', pg.DiagnosticoPage),
    ('Administração', pg.AdministracaoPage),
]


class Shell(tk.Tk):
    def __init__(self):
        super().__init__(className='Mercadinho')
        C = tema.cores()
        self.withdraw()
        self.title('Mercadinho — sistema reformulado')
        self.minsize(1100, 680)
        self.geometry('1280x800')
        self.configure(bg=C['papel'])
        self._paginas = {}
        self._atual = None
        self._construir()

    def iniciar(self):
        """Mostra a janela e abre o Início (chamado após o login)."""
        self.deiconify()
        self.ir_para('Início')

    def _construir(self):
        C = tema.cores()
        F = tema.fonte()
        # Barra superior
        topo = tk.Frame(self, bg=C['verde2'], height=52)
        topo.pack(fill='x')
        topo.pack_propagate(False)
        tk.Label(topo, text='🧺 Mercadinho', bg=C['verde2'], fg='white', font=(F, 15, 'bold')).pack(side='left', padx=18)
        self.status = tk.Label(topo, text='Pronto', bg=C['verde2'], fg='#B8D0C2', font=(F, 9))
        self.status.pack(side='right', padx=18)
        tk.Frame(self, bg=C['amarelo'], height=3).pack(fill='x')

        corpo = tk.Frame(self, bg=C['papel'])
        corpo.pack(fill='both', expand=True)
        # Menu lateral
        nav = tk.Frame(corpo, bg=C['branco'], width=190)
        nav.pack(side='left', fill='y')
        nav.pack_propagate(False)
        self._botoes = {}
        for nome, _ in AREAS:
            b = tk.Button(nav, text=nome, anchor='w', relief='flat', bd=0, padx=14, pady=9,
                          bg=C['branco'], fg=C['verde2'], activebackground=C['verdeclaro'],
                          font=(F, 10), command=lambda n=nome: self.ir_para(n))
            b.pack(fill='x')
            self._botoes[nome] = b
        tk.Frame(corpo, bg=C['linha'], width=1).pack(side='left', fill='y')
        self.area = tk.Frame(corpo, bg=C['papel'])
        self.area.pack(side='left', fill='both', expand=True, padx=14, pady=14)

    def ir_para(self, nome):
        if self._atual == nome:
            return
        C = tema.cores()
        for n, b in self._botoes.items():
            b.config(bg=C['verdeclaro'] if n == nome else C['branco'], fg=C['verde2'])
        # Esconde a página atual (mantém o estado do formulário) e mostra a nova.
        if self._atual and self._atual in self._paginas:
            self._paginas[self._atual].pack_forget()
        pagina = self._paginas.get(nome)
        if pagina is None:
            classe = dict(AREAS)[nome]
            pagina = classe(self.area, self)
            self._paginas[nome] = pagina
        pagina.pack(fill='both', expand=True)
        pagina.recarregar()
        self._atual = nome

    def notificar(self, texto):
        self.status.config(text=texto)
        self.after(6000, lambda: self.status.config(text='Pronto'))

    def atualizar_inicio(self):
        ini = self._paginas.get('Início')
        if ini:
            try:
                ini.recarregar()
            except Exception:
                pass
