"""Ponto de entrada da interface REFORMULADA do Retail POS.

Esta é a entrada principal documentada da nova interface (navegação por áreas:
Início, Vendas, Produtos e estoque, Compras, Operacional, Financeiro,
Resultados, Diagnóstico, Administração).

- Usa o MESMO banco e os MESMOS serviços (gestao/operacoes/producao/analises).
- Exige autenticação (tabela `usuarios`); o primeiro acesso cadastra o gerente.
- Trava de instância única (não roda junto com outra cópia no mesmo banco).

A interface antiga (app.py) continua disponível durante a transição, mas NÃO
deve rodar ao mesmo tempo sobre o mesmo banco (a trava impede).
"""
from __future__ import annotations

import os

os.environ.setdefault('XMODIFIERS', '@im=none')  # evita lentidão do XIM/IBus no Tk

import tkinter as tk
from tkinter import messagebox, ttk

import database as db
import gestao as g
from applock import TravaInstancia, InstanciaJaAberta


def _login(parent):
    """Autentica o operador. Devolve True se autenticou."""
    if not g.tem_usuarios():
        return _primeiro_acesso(parent)
    dlg = tk.Toplevel(parent)
    dlg.title('Entrar no sistema')
    dlg.geometry('380x260')
    dlg.transient(parent)
    dlg.grab_set()
    tk.Label(dlg, text='Entrar no sistema', font=('Segoe UI', 14, 'bold')).pack(anchor='w', padx=22, pady=(18, 8))
    users = [r['nome'] for r in g.consultar('SELECT nome FROM usuarios WHERE ativo=1 ORDER BY nome')]
    tk.Label(dlg, text='Usuário', font=('Segoe UI', 8, 'bold')).pack(anchor='w', padx=22)
    var_u = tk.StringVar(value=users[0] if users else '')
    ttk.Combobox(dlg, textvariable=var_u, values=users, state='readonly').pack(fill='x', padx=22)
    tk.Label(dlg, text='Senha', font=('Segoe UI', 8, 'bold')).pack(anchor='w', padx=22, pady=(10, 0))
    ent_s = tk.Entry(dlg, show='*'); ent_s.pack(fill='x', padx=22)
    ent_s.focus_set()
    ok = {'v': False}

    def entrar(_=None):
        if g.autenticar(var_u.get(), ent_s.get()):
            ok['v'] = True; dlg.destroy()
        else:
            messagebox.showerror('Login', 'Usuário ou senha inválidos.', parent=dlg)
    ent_s.bind('<Return>', entrar)
    b = tk.Frame(dlg); b.pack(fill='x', padx=22, pady=16)
    ttk.Button(b, text='Entrar', style='Primary.TButton', command=entrar).pack(side='right')
    ttk.Button(b, text='Sair', command=lambda: (dlg.destroy(), parent.destroy())).pack(side='right', padx=6)
    dlg.protocol('WM_DELETE_WINDOW', lambda: (dlg.destroy(), parent.destroy()))
    parent.wait_window(dlg)
    return ok['v']


def _primeiro_acesso(parent):
    dlg = tk.Toplevel(parent)
    dlg.title('Primeiro acesso — gerente')
    dlg.geometry('400x280'); dlg.transient(parent); dlg.grab_set()
    tk.Label(dlg, text='Cadastre o gerente', font=('Segoe UI', 14, 'bold')).pack(anchor='w', padx=22, pady=(18, 4))
    tk.Label(dlg, text='Não há senha padrão. O primeiro usuário é o gerente.', font=('Segoe UI', 9)).pack(anchor='w', padx=22)
    tk.Label(dlg, text='Nome', font=('Segoe UI', 8, 'bold')).pack(anchor='w', padx=22, pady=(12, 0))
    e_nome = tk.Entry(dlg); e_nome.pack(fill='x', padx=22); e_nome.focus_set()
    tk.Label(dlg, text='Senha (mínimo 8 caracteres)', font=('Segoe UI', 8, 'bold')).pack(anchor='w', padx=22, pady=(10, 0))
    e_senha = tk.Entry(dlg, show='*'); e_senha.pack(fill='x', padx=22)
    ok = {'v': False}

    def criar():
        try:
            g.criar_usuario(e_nome.get().strip(), e_senha.get(), 'gerente')
            g.autenticar(e_nome.get().strip(), e_senha.get())
            ok['v'] = True; dlg.destroy()
        except Exception as exc:
            messagebox.showerror('Erro', str(exc), parent=dlg)
    ttk.Button(dlg, text='Criar e entrar', style='Primary.TButton', command=criar).pack(pady=16)
    parent.wait_window(dlg)
    return ok['v']


def main():
    import sys
    trava = TravaInstancia('mercadinho_reformulado')
    try:
        trava.adquirir()
    except InstanciaJaAberta:
        try:
            import subprocess
            if os.name == 'nt':
                import ctypes
                ctypes.windll.user32.MessageBoxW(0, 'O sistema já está aberto.', 'Mercadinho', 0x40)
            else:
                subprocess.Popen(['notify-send', '-a', 'Mercadinho', 'O sistema já está aberto.'])
        except Exception:
            pass
        sys.exit(0)
    try:
        ok, msg = db.compativel()
        if not ok:
            _erro(msg)
            return
        db.init_db()
        from reformulacao.shell import Shell
        root = Shell()
        if not _login(root):
            root.destroy(); return
        root.iniciar()
        root.mainloop()
    finally:
        trava.liberar()


def _erro(msg):
    try:
        r = tk.Tk(); r.withdraw()
        messagebox.showerror('Versão incompatível', msg)
        r.destroy()
    except Exception:
        print(msg)


if __name__ == '__main__':
    main()
