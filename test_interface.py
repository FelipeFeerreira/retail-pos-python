"""Abre widgets em banco temporário, sem impressora, balança ou dados reais."""
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
import database as db
import gestao as g
import sys
import sqlite3


def main():
    with tempfile.TemporaryDirectory() as pasta:
        original=db.DB_PATH
        db.DB_PATH=str(Path(pasta)/'interface.db')
        if '--loja' in sys.argv:
            origem=sqlite3.connect(f'file:{Path(original).as_posix()}?mode=ro',uri=True)
            copia=sqlite3.connect(db.DB_PATH)
            origem.backup(copia);origem.close();copia.close()
        import app
        app.backup_diario=lambda:None
        app.registrar_fiado_recente=lambda *_:None
        app.App._iniciar_balanca=lambda self:setattr(self,'balanca',None)
        app.App._tela_cheia=lambda self:self.withdraw()
        app.App._login_gestao=lambda self:None
        app.App._tarefas_30min=lambda self:None
        errors=[]
        app.App.report_callback_exception=lambda self,t,v,tb:errors.append(str(v))
        root=app.App()
        g.USUARIO='Teste interface';g.PERFIL='gerente'
        root.update_idletasks();root.update()
        if '--imagem' in sys.argv:
            import ctypes
            import win32gui,win32ui
            root.geometry('1280x850+0+0');root.deiconify();root.nb.select(root.tab_fin)
            root.update_idletasks();root.update()
            hwnd=win32gui.GetAncestor(root.winfo_id(),2)
            rect=win32gui.GetWindowRect(hwnd);w=rect[2]-rect[0];h=rect[3]-rect[1]
            dc=win32gui.GetWindowDC(hwnd);src=win32ui.CreateDCFromHandle(dc);dest=src.CreateCompatibleDC()
            bitmap=win32ui.CreateBitmap();bitmap.CreateCompatibleBitmap(src,w,h);dest.SelectObject(bitmap)
            ctypes.windll.user32.PrintWindow(hwnd,dest.GetSafeHdc(),2)
            saida=Path(__file__).parent/'validacao';saida.mkdir(exist_ok=True)
            bitmap.SaveBitmapFile(dest,str(saida/'financeiro.bmp'))
            win32gui.DeleteObject(bitmap.GetHandle());dest.DeleteDC();src.DeleteDC();win32gui.ReleaseDC(hwnd,dc)
            root.withdraw()
        for tab in root.nb.tabs(): root.nb.select(tab);root.update_idletasks();root.update()
        # Chamadas diretas detectam falhas que o atualizador legado silencioso ocultava.
        for method in ('_carrega_analises','_carrega_painel','_carrega_hist','_carrega_clientes','_carrega_produtos','_carrega_producao','_carrega_estoque','_atualizar_financeiro'):
            getattr(root,method)()
        for method in ('_nova_conta_ui','_abrir_caixa_ui','_nova_conta_financeira_ui','_politica_ui','_catalogo_gestao','_conciliacao_ui','_orcamento_ui','_novo_usuario_ui'):
            getattr(root,method)();root.update_idletasks()
            for w in root.winfo_children():
                if isinstance(w,tk.Toplevel): w.destroy()
        if '--loja' in sys.argv:
            first=root.tvcli.get_children()[0];root.tvcli.selection_set(first)
            root._detalhes_cliente()
            root._abrir_registrar_producao()
            root._compra_varios_ui()
            root._receber_mercadoria_ui()
            root._consumo_recorrente_ui()
            root._abrir_novo_lote_global()
            root.update_idletasks()
        root.destroy()
        if errors: raise RuntimeError(errors)
        print('Interface: abas e formularios criados sem erros de Tkinter.')


if __name__=='__main__':main()
