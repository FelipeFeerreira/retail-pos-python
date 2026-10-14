"""Jornada real pela NOVA interface (reformulação): pesquisa → seleciona →
preenche → confirma → consulta histórico → confere estoque/resultado. Usa os
widgets de verdade (não substitui o seletor). Banco temporário."""
import tempfile
import tkinter as tk
from datetime import date
from pathlib import Path

import database as db
import gestao as g
import operacoes as op


def main():
    with tempfile.TemporaryDirectory() as pasta:
        db.DB_PATH = str(Path(pasta) / 'nova.db')
        g.USUARIO, g.PERFIL = 'Teste', 'gerente'
        db.init_db()
        g.abrir_caixa(0)

        from reformulacao import shell as sh
        sh.messagebox.askyesno = lambda *a, **k: True

        pid = op.criar_produto('PAO FRANCES', preco_custo=2, preco_venda=5, quantidade_estoque=20)
        root = sh.Shell()
        root.iniciar()
        root.update()

        # Navega para Operacional e usa a aba de consumo.
        root.ir_para('Operacional')
        root.update()
        aba = root._paginas['Operacional'].aba_consumo

        # Pesquisa e seleção EXPLÍCITA usando o código REAL do componente
        # (o mesmo que os eventos de tecla disparam em uso normal).
        aba.busca.ent.insert(0, 'PAO')
        aba.busca._buscar()
        root.update()
        assert aba.busca.lista.size() >= 1, 'sugestões não apareceram'
        aba.busca.lista.selection_set(0)
        aba.busca._escolher()
        root.update()
        assert aba.busca.produto and aba.busca.produto['id'] == pid, 'seleção explícita falhou'
        # Editar o texto invalida a seleção (não mantém ID indevido).
        aba.busca.ent.insert('end', 'X')
        aba.busca._buscar()
        assert aba.busca.produto is None, 'edição deveria invalidar a seleção'
        aba.busca.limpar()
        aba.busca.ent.insert(0, 'PAO'); aba.busca._buscar()
        aba.busca.lista.selection_set(0); aba.busca._escolher()

        aba.qtd.delete(0, 'end'); aba.qtd.insert(0, '3')
        aba._adicionar()
        root.update()
        assert len(aba.carrinho) == 1, 'item não entrou no carrinho'
        aba.finalidade.set('Operacional')
        aba._confirmar()
        root.update()

        # Efeitos persistidos.
        assert op.obter_produto(pid)['quantidade_estoque'] == 17, 'estoque não baixou'
        consumo = g.consultar("SELECT id,finalidade,valor_total FROM consumo_interno ORDER BY id DESC LIMIT 1")[0]
        assert consumo['finalidade'] == 'operacional', 'finalidade não gravada'
        assert consumo['valor_total'] == 6.0, 'custo histórico errado (3 x 2)'
        assert aba.hist.get_children(), 'histórico não atualizou'

        # Início reflete o resultado.
        root.ir_para('Início'); root.update()
        assert 'R$' in root._paginas['Início'].cards['resultado'].lbl.cget('text'), 'card de resultado vazio'

        # Resultados: total do componente == soma do detalhe (consumo operacional).
        root.ir_para('Resultados'); root.update()
        hoje = date.today().isoformat()
        res = g.resultado_gerencial(hoje, hoje)
        det = g.lancamentos_componente('consumo_operacional', hoje, hoje)
        assert round(sum(d['valor'] for d in det), 2) == res['consumo_operacional'] == 6.0, 'detalhe != total'

        root.destroy()
        print('OK: jornada da nova interface (consumo) com efeitos conferidos no banco.')


if __name__ == '__main__':
    main()
