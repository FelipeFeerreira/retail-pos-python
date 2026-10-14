"""Teste de GUI dos lançamentos operacionais: fluxo de perda com lote físico,
conferindo estoque, lotes, rastreabilidade e histórico. Banco temporário."""
import tempfile
import tkinter as tk
from datetime import date, timedelta
from pathlib import Path

import database as db
import gestao as g
import operacoes as op
import validade as val


def main():
    with tempfile.TemporaryDirectory() as pasta:
        db.DB_PATH = str(Path(pasta) / 'op.db')
        import app
        app.backup_diario = lambda *a: (None, False)
        app.registrar_fiado_recente = lambda *_: None
        app.App._iniciar_balanca = lambda self: setattr(self, 'balanca', None)
        app.App._tela_cheia = lambda self: self.geometry('1000x700+0+0')
        app.App._login_gestao = lambda self: None
        app.App._tarefas_30min = lambda self: None
        root = app.App()
        root.update()
        g.USUARIO, g.PERFIL = 'Teste', 'gerente'
        g.abrir_caixa(0)

        # Perecível com 2 lotes: 2 vencidos e 8 válidos.
        pid = op.criar_produto('IOGURTE', preco_custo=3, preco_venda=6, quantidade_estoque=10)
        conn = db.get_conn()
        try:
            conn.execute('UPDATE produtos SET perecivel=1 WHERE id=?', (pid,))
            conn.commit()
        finally:
            conn.close()
        vencido = val.registrar_lote(pid, 2, (date.today() - timedelta(days=1)).isoformat())
        val.registrar_lote(pid, 8, (date.today() + timedelta(days=10)).isoformat())
        produto = op.obter_produto(pid)

        # A perda usa o lote físico escolhido (aqui simulado pelo seletor).
        root._escolher_lote_perda = lambda prod: {
            'lote_id': vencido, 'validade': (date.today() - timedelta(days=1)).isoformat(), 'quantidade': 2}
        root._adicionar_perda(produto, 1)
        assert len(root.carrinho_perda) == 1 and root.carrinho_perda[0]['lote_id'] == vencido, 'lote não foi guardado no carrinho'

        app.messagebox.askyesno = lambda *a, **k: True
        root._confirmar_perda()
        root.update()

        # Confere efeitos persistidos.
        assert op.obter_produto(pid)['quantidade_estoque'] == 9, 'estoque não baixou'
        lote = g.consultar('SELECT quantidade FROM lotes_validade WHERE id=?', (vencido,))[0]
        assert lote['quantidade'] == 1, 'lote vencido não baixou'
        perda = g.consultar('SELECT id,motivo FROM perdas ORDER BY id DESC LIMIT 1')[0]
        assert perda['motivo'] == 'Validade vencida', 'motivo da perda errado'
        rastreio = g.consultar("SELECT lote_id,quantidade FROM baixas_lotes WHERE origem='Perda' AND referencia=?", (str(perda['id']),))
        assert rastreio and rastreio[0]['lote_id'] == vencido, 'rastreabilidade do lote não registrada'
        itens = g.consultar('SELECT quantidade FROM itens_perda WHERE perda_id=?', (perda['id'],))
        assert itens and itens[0]['quantidade'] == 1, 'item da perda não registrado'

        # O diálogo de produção (com prévia) precisa abrir sem erro.
        final = op.criar_produto('PAO', preco_custo=1, preco_venda=5, quantidade_estoque=0)
        insumo = op.criar_produto('FARINHA', preco_custo=2, preco_venda=3, quantidade_estoque=50)
        import producao
        producao.criar_receita(final, rendimento=10, itens=[{'insumo_id': insumo, 'quantidade': 10}])
        root._abrir_registrar_producao()
        root.update()
        tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        assert tops, 'diálogo de produção não abriu'
        tops[-1].destroy()

        # Painel gerencial: linhas do resultado e bloco de caixa preenchidos.
        root._atualizar_financeiro()
        root.update()
        assert root.dre_tree.get_children(), 'painel do resultado não foi preenchido'
        assert root.caixa_tree.get_children(), 'bloco de caixa não foi preenchido'
        hoje = date.today().isoformat()
        esperado = g.resultado_gerencial(hoje, hoje)['resultado_apos_retiradas']
        linha_final = root.dre_tree.item(root.dre_tree.get_children()[-1], 'values')
        assert 'RETIRADAS' in str(linha_final[0]).upper(), 'última linha deveria ser o resultado após retiradas'

        root.destroy()
        print('OK: perda por lote (estoque/lote/rastreio/histórico) e diálogo de produção funcionam.')


if __name__ == '__main__':
    main()
