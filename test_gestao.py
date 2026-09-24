"""Regressões de caixa, estoque e migração. Nunca usa o banco operacional."""
import shutil
import sqlite3
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path
import database as db
import gestao as g
import operacoes as op
import producao


class GestaoTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.original=db.DB_PATH; db.DB_PATH=str(Path(self.temp.name)/'teste.db')
        g.USUARIO='Teste';g.PERFIL='gerente'; db.init_db()
        self.hoje=date.today().isoformat()
        g.salvar_politica(None,200,30,0.1,0.05)
        g.abrir_caixa(0)
        self.pid=op.criar_produto('Produto teste',preco_custo=5,preco_venda=10,quantidade_estoque=20)
        self.cid=op.criar_cliente('Cliente teste')

    def tearDown(self):
        db.DB_PATH=self.original;self.temp.cleanup()

    def saldo(self,conta=1): return next(r['saldo_centavos'] for r in g.contas_saldos() if r['id']==conta)

    def venda(self,qtd=10,forma='fiado',**kw):
        return op.registrar_venda([dict(produto_id=self.pid,quantidade=qtd)],forma,cliente_id=self.cid,**kw)

    def test_fiado_parcial_nao_duplica_receita(self):
        self.venda(); self.assertEqual(self.saldo(),0)
        pid=g.receber_fiado(self.cid,40)
        self.assertEqual(self.saldo(),4000); self.assertEqual(op.saldo_fiado(self.cid),60)
        self.assertEqual(g.titulos_cliente(self.cid)[0]['status'],'Parcialmente recebido')
        self.assertIn('Principal: R$ 40.00',g.recibo_fiado(pid))
        d=g.resumo_financeiro(self.hoje,self.hoje)
        self.assertEqual(d['vendas'],100);self.assertEqual(d['entradas'],40);self.assertEqual(d['cmv'],50)

    def test_juros_diarios_sobre_parte_quitada(self):
        self.venda()
        with g.transacao() as c: c.execute('UPDATE titulos_receber SET vencimento=?',((date.today()-timedelta(days=10)).isoformat(),))
        self.assertEqual(g.titulos_cliente(self.cid)[0]['encargos_centavos'],150)
        g.receber_fiado(self.cid,40)
        self.assertEqual(self.saldo(),4060)
        self.assertEqual(g.titulos_cliente(self.cid)[0]['encargos_centavos'],90)

    def test_limite_credito(self):
        with self.assertRaises(op.ErroOperacao): self.venda(21)
        self.assertEqual(op.obter_produto(self.pid)['quantidade_estoque'],20)

    def test_estoque_insuficiente_rollback(self):
        with self.assertRaises(op.ErroOperacao): self.venda(21,'dinheiro')
        self.assertEqual(g.consultar('SELECT COUNT(*) n FROM vendas')[0]['n'],0)
        self.assertEqual(self.saldo(),0)

    def test_itens_repetidos_nao_superam_estoque(self):
        with self.assertRaises(op.ErroOperacao): op.registrar_venda([{'produto_id':self.pid,'quantidade':15}]*2)
        self.assertEqual(op.obter_produto(self.pid)['quantidade_estoque'],20)

    def test_perda_consumo_nao_movimentam_caixa(self):
        op.registrar_perda([dict(produto_id=self.pid,quantidade=2)],'Quebra')
        op.registrar_consumo_interno([dict(produto_id=self.pid,quantidade=1)],'Limpeza')
        self.assertEqual(self.saldo(),0);self.assertEqual(op.obter_produto(self.pid)['quantidade_estoque'],17)
        d=g.resumo_financeiro(self.hoje,self.hoje);self.assertEqual(d['perdas'],10);self.assertEqual(d['consumo'],5)

    def test_pagar_parcial_estornar(self):
        tid=g.criar_conta_pagar('Fornecedor','Compra',500,self.hoje,'Mercadoria para revenda')
        self.assertEqual(self.saldo(2),0)
        pid=g.pagar_conta(tid,200)
        self.assertEqual(self.saldo(2),-20000);self.assertEqual(g.contas_pagar()[0]['saldo_centavos'],30000)
        g.estornar_pagamento(pid,'Teste');self.assertEqual(self.saldo(2),0)
        self.assertEqual(g.contas_pagar()[0]['saldo_centavos'],50000)

    def test_idempotencia_venda_recebimento_pagamento(self):
        a=self.venda(chave_operacao='v1');b=self.venda(chave_operacao='v1')
        self.assertEqual(a['id'],b['id']);self.assertEqual(op.obter_produto(self.pid)['quantidade_estoque'],10)
        g.receber_fiado(self.cid,40,chave_operacao='r1');g.receber_fiado(self.cid,40,chave_operacao='r1')
        self.assertEqual(self.saldo(),4000)
        tid=g.criar_conta_pagar('Fornecedor','Conta',500,self.hoje)
        g.pagar_conta(tid,100,chave='p1');g.pagar_conta(tid,100,chave='p1');self.assertEqual(self.saldo(2),-10000)

    def test_cartao_so_entra_na_liquidacao(self):
        self.venda(1,'cartao_credito',taxa_paga=1)
        self.assertEqual(self.saldo(2),0)
        g.liquidar_cartao(1);self.assertEqual(self.saldo(2),900)
        with self.assertRaises(g.ErroGestao): g.liquidar_cartao(1)

    def test_estorno_fiado_e_cancelamento_restaura_estoque(self):
        v=self.venda();pid=g.receber_fiado(self.cid,40)
        with self.assertRaises(g.ErroGestao): g.cancelar_venda(v['id'],'Teste')
        g.estornar_recebimento(pid,'Teste');self.assertEqual(op.saldo_fiado(self.cid),100)
        g.cancelar_venda(v['id'],'Teste');self.assertEqual(op.saldo_fiado(self.cid),0)
        self.assertEqual(op.obter_produto(self.pid)['quantidade_estoque'],20);self.assertEqual(self.saldo(),0)

    def test_custo_historico_nao_muda_com_preco_atual(self):
        self.venda(2,'dinheiro');op.atualizar_produto(self.pid,preco_custo=99)
        self.assertEqual(g.resumo_financeiro(self.hoje,self.hoje)['cmv'],10)

    def test_lote_vencido_nao_vende_perda_lote_exato(self):
        with g.transacao() as c:
            c.execute('INSERT INTO lotes_validade(produto_id,quantidade,data_validade) VALUES(?,?,?)',(self.pid,20,'2000-01-01'))
        with self.assertRaises(op.ErroOperacao): self.venda(1,'dinheiro')
        op.registrar_perda([dict(produto_id=self.pid,quantidade=2,lote_id=1)],'Validade vencida')
        self.assertEqual(g.consultar('SELECT quantidade FROM lotes_validade')[0]['quantidade'],18)

    def test_producao_atomica_com_rendimento_real(self):
        final=op.criar_produto('Pão produzido',preco_venda=15)
        rid=producao.criar_receita(final,4,[dict(insumo_id=self.pid,quantidade=2)])
        p=producao.registrar_producao(rid,1,validade=self.hoje,rendimento_real=5)
        self.assertEqual(p['custo_total'],10);self.assertEqual(p['custo_unitario'],2)
        self.assertEqual(op.obter_produto(self.pid)['quantidade_estoque'],18)
        self.assertEqual(op.obter_produto(final)['quantidade_estoque'],5)
        with self.assertRaises(producao.ErroProducao): producao.registrar_producao(rid,50,validade=self.hoje)
        self.assertEqual(op.obter_produto(final)['quantidade_estoque'],5)

    def test_caixa_ajuste_nao_e_recebimento(self):
        self.venda();op.ajustar_saldo_cliente(self.cid,20,'Correção justificada')
        self.assertEqual(self.saldo(),0);self.assertEqual(op.saldo_fiado(self.cid),80)
        self.assertEqual(g.titulos_cliente(self.cid)[0]['saldo_centavos'],8000)

    def test_migracao_repetida_preserva_dados(self):
        self.venda();db.init_db();db.init_db()
        self.assertEqual(len(g.titulos_cliente(self.cid)),1);self.assertEqual(op.saldo_fiado(self.cid),100)

    def test_permissoes(self):
        g.PERFIL='caixa'
        with self.assertRaises(g.ErroGestao): g.criar_conta_pagar('X','Y',1,self.hoje)
        with self.assertRaises(g.ErroGestao): g.registrar_baixa([dict(produto_id=self.pid,quantidade=1)],'Teste')

    def test_fechamento_caixa(self):
        self.venda(1,'dinheiro')
        with self.assertRaises(g.ErroGestao): g.fechar_caixa(9)
        self.assertEqual(g.fechar_caixa(10),10)

    def test_conciliacao_nao_duplica_caixa(self):
        self.venda(1,'pix')
        f=Path(self.temp.name)/'extrato.csv';f.write_text(f'data;descricao;valor;identificador\n{self.hoje};PIX;10;pix1\n',encoding='utf-8')
        self.assertEqual(g.importar_extrato(f,2),1);self.assertEqual(g.importar_extrato(f,2),0)
        g.conciliar(1,1);self.assertEqual(self.saldo(2),1000)

    def test_compra_multiplos_itens_gera_uma_obrigacao(self):
        segundo=op.criar_produto('Insumo',preco_custo=2,preco_venda=5)
        compra=g.receber_compra([dict(produto_id=self.pid,quantidade=2,custo=10),dict(produto_id=segundo,quantidade=3,custo=2)],'Fornecedor','NF1',self.hoje)
        self.assertEqual(compra,1);self.assertEqual(g.contas_pagar()[0]['saldo_centavos'],2600)
        self.assertEqual(op.obter_produto(self.pid)['quantidade_estoque'],22)
        self.assertAlmostEqual(op.obter_produto(self.pid)['preco_custo'],120/22)
        self.assertEqual(self.saldo(2),0)
        with self.assertRaises(g.ErroGestao): g.receber_compra([dict(produto_id=segundo,quantidade=3,custo=2)],'Fornecedor','NF1',self.hoje)

    def test_compra_avista_e_rollback_perecivel(self):
        with g.transacao() as c: c.execute('UPDATE produtos SET perecivel=1 WHERE id=?',(self.pid,))
        with self.assertRaises(g.ErroGestao): g.receber_compra([dict(produto_id=self.pid,quantidade=2,custo=10)],'F','N',self.hoje,'À vista')
        self.assertEqual(len(g.contas_pagar()),0)
        g.receber_compra([dict(produto_id=self.pid,quantidade=2,custo=10,validade=self.hoje)],'F','N',self.hoje,'À vista')
        self.assertEqual(self.saldo(2),-2000);self.assertEqual(g.contas_pagar()[0]['status'],'Pago')

    def test_pagamento_dividido(self):
        self.venda(2,'dinheiro',pagamentos=[dict(forma='dinheiro',valor=5),dict(forma='cartao_credito',valor=15)])
        self.assertEqual(self.saldo(),500);self.assertEqual(self.saldo(2),0)
        g.liquidar_cartao(1,taxa=1);self.assertEqual(self.saldo(2),1400)
        self.assertEqual(g.resumo_financeiro(self.hoje,self.hoje)['taxas'],1)

    def test_analises_contam_fiado_e_desconto_sem_recebimento_duplo(self):
        import analises as a
        self.venda(10,desconto=10)
        g.receber_fiado(self.cid,40)
        resumo=a.resumo_periodo(self.hoje,self.hoje)
        self.assertEqual(resumo['faturamento'],90)
        self.assertEqual(resumo['lucro_estimado'],40)
        self.assertEqual(a.serie_temporal('dia',self.hoje,self.hoje)[0]['lucro_estimado'],40)

    def test_editar_produto_com_codigo_interno_legado(self):
        with g.transacao() as c: c.execute("UPDATE produtos SET codigo_barras='9000' WHERE id=?",(self.pid,))
        op.atualizar_produto(self.pid,preco_venda=11)
        self.assertEqual(op.buscar_por_codigo('9000')['id'],self.pid)

    def test_receita_snapshot_preserva_insumos(self):
        final=op.criar_produto('Produto final',preco_venda=15)
        rid=producao.criar_receita(final,4,[dict(insumo_id=self.pid,quantidade=2)])
        p=producao.registrar_producao(rid,1,validade=self.hoje)
        producao.atualizar_receita(rid,itens=[dict(insumo_id=self.pid,quantidade=3)])
        self.assertEqual(producao.detalhar_producao(p['id'])['insumos'][0]['quantidade'],2)

    def test_aporte_entrada_real_sem_receita_de_venda(self):
        with g.transacao() as c: g.movimento(c,1,10000,'Aporte','Capital','manual','x')
        d=g.resumo_financeiro(self.hoje,self.hoje)
        self.assertEqual(d['entradas'],100);self.assertEqual(d['vendas'],0);self.assertEqual(d['resultado'],0)
        self.assertEqual(d['fluxo_livre'],0)

    def test_promocao_e_cancelamento_analises(self):
        import analises as a
        with g.transacao() as c:c.execute('INSERT INTO promocoes(produto_id,inicio,fim,preco) VALUES(?,?,?,?)',(self.pid,self.hoje,self.hoje,8))
        v=self.venda(2,'dinheiro');self.assertEqual(v['valor_total'],16)
        g.cancelar_venda(v['id'],'Devolução')
        self.assertEqual(a.resumo_periodo(self.hoje,self.hoje)['faturamento'],0)

    def test_codigos_e_quantidade_invalidos(self):
        for q in (float('nan'),float('inf'),0.0001):
            with self.assertRaises(g.ErroGestao): g.quantidade(q)
        with self.assertRaises(g.ErroGestao): g.validar_codigo('1234567890123')
        g.validar_codigo('7894900011517')


if __name__=='__main__': unittest.main(verbosity=2)
