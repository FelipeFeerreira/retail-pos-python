"""Regressões das correções de segurança, importação NF-e, backup e trava de
instância. Sempre usa banco temporário — nunca o banco operacional."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

import database as db
import gestao as g
import operacoes as op
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
