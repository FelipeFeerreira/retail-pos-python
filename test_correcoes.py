"""Regressões das correções de segurança, importação NF-e, backup e trava de
instância. Sempre usa banco temporário — nunca o banco operacional."""
import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import database as db
import gestao as g
import operacoes as op
import producao as prod
import validade as val
import backup as bk
import importar_nfe as nfe
from applock import TravaInstancia, InstanciaJaAberta


XML_NFE = '''<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe Id="NFe35200114200166000187550010000000015000000015" versao="4.00">
<ide><nNF>1234</nNF><serie>1</serie><dhEmi>2026-10-01T10:00:00-03:00</dhEmi></ide>
<emit><CNPJ>14200166000187</CNPJ><xNome>FORNECEDOR TESTE LTDA</xNome></emit>
<det nItem="1"><prod><cProd>001</cProd><cEAN>7891234567895</cEAN><xProd>ARROZ TESTE</xProd><NCM>1006</NCM><CFOP>5102</CFOP><uCom>UN</uCom><qCom>10.0000</qCom><vUnCom>5.00</vUnCom><vProd>50.00</vProd></prod></det>
<det nItem="2"><prod><cProd>002</cProd><cEAN>7891234567802</cEAN><xProd>IOGURTE TESTE</xProd><NCM>0403</NCM><CFOP>5102</CFOP><uCom>UN</uCom><qCom>6.0000</qCom><vUnCom>4.00</vUnCom><vProd>24.00</vProd></prod></det>
<total><ICMSTot><vNF>74.00</vNF></ICMSTot></total>
</infNFe></NFe></nfeProc>'''


