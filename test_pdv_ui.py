"""Jornada do PDV na nova interface: venda simples, pagamento misto e fiado,
conferindo estoque, vendas, partes do pagamento e título de fiado no banco."""
import tempfile
import tkinter as tk
from pathlib import Path

import database as db
import gestao as g
import operacoes as op


def _add_produto(page, nome):
    page.busca.ent.delete(0, 'end')
    page.busca.ent.insert(0, nome)
    page.busca._buscar()
    assert page.busca.lista.size() >= 1, f'{nome} não achado'
    page.busca.lista.selection_set(0)
    page.busca._escolher()


def main():
    with tempfile.TemporaryDirectory() as pasta:
        db.DB_PATH = str(Path(pasta) / 'pdv.db')
        g.USUARIO, g.PERFIL = 'Teste', 'gerente'
        db.init_db()
        g.abrir_caixa(0)
        g.salvar_politica(None, 500, 30, 0, 0)
        pid = op.criar_produto('REFRIGERANTE', preco_custo=3, preco_venda=8, quantidade_estoque=50)
        cli = op.criar_cliente('Cliente PDV')

        from reformulacao import shell as sh
        sh.messagebox.showinfo = lambda *a, **k: None
        root = sh.Shell(); root.iniciar(); root.update()
        root.ir_para('Vendas'); root.update()
        page = root._paginas['Vendas']

        # Venda simples em dinheiro.
        _add_produto(page, 'REFRIG')
        page._add()
        root.update()
        assert len(page.carrinho) == 1, 'item não entrou no carrinho'
        page.v_forma.set('Dinheiro')
        page._finalizar()
        root.update()
        assert op.obter_produto(pid)['quantidade_estoque'] == 49, 'estoque não baixou'
        venda = g.consultar("SELECT id,forma_pagamento,valor_total FROM vendas ORDER BY id DESC LIMIT 1")[0]
        assert venda['forma_pagamento'] == 'dinheiro' and venda['valor_total'] == 8.0, 'venda em dinheiro errada'

        # Pagamento misto (Pix + Dinheiro).
        _add_produto(page, 'REFRIG'); page._add()
        page.misto.set(True); page._atualiza_forma()
        page.v_forma.set('Pix'); page.v_forma2.set('Dinheiro')
        page.e_valor2.delete(0, 'end'); page.e_valor2.insert(0, '3')
        page._finalizar(); root.update()
        venda2 = g.consultar("SELECT id,forma_pagamento FROM vendas ORDER BY id DESC LIMIT 1")[0]
        partes = g.consultar('SELECT forma,valor_centavos FROM venda_pagamentos WHERE venda_id=?', (venda2['id'],))
        assert venda2['forma_pagamento'] == 'misto' and len(partes) == 2, 'pagamento misto não registrou as partes'
        assert {p['forma'] for p in partes} == {'pix', 'dinheiro'}

        # Venda fiado com cliente.
        _add_produto(page, 'REFRIG'); page._add()
        page.misto.set(False); page._atualiza_forma()
        page.v_forma.set('Fiado'); page.cliente_fiado = {'id': cli, 'nome': 'Cliente PDV'}
        page._finalizar(); root.update()
        titulo = g.consultar('SELECT COUNT(*) n FROM titulos_receber WHERE cliente_id=? AND cancelado=0', (cli,))[0]['n']
        assert titulo == 1, 'venda fiado não gerou título'
        assert op.saldo_fiado(cli) == 8.0, 'saldo fiado errado'
        # Receber fiado não cria nova venda.
        vendas_antes = g.consultar('SELECT COUNT(*) n FROM vendas')[0]['n']
        g.receber_fiado(cli, 8.0)
        assert g.consultar('SELECT COUNT(*) n FROM vendas')[0]['n'] == vendas_antes, 'recebimento duplicou venda'
        assert op.saldo_fiado(cli) == 0.0, 'saldo não quitou'

        root.destroy()
        print('OK: PDV nova interface (simples, misto, fiado) com efeitos conferidos no banco.')


if __name__ == '__main__':
    main()