class BaseTemp(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = db.DB_PATH
        db.DB_PATH = str(Path(self.temp.name) / 'teste.db')
        g.USUARIO = 'Teste'
        g.PERFIL = 'gerente'
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.original
        g.sair()
        self.temp.cleanup()


class TravaInstanciaTest(BaseTemp):
    def test_segunda_instancia_bloqueada(self):
        nome = f'teste_lock_{os.getpid()}'
        a = TravaInstancia(nome)
        a.adquirir()
        try:
            b = TravaInstancia(nome)
            with self.assertRaises(InstanciaJaAberta):
                b.adquirir()
        finally:
            a.liberar()
        # Depois de liberar, outra instância consegue.
        c = TravaInstancia(nome)
        c.adquirir()
        c.liberar()


class AutenticacaoTest(BaseTemp):
    def test_perfil_padrao_sem_privilegios(self):
        g.sair()
        self.assertIsNone(g.PERFIL)
        with self.assertRaises(g.ErroGestao):
            g.permitir('configurar')
        with self.assertRaises(g.ErroGestao):
            g.permitir('venda')

    def test_bootstrap_primeiro_usuario_e_perfis(self):
        g.sair()
        # Primeiro usuário é criado sem autenticação prévia (mas precisa ser gerente).
        with self.assertRaises(g.ErroGestao):
            g.criar_usuario('x', 'senha1234', 'caixa')
        g.criar_usuario('admin', 'senha1234', 'gerente')
        # Depois disso, cadastro exige autenticação com permissão.
        with self.assertRaises(g.ErroGestao):
            g.criar_usuario('y', 'senha1234', 'caixa')
        self.assertTrue(g.autenticar('admin', 'senha1234'))
        g.criar_usuario('caixa1', 'senha1234', 'caixa')
        g.sair()
        self.assertTrue(g.autenticar('caixa1', 'senha1234'))
        # Caixa vende, mas não configura nem cadastra usuário.
        g.permitir('venda')
        with self.assertRaises(g.ErroGestao):
            g.permitir('configurar')
        with self.assertRaises(g.ErroGestao):
            g.criar_usuario('z', 'senha1234', 'caixa')

    def test_sair_bloqueia_e_troca_de_senha(self):
        g.criar_usuario('admin', 'senha1234', 'gerente')
        g.autenticar('admin', 'senha1234')
        g.alterar_senha('admin', 'novasenha1', 'senha1234')
        g.sair()
        self.assertFalse(g.autenticar('admin', 'senha1234'))
        self.assertTrue(g.autenticar('admin', 'novasenha1'))


class CustoMedioNegativoTest(BaseTemp):
    def _produto_saldo(self, saldo, custo=10.0):
        pid = op.criar_produto('PROD NEG', preco_custo=custo, preco_venda=20,
                               quantidade_estoque=0)
        conn = db.get_conn()
        try:
            conn.execute('UPDATE produtos SET quantidade_estoque=? WHERE id=?', (saldo, pid))
            conn.commit()
        finally:
            conn.close()
        return pid

    def test_helper_sem_divisao_por_zero(self):
        self.assertEqual(g.custo_medio_entrada(-5, 10, 5, 3), 3.0)   # zera o saldo
        self.assertEqual(g.custo_medio_entrada(0, 10, 5, 3), 3.0)
        self.assertEqual(g.custo_medio_entrada(-5, 10, 10, 3), 3.0)  # fica positivo
        self.assertEqual(g.custo_medio_entrada(5, 2, 5, 4), 3.0)     # média normal

    def test_ajustar_estoque_negativo_zera(self):
        pid = self._produto_saldo(-5)
        novo = g.ajustar_estoque(pid, 5, 'entrada', 'Regularização doc 1', custo=3)
        self.assertEqual(novo, 0)
        p = op.obter_produto(pid)
        self.assertEqual(p['quantidade_estoque'], 0)
        self.assertEqual(p['preco_custo'], 3.0)  # custo documentado, não inventado

    def test_ajustar_estoque_negativo_fica_positivo(self):
        pid = self._produto_saldo(-5)
        g.ajustar_estoque(pid, 10, 'entrada', 'Regularização doc 2', custo=4)
        p = op.obter_produto(pid)
        self.assertEqual(p['quantidade_estoque'], 5)
        self.assertEqual(p['preco_custo'], 4.0)

    def test_ajustar_estoque_negativo_continua_negativo(self):
        pid = self._produto_saldo(-5)
        g.ajustar_estoque(pid, 2, 'entrada', 'Regularização doc 3', custo=4)
        p = op.obter_produto(pid)
        self.assertEqual(p['quantidade_estoque'], -3)
        self.assertEqual(p['preco_custo'], 4.0)

    def test_receber_compra_estoque_negativo(self):
        pid = self._produto_saldo(-5, custo=8)
        comp = g.receber_compra([{'produto_id': pid, 'quantidade': 5, 'custo': 3.0}],
                                'FORNECEDOR', 'DOC1', (date.today() + timedelta(days=10)).isoformat())
        p = op.obter_produto(pid)
        self.assertEqual(p['quantidade_estoque'], 0)
        self.assertEqual(p['preco_custo'], 3.0)
        self.assertTrue(comp)

    def test_producao_estoque_negativo_zera(self):
        final = self._produto_saldo(-5, custo=8)
        insumo = op.criar_produto('INSUMO', preco_custo=1, preco_venda=2, quantidade_estoque=100)
        rid = prod.criar_receita(final, rendimento=5, itens=[{'insumo_id': insumo, 'quantidade': 5}])
        validade = (date.today() + timedelta(days=30)).isoformat()
        r = g.registrar_producao(rid, 1, validade=validade)
        p = op.obter_produto(final)
        self.assertEqual(p['quantidade_estoque'], 0)
        self.assertGreater(r['custo_unitario'], 0)

    def test_producao_estoque_negativo_fica_positivo(self):
        final = self._produto_saldo(-5, custo=8)
        insumo = op.criar_produto('INSUMO2', preco_custo=2, preco_venda=3, quantidade_estoque=100)
        rid = prod.criar_receita(final, rendimento=5, itens=[{'insumo_id': insumo, 'quantidade': 5}])
        validade = (date.today() + timedelta(days=30)).isoformat()
        g.registrar_producao(rid, 3, validade=validade)  # produz 15
        p = op.obter_produto(final)
        self.assertEqual(p['quantidade_estoque'], 10)


class LoteVencidoTest(BaseTemp):
    def setUp(self):
        super().setUp()
        g.abrir_caixa(0)
        self.pid = op.criar_produto('PERECIVEL', preco_custo=2, preco_venda=5, quantidade_estoque=10)
        conn = db.get_conn()
        try:
            conn.execute('UPDATE produtos SET perecivel=1 WHERE id=?', (self.pid,))
            conn.commit()
        finally:
            conn.close()
        self.vencido = val.registrar_lote(self.pid, 2, (date.today() - timedelta(days=2)).isoformat())
        self.valido = val.registrar_lote(self.pid, 8, (date.today() + timedelta(days=10)).isoformat())

    def test_consumo_lote_vencido_bloqueado_sem_efeito(self):
        with self.assertRaises(g.ErroGestao):
            g.registrar_baixa([{'produto_id': self.pid, 'quantidade': 1, 'lote_id': self.vencido}],
                              'Limpeza', perda=False)
        self.assertEqual(op.obter_produto(self.pid)['quantidade_estoque'], 10)
        self.assertEqual(g.consultar('SELECT COUNT(*) n FROM consumo_interno')[0]['n'], 0)

    def test_perda_lote_vencido_permitida(self):
        r = g.registrar_baixa([{'produto_id': self.pid, 'quantidade': 1, 'lote_id': self.vencido}],
                              'Validade vencida', perda=True)
        self.assertTrue(r['id'])
        self.assertEqual(op.obter_produto(self.pid)['quantidade_estoque'], 9)
        lote = g.consultar('SELECT quantidade FROM lotes_validade WHERE id=?', (self.vencido,))[0]
        self.assertEqual(lote['quantidade'], 1)

    def test_lote_de_outro_produto_rejeitado(self):
        outro = op.criar_produto('OUTRO', preco_custo=1, preco_venda=2, quantidade_estoque=5)
        outro_lote = val.registrar_lote(outro, 1, (date.today() + timedelta(days=5)).isoformat())
        with self.assertRaises(g.ErroGestao):
            g.registrar_baixa([{'produto_id': self.pid, 'quantidade': 1, 'lote_id': outro_lote}],
                              'Limpeza', perda=False)

    def test_quantidade_maior_que_lote_rejeitada(self):
        with self.assertRaises(g.ErroGestao):
            g.registrar_baixa([{'produto_id': self.pid, 'quantidade': 9, 'lote_id': self.valido}],
                              'Limpeza', perda=False)
        self.assertEqual(op.obter_produto(self.pid)['quantidade_estoque'], 10)
        self.assertEqual(g.consultar('SELECT COUNT(*) n FROM consumo_interno')[0]['n'], 0)


class RelatorioProducaoCanceladaTest(BaseTemp):
    def test_venda_cancelada_nao_conta_como_vendido(self):
        g.abrir_caixa(0)
        pao = op.criar_produto('PAO', preco_custo=2, preco_venda=10, quantidade_estoque=0)
        farinha = op.criar_produto('FARINHA', preco_custo=1, preco_venda=2, quantidade_estoque=100)
        rid = prod.criar_receita(pao, rendimento=10, itens=[{'insumo_id': farinha, 'quantidade': 10}])
        g.registrar_producao(rid, 1, validade=(date.today() + timedelta(days=30)).isoformat())
        venda = op.registrar_venda([{'produto_id': pao, 'quantidade': 1}], 'dinheiro')
        hoje = date.today()
        rel = prod.relatorio_diario_produto(pao, hoje.year, hoje.month)
        self.assertEqual(rel['totais']['vendido'], 1)
        g.cancelar_venda(venda['id'], 'Cliente desistiu')
        rel2 = prod.relatorio_diario_produto(pao, hoje.year, hoje.month)
        self.assertEqual(rel2['totais']['vendido'], 0)

    def test_consumo_cliente_ignora_cancelada(self):
        cli = op.criar_cliente('Cliente Cancelado')
        p = op.criar_produto('ITEM', preco_custo=1, preco_venda=5, quantidade_estoque=50)
        g.abrir_caixa(0)
        v = op.registrar_venda([{'produto_id': p, 'quantidade': 3}], 'dinheiro', cliente_id=cli)
        self.assertEqual(op.consumo_cliente(cli)['produtos'][0]['qtd'], 3)
        g.cancelar_venda(v['id'], 'Engano')
        self.assertEqual(op.consumo_cliente(cli)['produtos'], [])


class IdempotenciaTest(BaseTemp):
    def test_consumo_mesma_chave_nao_duplica(self):
        g.abrir_caixa(0)
        p = op.criar_produto('ITEM IDEM', preco_custo=1, preco_venda=2, quantidade_estoque=50)
        r1 = op.registrar_consumo_interno([{'produto_id': p, 'quantidade': 2}], 'Limpeza', chave='k1')
        r2 = op.registrar_consumo_interno([{'produto_id': p, 'quantidade': 2}], 'Limpeza', chave='k1')
        self.assertEqual(r1['id'], r2['id'])
        self.assertEqual(g.consultar('SELECT COUNT(*) n FROM consumo_interno')[0]['n'], 1)
        self.assertEqual(op.obter_produto(p)['quantidade_estoque'], 48)
        # Chave distinta = operação legítima nova.
        op.registrar_consumo_interno([{'produto_id': p, 'quantidade': 2}], 'Limpeza', chave='k2')
        self.assertEqual(g.consultar('SELECT COUNT(*) n FROM consumo_interno')[0]['n'], 2)
        self.assertEqual(op.obter_produto(p)['quantidade_estoque'], 46)

    def test_perda_mesma_chave_nao_duplica(self):
        g.abrir_caixa(0)
        p = op.criar_produto('ITEM PERDA', preco_custo=1, preco_venda=2, quantidade_estoque=10)
        r1 = op.registrar_perda([{'produto_id': p, 'quantidade': 1}], 'Quebra', chave='p1')
        r2 = op.registrar_perda([{'produto_id': p, 'quantidade': 1}], 'Quebra', chave='p1')
        self.assertEqual(r1['id'], r2['id'])
        self.assertEqual(g.consultar('SELECT COUNT(*) n FROM perdas')[0]['n'], 1)
        self.assertEqual(op.obter_produto(p)['quantidade_estoque'], 9)

    def test_producao_mesma_chave_nao_duplica(self):
        final = op.criar_produto('FINAL', preco_custo=1, preco_venda=2, quantidade_estoque=0)
        insumo = op.criar_produto('INSUMO', preco_custo=1, preco_venda=2, quantidade_estoque=100)
        rid = prod.criar_receita(final, rendimento=5, itens=[{'insumo_id': insumo, 'quantidade': 5}])
        validade = (date.today() + timedelta(days=30)).isoformat()
        r1 = g.registrar_producao(rid, 1, validade=validade, chave='prod1')
        r2 = g.registrar_producao(rid, 1, validade=validade, chave='prod1')
        self.assertEqual(r1['id'], r2['id'])
        self.assertEqual(g.consultar('SELECT COUNT(*) n FROM producoes')[0]['n'], 1)
        self.assertEqual(op.obter_produto(final)['quantidade_estoque'], 5)
        self.assertEqual(op.obter_produto(insumo)['quantidade_estoque'], 95)


class MigracaoVersaoTest(BaseTemp):
    def test_backup_pre_migracao_ao_mudar_versao(self):
        pasta_backups = Path(self.temp.name) / 'backups'
        # Simula um banco na versão anterior (2), sem as colunas de idempotência.
        conn = db.get_conn()
        try:
            for idx in ('idx_consumo_chave', 'idx_perda_chave', 'idx_producao_chave'):
                conn.execute(f'DROP INDEX IF EXISTS {idx}')
            for t in ('consumo_interno', 'perdas', 'producoes'):
                if 'chave' in [r['name'] for r in conn.execute(f'PRAGMA table_info({t})')]:
                    conn.execute(f'ALTER TABLE {t} DROP COLUMN chave')
            conn.execute("UPDATE schema_meta SET valor='2' WHERE chave='versao'")
            conn.commit()
        finally:
            conn.close()
        # Aumentar a versão do esquema deve disparar backup pré-migração.
        db.init_db()
        backups = list(pasta_backups.glob('antes_migracao_v*_*.db')) if pasta_backups.exists() else []
        self.assertTrue(backups, 'backup pré-migração não foi criado ao mudar a versão')
        conn = db.get_conn()
        try:
            self.assertEqual(conn.execute("SELECT valor FROM schema_meta WHERE chave='versao'").fetchone()['valor'],
                             str(db.SCHEMA_VERSAO))
            for t in ('consumo_interno', 'perdas', 'producoes'):
                self.assertIn('chave', [r['name'] for r in conn.execute(f'PRAGMA table_info({t})')])
        finally:
            conn.close()

    def test_migracao_repetida_nao_recria_backup(self):
        pasta_backups = Path(self.temp.name) / 'backups'
        conn = db.get_conn()
        try:
            conn.execute("UPDATE schema_meta SET valor='2' WHERE chave='versao'")
            conn.commit()
        finally:
            conn.close()
        db.init_db()  # migra 2 -> atual e cria backup
        antes = set(os.listdir(pasta_backups)) if pasta_backups.exists() else set()
        self.assertTrue(antes, 'esperava um backup na primeira migração')
        db.init_db()  # repetida: já na versão corrente, não cria backup novo
        depois = set(os.listdir(pasta_backups)) if pasta_backups.exists() else set()
        self.assertEqual(depois - antes, set(), 'migração repetida não deve criar backup novo')


class ResultadoGerencialTest(BaseTemp):
    def setUp(self):
        super().setUp()
        g.abrir_caixa(0)
        g.salvar_politica(None, 500, 30, 0, 0)
        self.hoje = date.today().isoformat()
        # P1 custo 6 / venda 10; P2 custo 5 / venda 8.
        self.p1 = op.criar_produto('P1', preco_custo=6, preco_venda=10, quantidade_estoque=1000)
        self.p2 = op.criar_produto('P2', preco_custo=5, preco_venda=8, quantidade_estoque=100)

    def test_estrutura_do_resultado(self):
        # Vendas 1000 (100 x 10), CMV 600, taxa 10.
        op.registrar_venda([{'produto_id': self.p1, 'quantidade': 100}], 'dinheiro', taxa_paga=10)
        # Consumo operacional 20 (4 x 5) e equipe 10 (2 x 5).
        op.registrar_consumo_interno([{'produto_id': self.p2, 'quantidade': 4}], 'Limpeza')
        op.registrar_consumo_interno([{'produto_id': self.p2, 'quantidade': 2}], 'Lanches da equipe')
        # Perda 20 (4 x 5).
        op.registrar_perda([{'produto_id': self.p2, 'quantidade': 4}], 'Quebra/avaria')
        # Despesa 100 por competência.
        g.criar_conta_pagar('Imobiliária', 'Aluguel', 100, self.hoje, categoria='Aluguel', competencia=self.hoje)
        # Retirada familiar 40 (8 x 5).
        op.registrar_consumo_interno([{'produto_id': self.p2, 'quantidade': 8}], 'Consumo pessoal/família')

        r = g.resultado_gerencial(self.hoje, self.hoje)
        self.assertEqual(r['vendas_liquidas'], 1000)
        self.assertEqual(r['cmv'], 600)
        self.assertEqual(r['taxas'], 10)
        self.assertEqual(r['perdas'], 20)
        self.assertEqual(r['consumo_operacional'], 20)
        self.assertEqual(r['consumo_equipe'], 10)
        self.assertEqual(r['consumo_outro'], 0)
        self.assertEqual(r['despesas_competencia'], 100)
        self.assertEqual(r['resultado_liquido'], 240)          # 1000-600-10-20-20-10-100
        self.assertEqual(r['retiradas_pessoais'], 40)
        self.assertEqual(r['resultado_apos_retiradas'], 200)   # 240 - 40
        self.assertFalse(r['parcial'])

        # Estoque diminuiu pela retirada (18 unidades de P2: 4+2+4+8).
        self.assertEqual(op.obter_produto(self.p2)['quantidade_estoque'], 82)
        # Consumo não gera saída de dinheiro.
        self.assertEqual(g.consultar("SELECT COUNT(*) n FROM movimentos_financeiros WHERE origem='consumo'")[0]['n'], 0)

    def test_drilldown_soma_bate_com_o_painel(self):
        op.registrar_venda([{'produto_id': self.p1, 'quantidade': 100}], 'dinheiro', taxa_paga=10)
        op.registrar_consumo_interno([{'produto_id': self.p2, 'quantidade': 4}], 'Limpeza')
        op.registrar_consumo_interno([{'produto_id': self.p2, 'quantidade': 8}], 'Consumo pessoal/família')
        r = g.resultado_gerencial(self.hoje, self.hoje)
        detalhe_vendas = g.lancamentos_componente('vendas', self.hoje, self.hoje)
        self.assertAlmostEqual(sum(d['valor'] for d in detalhe_vendas), r['vendas_liquidas'], 2)
        detalhe_consumo = g.lancamentos_componente('consumo_operacional', self.hoje, self.hoje)
        self.assertAlmostEqual(sum(d['valor'] for d in detalhe_consumo), r['consumo_operacional'], 2)
        detalhe_pessoal = g.lancamentos_componente('retiradas_pessoais', self.hoje, self.hoje)
        self.assertAlmostEqual(sum(d['valor'] for d in detalhe_pessoal), r['retiradas_pessoais'], 2)

    def test_custo_desconhecido_marca_parcial(self):
        p = op.criar_produto('SEM CUSTO', preco_custo=0, preco_venda=5, quantidade_estoque=10)
        op.registrar_consumo_interno([{'produto_id': p, 'quantidade': 1}], 'Limpeza')
        r = g.resultado_gerencial(self.hoje, self.hoje)
        self.assertTrue(r['parcial'])
        self.assertTrue(any('consumo' in p.lower() for p in r['pendencias']))

    def test_compra_de_mercadoria_nao_entra_como_despesa(self):
        g.receber_compra([{'produto_id': self.p1, 'quantidade': 10, 'custo': 6.0}],
                         'Fornecedor', 'DOC-1', self.hoje)
        r = g.resultado_gerencial(self.hoje, self.hoje)
        self.assertEqual(r['despesas_competencia'], 0)  # mercadoria não é despesa; vira estoque

    def test_conta_parcial_afeta_competencia_e_caixa(self):
        tid = g.criar_conta_pagar('Energia', 'Conta de luz', 100, self.hoje, categoria='Energia', competencia=self.hoje)
        r1 = g.resultado_gerencial(self.hoje, self.hoje)
        self.assertEqual(r1['despesas_competencia'], 100)  # competência: valor cheio
        g.pagar_conta(tid, 40, conta_id=2, metodo='Pix')
        r2 = g.resultado_gerencial(self.hoje, self.hoje)
        self.assertEqual(r2['despesas_competencia'], 100)  # pagamento parcial não duplica
        painel = g.painel_financeiro(self.hoje, self.hoje)
        self.assertEqual(painel['saidas'], 40)             # caixa: só o que foi pago

    def test_fiado_e_recebimento_nao_duplicam_receita(self):
        cli = op.criar_cliente('Cliente Fiado')
        op.registrar_venda([{'produto_id': self.p1, 'quantidade': 5}], 'fiado', cliente_id=cli)
        r1 = g.resultado_gerencial(self.hoje, self.hoje)
        self.assertEqual(r1['vendas_liquidas'], 50)
        g.receber_fiado(cli, 50)
        r2 = g.resultado_gerencial(self.hoje, self.hoje)
        self.assertEqual(r2['vendas_liquidas'], 50)        # recebimento não é nova venda
        painel = g.painel_financeiro(self.hoje, self.hoje)
        self.assertEqual(painel['entradas'], 50)           # mas entra no caixa
        self.assertEqual(painel['fiado_receber'], 0)

    def test_producao_nao_duplica_custo(self):
        insumo = op.criar_produto('INSUMO', preco_custo=2, preco_venda=3, quantidade_estoque=100)
        final = op.criar_produto('FINAL', preco_custo=0, preco_venda=10, quantidade_estoque=0)
        rid = prod.criar_receita(final, rendimento=10, itens=[{'insumo_id': insumo, 'quantidade': 10}])
        g.registrar_producao(rid, 1, validade=(date.today() + timedelta(days=30)).isoformat())
        r = g.resultado_gerencial(self.hoje, self.hoje)
        self.assertEqual(r['consumo_operacional'] + r['consumo_equipe'] + r['consumo_outro'], 0)
        self.assertEqual(r['perdas'], 0)
        self.assertEqual(op.obter_produto(final)['quantidade_estoque'], 10)
        self.assertEqual(op.obter_produto(insumo)['quantidade_estoque'], 90)

    def test_estorno_corrige_indicadores(self):
        c = op.registrar_consumo_interno([{'produto_id': self.p2, 'quantidade': 4}], 'Limpeza')
        self.assertEqual(g.resultado_gerencial(self.hoje, self.hoje)['consumo_operacional'], 20)
        self.assertEqual(op.obter_produto(self.p2)['quantidade_estoque'], 96)
        op.estornar_consumo_interno(c['id'], 'Lancei errado')
        self.assertEqual(g.resultado_gerencial(self.hoje, self.hoje)['consumo_operacional'], 0)
        self.assertEqual(op.obter_produto(self.p2)['quantidade_estoque'], 100)
        with self.assertRaises(op.ErroOperacao):
            op.estornar_consumo_interno(c['id'], 'de novo')  # estorno duplicado bloqueado

    def test_estorno_perda_devolve_lote(self):
        conn = db.get_conn()
        try:
            conn.execute('UPDATE produtos SET perecivel=1 WHERE id=?', (self.p2,))
            conn.commit()
        finally:
            conn.close()
        lote = val.registrar_lote(self.p2, 5, (date.today() - timedelta(days=1)).isoformat())
        p = op.registrar_perda([{'produto_id': self.p2, 'quantidade': 3, 'lote_id': lote}], 'Validade vencida')
        self.assertEqual(g.consultar('SELECT quantidade FROM lotes_validade WHERE id=?', (lote,))[0]['quantidade'], 2)
        op.estornar_perda(p['id'], 'Era aproveitável')
        self.assertEqual(g.consultar('SELECT quantidade FROM lotes_validade WHERE id=?', (lote,))[0]['quantidade'], 5)
        self.assertEqual(g.resultado_gerencial(self.hoje, self.hoje)['perdas'], 0)

    def test_falha_no_segundo_item_reverte_tudo(self):
        # Segundo item sem saldo: a transação inteira (cabeçalho, itens, estoque) volta.
        with self.assertRaises(op.ErroOperacao):
            op.registrar_consumo_interno(
                [{'produto_id': self.p2, 'quantidade': 1}, {'produto_id': self.p1, 'quantidade': 99999}], 'Limpeza')
        self.assertEqual(g.consultar('SELECT COUNT(*) n FROM consumo_interno')[0]['n'], 0)
        self.assertEqual(op.obter_produto(self.p2)['quantidade_estoque'], 100)


class DefeitosReformulacaoTest(BaseTemp):
    """Regressões dos defeitos identificados na análise de reformulação."""

    def setUp(self):
        super().setUp()
        g.abrir_caixa(0)
        g.salvar_politica(None, 500, 30, 0, 0)
        self.hoje = date.today().isoformat()

    def test_d1_custo_desconhecido_marca_parcial(self):
        p = op.criar_produto('BONIF', preco_custo=0, preco_venda=10, quantidade_estoque=10)
        op.registrar_venda([{'produto_id': p, 'quantidade': 1}], 'dinheiro')
        r = g.resultado_gerencial(self.hoje, self.hoje)
        self.assertTrue(r['parcial'], 'custo desconhecido deve marcar resultado parcial')
        self.assertTrue(any('venda' in x.lower() for x in r['pendencias']))
        # Produto com custo conhecido entra no CMV normalmente.
        p2 = op.criar_produto('OK', preco_custo=6, preco_venda=10, quantidade_estoque=10)
        op.registrar_venda([{'produto_id': p2, 'quantidade': 1}], 'dinheiro')
        self.assertEqual(g.resultado_gerencial(self.hoje, self.hoje)['cmv'], 6)

    def test_d2_taxas_total_igual_detalhe(self):
        p = op.criar_produto('CARD', preco_custo=5, preco_venda=10, quantidade_estoque=100)
        op.registrar_venda([{'produto_id': p, 'quantidade': 10}], 'cartao_debito', taxa_paga=0)
        rec = g.consultar("SELECT id FROM recebiveis_cartao WHERE origem='venda'")[0]['id']
        g.liquidar_cartao(rec, conta_id=2, taxa=1.0)
        total = g.resultado_gerencial(self.hoje, self.hoje)['taxas']
        detalhe = g.componentes_taxas(self.hoje, self.hoje)
        self.assertEqual(total, 1.0)
        self.assertAlmostEqual(sum(i['valor'] for i in detalhe), total, 2)
        self.assertEqual(g.lancamentos_componente('taxas', self.hoje, self.hoje), detalhe)

    def test_d3_retirada_familiar_unificada(self):
        p = op.criar_produto('P', preco_custo=5, preco_venda=8, quantidade_estoque=100)
        op.registrar_consumo_interno([{'produto_id': p, 'quantidade': 4}], 'Limpeza', finalidade='operacional')
        op.registrar_consumo_interno([{'produto_id': p, 'quantidade': 8}], 'Consumo pessoal/família', finalidade='pessoal')
        rf = g.resumo_financeiro(self.hoje, self.hoje)
        rg = g.resultado_gerencial(self.hoje, self.hoje)
        self.assertEqual(rf['resultado'], rg['resultado_liquido'])
        self.assertEqual(rf['retiradas_pessoais'], 40)
        self.assertEqual(rf['resultado_apos_retiradas'], rg['resultado_apos_retiradas'])
        self.assertEqual(rg['consumo_operacional'], 20)  # pessoal NÃO entra no operacional

    def test_d4_finalidade_estavel_independe_do_texto(self):
        p = op.criar_produto('P4', preco_custo=1, preco_venda=2, quantidade_estoque=100)
        op.registrar_consumo_interno([{'produto_id': p, 'quantidade': 3}], 'Texto livre qualquer', finalidade='equipe')
        r = g.resultado_gerencial(self.hoje, self.hoje)
        self.assertEqual(r['consumo_equipe'], 3)
        self.assertEqual(r['consumo_outro'], 0)

    def test_d5_chave_repetida_conteudo_diferente_conflito(self):
        p = op.criar_produto('P5', preco_custo=1, preco_venda=2, quantidade_estoque=100)
        op.registrar_consumo_interno([{'produto_id': p, 'quantidade': 5}], 'Limpeza', chave='K')
        # repetição idêntica é segura
        op.registrar_consumo_interno([{'produto_id': p, 'quantidade': 5}], 'Limpeza', chave='K')
        self.assertEqual(op.obter_produto(p)['quantidade_estoque'], 95)
        with self.assertRaises(op.ErroOperacao):
            op.registrar_consumo_interno([{'produto_id': p, 'quantidade': 9}], 'Limpeza', chave='K')
        # venda com chave repetida e itens diferentes
        op.registrar_venda([{'produto_id': p, 'quantidade': 1}], 'dinheiro', chave_operacao='V1')
        with self.assertRaises(op.ErroOperacao):
            op.registrar_venda([{'produto_id': p, 'quantidade': 2}], 'dinheiro', chave_operacao='V1')

    def test_todos_componentes_reconciliam(self):
        p = op.criar_produto('RECON', preco_custo=6, preco_venda=10, quantidade_estoque=1000)
        op.registrar_venda([{'produto_id': p, 'quantidade': 100}], 'cartao_debito', taxa_paga=10)
        rec = g.consultar("SELECT id FROM recebiveis_cartao WHERE origem='venda'")[0]['id']
        g.liquidar_cartao(rec, conta_id=2, taxa=10.0)
        op.registrar_consumo_interno([{'produto_id': p, 'quantidade': 4}], 'Limpeza', finalidade='operacional')
        op.registrar_consumo_interno([{'produto_id': p, 'quantidade': 2}], 'Lanches', finalidade='equipe')
        op.registrar_consumo_interno([{'produto_id': p, 'quantidade': 8}], 'Família', finalidade='pessoal')
        op.registrar_perda([{'produto_id': p, 'quantidade': 3}], 'Quebra/avaria')
        g.criar_conta_pagar('Credor', 'Aluguel', 100, self.hoje, categoria='Aluguel', competencia=self.hoje)
        with g.transacao() as c:
            g.movimento(c, 1, 500, 'Outras receitas', 'Venda de sucata', 'manual', 'r1', data=self.hoje)
        with g.transacao() as c:
            g.movimento(c, 1, -200, 'Outras despesas', 'Frete', 'manual', 'd1', data=self.hoje)
        r = g.resultado_gerencial(self.hoje, self.hoje)
        mapa = {'vendas': 'vendas_liquidas', 'cmv': 'cmv', 'taxas': 'taxas', 'perdas': 'perdas',
                'consumo_operacional': 'consumo_operacional', 'consumo_equipe': 'consumo_equipe',
                'consumo_outro': 'consumo_outro', 'retiradas_pessoais': 'retiradas_pessoais',
                'despesas_competencia': 'despesas_competencia', 'outras_receitas': 'outras_receitas',
                'outras_despesas': 'outras_despesas'}
        for comp, chave in mapa.items():
            det = g.lancamentos_componente(comp, self.hoje, self.hoje)
            self.assertAlmostEqual(sum(d['valor'] for d in det), r[chave], 2,
                                   msg=f'componente {comp}: detalhe != total')

    def test_estorno_producao_preserva_movimentacoes_posteriores(self):
        # Produzir -> comprar mais insumo (outro custo) -> consumir -> estornar.
        insumo = op.criar_produto('INS-POST', preco_custo=2, preco_venda=3, quantidade_estoque=100)
        final = op.criar_produto('FIM-POST', preco_custo=0, preco_venda=10, quantidade_estoque=0)
        rid = prod.criar_receita(final, rendimento=10, itens=[{'insumo_id': insumo, 'quantidade': 10}])
        pr = g.registrar_producao(rid, 1, validade=(date.today() + timedelta(days=30)).isoformat())
        # compra posterior (20 x 5) e consumo posterior (30)
        g.receber_compra([{'produto_id': insumo, 'quantidade': 20, 'custo': 5.0}], 'Forn', 'DOC-POST',
                         (date.today() + timedelta(days=30)).isoformat())
        op.registrar_consumo_interno([{'produto_id': insumo, 'quantidade': 30}], 'Limpeza', finalidade='operacional')
        # estado antes do estorno: qtd 80, custo (90*2+20*5)/110
        custo_meio = (90 * 2 + 20 * 5) / 110
        self.assertAlmostEqual(op.obter_produto(insumo)['quantidade_estoque'], 80, 3)
        g.estornar_producao(pr['id'], 'engano')
        p = op.obter_produto(insumo)
        # todas as movimentações posteriores preservadas: 100 -10 +20 -30 +10 = 90
        self.assertAlmostEqual(p['quantidade_estoque'], 90, 3)
        # valorização compensatória: devolve 10 pelo custo histórico (2)
        self.assertAlmostEqual(p['preco_custo'], (80 * custo_meio + 10 * 2) / 90, 4)
        self.assertAlmostEqual(op.obter_produto(final)['quantidade_estoque'], 0, 3)

    def test_estorno_producao_antiga_sem_snapshot(self):
        # Produção antiga sem as colunas de snapshot: reverte compensatoriamente
        # (usa o custo histórico gravado), sem inventar estado anterior.
        insumo = op.criar_produto('INS-OLD', preco_custo=2, preco_venda=3, quantidade_estoque=100)
        final = op.criar_produto('FIM-OLD', preco_custo=0, preco_venda=10, quantidade_estoque=0)
        rid = prod.criar_receita(final, rendimento=10, itens=[{'insumo_id': insumo, 'quantidade': 10}])
        pr = g.registrar_producao(rid, 1, validade=(date.today() + timedelta(days=30)).isoformat())
        with g.transacao() as c:
            c.execute('UPDATE producoes SET estoque_anterior_produto=NULL,custo_anterior_produto=NULL WHERE id=?', (pr['id'],))
            c.execute('UPDATE insumos_producao SET estoque_anterior_insumo=NULL,custo_anterior_insumo=NULL WHERE producao_id=?', (pr['id'],))
        g.estornar_producao(pr['id'], 'produção antiga')
        self.assertAlmostEqual(op.obter_produto(final)['quantidade_estoque'], 0, 3)
        self.assertAlmostEqual(op.obter_produto(insumo)['quantidade_estoque'], 100, 3)

    def test_estorno_producao_bloqueia_ajuste_posterior(self):
        insumo = op.criar_produto('INS-AJ', preco_custo=2, preco_venda=3, quantidade_estoque=100)
        final = op.criar_produto('FIM-AJ', preco_custo=0, preco_venda=10, quantidade_estoque=0)
        rid = prod.criar_receita(final, rendimento=10, itens=[{'insumo_id': insumo, 'quantidade': 10}])
        pr = g.registrar_producao(rid, 1, validade=(date.today() + timedelta(days=30)).isoformat())
        g.ajustar_estoque(final, 25, 'ajuste', 'Inventário conferido',
                          validade=(date.today() + timedelta(days=10)).isoformat())  # movimentação posterior
        with self.assertRaises(g.ErroGestao):
            g.estornar_producao(pr['id'], 'engano')

    def test_d6_estorno_producao_com_dependencia(self):
        insumo = op.criar_produto('INS', preco_custo=2, preco_venda=3, quantidade_estoque=100)
        final = op.criar_produto('FIM', preco_custo=0, preco_venda=10, quantidade_estoque=0)
        rid = prod.criar_receita(final, rendimento=10, itens=[{'insumo_id': insumo, 'quantidade': 10}])
        pr = g.registrar_producao(rid, 1, validade=(date.today() + timedelta(days=30)).isoformat())
        # usa o produto acabado depois -> não pode reverter
        op.registrar_venda([{'produto_id': final, 'quantidade': 1}], 'dinheiro')
        with self.assertRaises(g.ErroGestao):
            g.estornar_producao(pr['id'], 'engano')
        # sem uso posterior, reverte: insumos voltam, produto acabado sai
        insumo2 = op.criar_produto('INS2', preco_custo=2, preco_venda=3, quantidade_estoque=100)
        final2 = op.criar_produto('FIM2', preco_custo=0, preco_venda=10, quantidade_estoque=0)
        rid2 = prod.criar_receita(final2, rendimento=10, itens=[{'insumo_id': insumo2, 'quantidade': 10}])
        pr2 = g.registrar_producao(rid2, 1, validade=(date.today() + timedelta(days=30)).isoformat())
        self.assertEqual(op.obter_produto(final2)['quantidade_estoque'], 10)
        self.assertEqual(op.obter_produto(insumo2)['quantidade_estoque'], 90)
        g.estornar_producao(pr2['id'], 'lançado por engano')
        self.assertEqual(op.obter_produto(final2)['quantidade_estoque'], 0)
        self.assertEqual(op.obter_produto(insumo2)['quantidade_estoque'], 100)
        with self.assertRaises(g.ErroGestao):
            g.estornar_producao(pr2['id'], 'de novo')  # duplicado


class CompatibilidadeTest(BaseTemp):
    def test_banco_mais_novo_bloqueia(self):
        conn = db.get_conn()
        try:
            conn.execute("INSERT OR REPLACE INTO schema_meta(chave,valor) VALUES('versao',?)", (str(db.SCHEMA_VERSAO + 1),))
            conn.commit()
        finally:
            conn.close()
        ok, msg = db.compativel()
        self.assertFalse(ok)
        self.assertIn('mais nova', msg)

    def test_banco_igual_ou_antigo_ok(self):
        self.assertTrue(db.compativel()[0])
        conn = db.get_conn()
        try:
            conn.execute("INSERT OR REPLACE INTO schema_meta(chave,valor) VALUES('versao','0')")
            conn.commit()
        finally:
            conn.close()
        self.assertTrue(db.compativel()[0])  # mais antigo é seguro (migração aditiva)


class BalancaTest(unittest.TestCase):
    def test_protocolos_toledo_8217(self):
        from balanca import LeitorBalanca as L
        p = L._parsear_toledo_pacote
        # P05A: 5 dígitos sem ponto (2 inteiros + 3 decimais)
        self.assertEqual(p(b'\x02' + b'15000' + b'\x03'), 15.0)
        self.assertEqual(p(b'\x02' + b'00500' + b'\x03'), 0.5)
        # Instável / negativo / acima não viram peso
        self.assertIsNone(p(b'\x02' + b'IIIII' + b'\x03'))
        self.assertIsNone(p(b'\x02' + b'NNNNN' + b'\x03'))
        self.assertIsNone(p(b'\x02' + b'SSSSS' + b'\x03'))
        # P05B: S + PPDPPP (com ponto decimal)
        self.assertEqual(p(b'\x02' + b' 00.185' + b'\x03'), 0.185)
        self.assertEqual(p(b'\x02' + b'-00.185' + b'\x03'), -0.185)
        # P05B com tara: usa o peso líquido (primeiro número)
        self.assertEqual(p(b'\x02' + b' 00.185 01.000' + b'\x03'), 0.185)
        # P06: 6 caracteres + CR
        self.assertEqual(p(b'\x02' + b'00.185' + b'\r'), 0.185)

    def test_frame_fragmentado(self):
        from balanca import LeitorBalanca as L
        b = L()
        for parte in (b'\x02', b'15', b'000', b'\x03'):
            b._processar_bytes(parte)
        self.assertEqual(b.peso_atual(), 15.0)

    def test_peso_negativo_nao_vira_saldo(self):
        from balanca import LeitorBalanca as L
        b = L()
        b._processar_bytes(b'\x02' + b'-00.500' + b'\x03')
        self.assertEqual(b.peso_atual(), 0.0)

    def test_perfis_tem_baud_e_paridade(self):
        from balanca import LeitorBalanca as L
        self.assertEqual(L.PROTOCOLOS['P05A (Toledo 8217)']['baudrate'], 2400)
        self.assertIn('P05B (Toledo 8217)', L.PROTOCOLOS)
        self.assertIn('P06 (Toledo 8217)', L.PROTOCOLOS)


class ArredondamentoTest(BaseTemp):
    def test_total_kg_bate_com_backend(self):
        g.abrir_caixa(0)
        pid = op.criar_produto('BACON KG', unidade='KG', preco_custo=30,
                               preco_venda=45.0, quantidade_estoque=10)
        # 0,185 kg × R$ 45,00 = 8,325 → arredonda item a item para 8,33
        bruto_c = g.centavos_itens([{'preco_unitario': 45.0, 'quantidade': 0.185}])
        self.assertEqual(bruto_c, 833)
        venda = op.registrar_venda([{'produto_id': pid, 'quantidade': 0.185}],
                                   'dinheiro', total_esperado=bruto_c / 100)
        self.assertEqual(venda['valor_total'], 8.33)
        # O valor "antigo" (tela com ponto flutuante) não pode mais passar.
        with self.assertRaises(op.ErroOperacao):
            op.registrar_venda([{'produto_id': pid, 'quantidade': 0.185}],
                               'dinheiro', total_esperado=8.32)


class VendaDivididaTest(BaseTemp):
    def setUp(self):
        super().setUp()
        g.abrir_caixa(0)
        self.pid = op.criar_produto('PRODUTO X', preco_custo=2, preco_venda=10,
                                    quantidade_estoque=20)

    def test_pagamento_dividido_registra_partes(self):
        venda = op.registrar_venda([{'produto_id': self.pid, 'quantidade': 2}],
                                   pagamentos=[{'forma': 'dinheiro', 'valor': 10},
                                               {'forma': 'pix', 'valor': 10}])
        self.assertEqual(venda['valor_total'], 20)
        det = op.detalhar_venda(venda['id'])
        self.assertEqual(det['forma_pagamento'], 'misto')
        formas = {p['forma']: p['valor'] for p in det['pagamentos']}
        self.assertEqual(formas, {'dinheiro': 10.0, 'pix': 10.0})

    def test_pagamento_dividido_soma_errada_bloqueia(self):
        with self.assertRaises(op.ErroOperacao):
            op.registrar_venda([{'produto_id': self.pid, 'quantidade': 2}],
                               pagamentos=[{'forma': 'dinheiro', 'valor': 5},
                                           {'forma': 'pix', 'valor': 5}])
        self.assertEqual(g.consultar('SELECT COUNT(*) n FROM vendas')[0]['n'], 0)


class CancelamentoTest(BaseTemp):
    def test_cancelar_restaura_estoque_e_estorna_caixa(self):
        g.abrir_caixa(0)
        pid = op.criar_produto('PRODUTO Y', preco_custo=2, preco_venda=10,
                               quantidade_estoque=20)
        venda = op.registrar_venda([{'produto_id': pid, 'quantidade': 3}], 'dinheiro')
        self.assertEqual(op.obter_produto(pid)['quantidade_estoque'], 17)
        g.cancelar_venda(venda['id'], 'Cliente desistiu')
        self.assertEqual(op.obter_produto(pid)['quantidade_estoque'], 20)
        # O caixa volta ao valor de abertura (0) — a entrada foi estornada.
        saldo = next(r['saldo_centavos'] for r in g.contas_saldos() if r['id'] == 1)
        self.assertEqual(saldo, 0)


class PlanilhaImportTest(BaseTemp):
    def _planilha(self, linhas):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Mercearia'
        ws.append(['DESCRIÇÃO', 'PREÇO', 'UNIDADE', 'EAN'])
        for nome, preco, unidade, ean in linhas:
            ws.append([nome, preco, unidade, ean])
        caminho = Path(self.temp.name) / 'planilha.xlsx'
        wb.save(caminho)
        return str(caminho)

    def test_preview_e_aplicar_com_transacao(self):
        import importar_planilha as iplan
        caminho = self._planilha([
            ('ARROZ', 8.0, 'UN', '7891234567895'),
            ('FEIJAO', 6.0, 'UN', '7891234567802'),
        ])
        plano = iplan.pre_visualizar(caminho)
        self.assertEqual(plano['inseridos_previstos'], 2)
        # Nada gravado na pré-visualização.
        self.assertEqual(g.consultar("SELECT COUNT(*) n FROM produtos WHERE nome IN ('ARROZ','FEIJAO')")[0]['n'], 0)
        r = iplan.aplicar(caminho, plano)
        self.assertEqual(r['inseridos'], 2)
        self.assertEqual(op.obter_produto(op.buscar_por_codigo('7891234567895')['id'])['preco_venda'], 8.0)
        # Reimportar atualiza, não duplica.
        plano2 = iplan.pre_visualizar(caminho)
        self.assertEqual(plano2['atualizados_previstos'], 2)
        iplan.aplicar(caminho, plano2)
        self.assertEqual(g.consultar("SELECT COUNT(*) n FROM produtos WHERE nome='ARROZ'")[0]['n'], 1)

    def test_preco_negativo_rejeitado(self):
        import importar_planilha as iplan
        caminho = self._planilha([('PRODUTO RUIM', -5.0, 'UN', '7891234567895')])
        plano = iplan.pre_visualizar(caminho)
        self.assertEqual(plano['inseridos_previstos'], 0)
        self.assertTrue(any('negativo' in i['motivo'] for i in plano['ignorados']))


class NfeImportTest(BaseTemp):
    def setUp(self):
        super().setUp()
        g.abrir_caixa(0)
        self.arroz = op.criar_produto('ARROZ TESTE', codigo_barras='7891234567895',
                                      preco_custo=5, preco_venda=8, quantidade_estoque=0)
        self.iog = op.criar_produto('IOGURTE TESTE', codigo_barras='7891234567802',
                                    preco_custo=4, preco_venda=7, quantidade_estoque=0)
        conn = db.get_conn()
        try:
            conn.execute('UPDATE produtos SET perecivel=1 WHERE id=?', (self.iog,))
            conn.commit()
        finally:
            conn.close()
        self.arq = Path(self.temp.name) / 'nota.xml'
        self.arq.write_text(XML_NFE, encoding='utf-8')

    def test_nao_inventa_validade_nem_vencimento(self):
        plano = nfe.pre_visualizar(str(self.arq))
        nota = plano['notas'][0]
        self.assertIsNone(nota['vencimento'])
        self.assertIsNone(nota['forma'])
        self.assertTrue(plano['precisa_vencimento'])
        self.assertTrue(plano['tem_perecivel'])

    def test_bloqueia_sem_dados_obrigatorios(self):
        plano = nfe.pre_visualizar(str(self.arq))
        with self.assertRaises(ValueError):
            nfe.aplicar(str(self.arq), plano)
        # Nada foi gravado.
        self.assertEqual(op.obter_produto(self.arroz)['quantidade_estoque'], 0)
        self.assertEqual(g.consultar('SELECT COUNT(*) n FROM compras_estoque')[0]['n'], 0)

    def test_aplica_com_dados_e_nao_duplica(self):
        plano = nfe.pre_visualizar(str(self.arq))
        nfe.aplicar(str(self.arq), plano, vencimento_padrao='2026-11-15',
                    forma_padrao='A prazo', validade_padrao='2026-12-01')
        self.assertEqual(op.obter_produto(self.arroz)['quantidade_estoque'], 10)
        self.assertEqual(op.obter_produto(self.iog)['quantidade_estoque'], 6)
        lotes = g.consultar('SELECT data_validade FROM lotes_validade WHERE produto_id=?', (self.iog,))
        self.assertEqual(lotes[0]['data_validade'], '2026-12-01')
        # Reimportação: detecta duplicata e não duplica estoque.
        plano2 = nfe.pre_visualizar(str(self.arq))
        self.assertTrue(plano2['notas'][0]['duplicada'])
        nfe.aplicar(str(self.arq), plano2, vencimento_padrao='2026-11-15',
                    forma_padrao='A prazo', validade_padrao='2026-12-01')
        self.assertEqual(op.obter_produto(self.arroz)['quantidade_estoque'], 10)

    def test_falha_nao_deixa_produto_orfao(self):
        # Já existe uma conta com o mesmo documento: a compra falha depois de
        # o produto novo ser cadastrado; o cadastro órfão deve ser removido.
        g.criar_conta_pagar('FORNECEDOR TESTE LTDA', 'Compra', 10, '2026-11-15',
                            documento='1234')
        plano = nfe.pre_visualizar(str(self.arq))
        self.assertEqual(plano['itens'][0]['acao'], 'atualizar')  # arroz já existe
        # Força um produto novo: uma nota com EAN inédito.
        novo = XML_NFE.replace('7891234567895', '7891234567895').replace(
            'ARROZ TESTE', 'PRODUTO NOVO TESTE').replace(
            '<cEAN>7891234567895</cEAN>', '<cEAN>7890000000000</cEAN>')
        arq2 = Path(self.temp.name) / 'nota2.xml'
        arq2.write_text(novo, encoding='utf-8')
        plano2 = nfe.pre_visualizar(str(arq2))
        nfe.aplicar(str(arq2), plano2, vencimento_padrao='2026-11-15',
                    forma_padrao='A prazo', validade_padrao='2026-12-01')
        # O produto novo não pode ter ficado cadastrado sem estoque/uso.
        self.assertFalse(g.consultar("SELECT 1 FROM produtos WHERE nome='PRODUTO NOVO TESTE'"))


class BackupTest(BaseTemp):
    def test_backup_integro_e_retencao(self):
        g.criar_usuario('admin', 'senha1234', 'gerente')
        self.assertTrue(g.autenticar('admin', 'senha1234'))
        pasta = Path(self.temp.name) / 'backups'
        pasta.mkdir()
        original_dir = bk.BACKUP_DIR
        bk.BACKUP_DIR = str(pasta)
        try:
            # Cria backups antigos simulados.
            for dia in ('2020-01-01', '2020-01-02', '2020-01-03'):
                (pasta / f'mercadinho_{dia}.db').write_bytes(b'x')
            destino, novo = bk.backup_diario()
            self.assertTrue(novo)
            self.assertTrue(os.path.exists(destino))
            conn = sqlite3.connect(destino)
            try:
                self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            finally:
                conn.close()
            restantes = sorted(n for n in os.listdir(pasta) if n.startswith('mercadinho_'))
            self.assertLessEqual(len(restantes), bk.retencao_backups())
        finally:
            bk.BACKUP_DIR = original_dir

    def test_restaurar_backup_guarda_copia(self):
        g.criar_usuario('admin', 'senha1234', 'gerente')
        self.assertTrue(g.autenticar('admin', 'senha1234'))
        pasta = Path(self.temp.name) / 'backups'
        pasta.mkdir()
        original_dir = bk.BACKUP_DIR
        bk.BACKUP_DIR = str(pasta)
        try:
            op.criar_produto('PRODUTO ANTES', preco_custo=1, preco_venda=2, quantidade_estoque=5)
            # Backup do estado atual.
            destino, _ = bk.backup_diario()
            # Muda o banco depois do backup.
            op.criar_produto('PRODUTO DEPOIS', preco_custo=1, preco_venda=2, quantidade_estoque=5)
            self.assertTrue(g.consultar("SELECT 1 FROM produtos WHERE nome='PRODUTO DEPOIS'"))
            # Restaura: o produto posterior some, e uma cópia de segurança é guardada.
            seguranca = bk.restaurar_backup(destino)
            self.assertTrue(os.path.exists(seguranca))
            self.assertFalse(g.consultar("SELECT 1 FROM produtos WHERE nome='PRODUTO DEPOIS'"))
            self.assertTrue(g.consultar("SELECT 1 FROM produtos WHERE nome='PRODUTO ANTES'"))
        finally:
            bk.BACKUP_DIR = original_dir


if __name__ == '__main__':
    unittest.main()
