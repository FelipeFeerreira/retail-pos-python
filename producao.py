"""
producao.py

Produção própria: quando o mercadinho compra farinha, óleo etc. (insumos —
produtos como qualquer outro, comprados juntos ou separados) e usa pra fazer
um item que vira estoque de verdade (pão, bolo, salgado...), esse módulo
registra a "receita" (quanto de cada insumo o produto final leva) e, cada
vez que uma produção acontece, dá baixa nos insumos e entrada no produto
final — automático, sem precisar lançar cada ingrediente à mão toda vez.

Fluxo:
  1. Cadastra farinha, óleo etc. como produto normal (entram pela "entrada
     de mercadoria" de sempre, com o custo de compra).
  2. Cria uma receita pro item que é produzido (ex.: "Pão Caseiro"): quantas
     unidades a receita rende, e quanto de cada insumo ela usa.
  3. Toda vez que produzir, registra "fiz 1x a receita" (ou 2x, 0.5x etc.) —
     o sistema desconta os insumos do estoque, calcula o custo do lote pelo
     preço de custo atual de cada insumo, e dá entrada no produto final já
     com esse custo por unidade (fazendo média ponderada com o estoque que
     já existia, se houver).
"""
from __future__ import annotations

import database as db
import validade as val

try:
    import operacoes as op
except ImportError:  # evita import circular em alguns cenários de teste
    op = None


class ErroProducao(Exception):
    pass


def criar_receita(produto_id, rendimento, itens, observacao=''):
    """itens: lista de {'insumo_id':.., 'quantidade':..} — quanto de cada
    insumo a receita usa PARA RENDER 'rendimento' unidades do produto final."""
    import gestao as g
    g.permitir('estoque')
    rendimento = round(float(rendimento), 3)
    if rendimento <= 0:
        raise ErroProducao('O rendimento da receita precisa ser maior que zero.')
    if not itens:
        raise ErroProducao('A receita precisa ter ao menos um insumo.')
    conn = db.get_conn()
    try:
        p = conn.execute('SELECT id FROM produtos WHERE id = ?', (produto_id,)).fetchone()
        if not p:
            raise ErroProducao('Produto final não encontrado.')
        existente = conn.execute('SELECT id FROM receitas WHERE produto_id = ?', (produto_id,)).fetchone()
        if existente:
            raise ErroProducao('Esse produto já tem uma receita — edite a existente em vez de criar outra.')
        for it in itens:
            qtd = float(it.get('quantidade') or 0)
            if qtd <= 0:
                raise ErroProducao('Quantidade de insumo inválida.')
            if it['insumo_id'] == produto_id:
                raise ErroProducao('Um produto não pode ser insumo de si mesmo.')
        cur = conn.execute(
            'INSERT INTO receitas (produto_id, rendimento, observacao) VALUES (?, ?, ?)',
            (produto_id, rendimento, observacao or ''))
        receita_id = cur.lastrowid
        for it in itens:
            conn.execute(
                'INSERT INTO receita_itens (receita_id, insumo_id, quantidade) VALUES (?, ?, ?)',
                (receita_id, it['insumo_id'], round(float(it['quantidade']), 4)))
        conn.commit()
        return receita_id
    finally:
        conn.close()


def atualizar_receita(receita_id, rendimento=None, itens=None, observacao=None):
    """Substitui o rendimento/observação e, se 'itens' for passado, apaga os
    insumos antigos e grava a lista nova (mais simples e seguro do que
    tentar casar item por item)."""
    import gestao as _gestao
    _gestao.permitir('estoque')
    conn = db.get_conn()
    try:
        r = conn.execute('SELECT * FROM receitas WHERE id = ?', (receita_id,)).fetchone()
        if not r:
            raise ErroProducao('Receita não encontrada.')
        novo_rend = round(float(rendimento), 3) if rendimento is not None else r['rendimento']
        if novo_rend <= 0:
            raise ErroProducao('O rendimento precisa ser maior que zero.')
        nova_obs = observacao if observacao is not None else r['observacao']
        conn.execute('UPDATE receitas SET rendimento = ?, observacao = ? WHERE id = ?',
                     (novo_rend, nova_obs, receita_id))
        if itens is not None:
            if any(it['insumo_id']==r['produto_id'] for it in itens):
                raise ErroProducao('Produto final não pode ser insumo de si mesmo.')
            if not itens:
                raise ErroProducao('A receita precisa ter ao menos um insumo.')
            conn.execute('DELETE FROM receita_itens WHERE receita_id = ?', (receita_id,))
            for it in itens:
                qtd = float(it.get('quantidade') or 0)
                if qtd <= 0:
                    raise ErroProducao('Quantidade de insumo inválida.')
                conn.execute(
                    'INSERT INTO receita_itens (receita_id, insumo_id, quantidade) VALUES (?, ?, ?)',
                    (receita_id, it['insumo_id'], round(qtd, 4)))
        conn.commit()
    finally:
        conn.close()


def desativar_receita(receita_id):
    import gestao as _gestao
    _gestao.permitir('estoque')
    conn = db.get_conn()
    try:
        conn.execute('UPDATE receitas SET ativo = 0 WHERE id = ?', (receita_id,))
        conn.commit()
    finally:
        conn.close()


def listar_receitas(somente_ativas=True):
    conn = db.get_conn()
    try:
        sql = '''SELECT r.id, r.produto_id, r.rendimento, r.observacao, r.ativo, p.nome, p.unidade
                  FROM receitas r JOIN produtos p ON p.id = r.produto_id'''
        if somente_ativas:
            sql += ' WHERE r.ativo = 1'
        sql += ' ORDER BY p.nome'
        receitas = [dict(x) for x in conn.execute(sql).fetchall()]
        for r in receitas:
            itens = conn.execute(
                '''SELECT ri.insumo_id, ri.quantidade, p.nome, p.unidade, p.preco_custo
                   FROM receita_itens ri JOIN produtos p ON p.id = ri.insumo_id
                   WHERE ri.receita_id = ? ORDER BY p.nome''', (r['id'],)).fetchall()
            r['itens'] = [dict(i) for i in itens]
        return receitas
    finally:
        conn.close()


def obter_receita(receita_id):
    todas = listar_receitas(somente_ativas=False)
    return next((r for r in todas if r['id'] == receita_id), None)


def calcular_custo_receita(receita_id):
    """Custo dos insumos PARA UMA VEZ a receita (multiplicador=1), pelo preço
    de custo atual de cada insumo."""
    receita = obter_receita(receita_id)
    if not receita:
        raise ErroProducao('Receita não encontrada.')
    custo = sum(item['quantidade'] * (item['preco_custo'] or 0) for item in receita['itens'])
    return round(custo, 4)


def registrar_producao(receita_id,multiplicador,observacao='',**kwargs):
    import gestao as g
    try:
        return g.registrar_producao(receita_id,multiplicador,observacao,**kwargs)
    except g.ErroGestao as exc:
        raise ErroProducao(str(exc)) from exc


def listar_producoes(limite=200):
    conn = db.get_conn()
    try:
        rows = conn.execute(
            '''SELECT pr.*, p.nome produto_nome, p.unidade
               FROM producoes pr JOIN receitas r ON r.id = pr.receita_id JOIN produtos p ON p.id = r.produto_id
               ORDER BY pr.data_hora DESC LIMIT ?''', (limite,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def relatorio_diario_produto(produto_id, ano, mes):
    """Dia a dia de um único mês: quanto desse produto foi produzido (aba
    Produção), vendido (Caixa), perdido (aba Perdas) e consumido internamente
    — pensado pro pão (ou qualquer produto feito e vendido no mesmo dia):
    'fizemos 125, vendemos 120' fica visível por dia do mês, não só o total.

    'saldo' aqui é o MOVIMENTO LÍQUIDO do dia (produzido - vendido - perdido
    - consumido), NÃO o estoque físico final: compras, entradas por ajuste,
    devoluções de venda cancelada e o saldo inicial do dia não entram nessa
    conta. Vendas canceladas não contam como vendido. Para o estoque real,
    consulte produtos.quantidade_estoque e as movimentações de estoque."""
    conn = db.get_conn()
    try:
        produto = conn.execute('SELECT id, nome, unidade FROM produtos WHERE id = ?', (produto_id,)).fetchone()
        if not produto:
            raise ErroProducao('Produto não encontrado.')
        prefixo = f'{int(ano):04d}-{int(mes):02d}'

        def _por_dia(sql, chave):
            linhas = conn.execute(sql, (produto_id, prefixo)).fetchall()
            for row in linhas:
                mapa.setdefault(row['dia'], {'produzido': 0.0, 'vendido': 0.0, 'perdido': 0.0, 'consumido': 0.0})[chave] = row['qtd']

        mapa = {}
        _por_dia(
            '''SELECT date(pr.data_hora) AS dia, COALESCE(SUM(pr.quantidade_produzida), 0) AS qtd
               FROM producoes pr JOIN receitas r ON r.id = pr.receita_id
               WHERE r.produto_id = ? AND substr(pr.data_hora, 1, 7) = ?
               GROUP BY date(pr.data_hora)''', 'produzido')
        _por_dia(
            '''SELECT date(v.data_hora) AS dia, COALESCE(SUM(iv.quantidade), 0) AS qtd
               FROM itens_venda iv JOIN vendas v ON v.id = iv.venda_id
               WHERE iv.produto_id = ? AND substr(v.data_hora, 1, 7) = ? AND v.cancelada = 0
               GROUP BY date(v.data_hora)''', 'vendido')
        _por_dia(
            '''SELECT date(pe.data_hora) AS dia, COALESCE(SUM(ip.quantidade), 0) AS qtd
               FROM itens_perda ip JOIN perdas pe ON pe.id = ip.perda_id
               WHERE ip.produto_id = ? AND substr(pe.data_hora, 1, 7) = ?
               GROUP BY date(pe.data_hora)''', 'perdido')
        _por_dia(
            '''SELECT date(ci.data_hora) AS dia, COALESCE(SUM(ici.quantidade), 0) AS qtd
               FROM itens_consumo_interno ici JOIN consumo_interno ci ON ci.id = ici.consumo_id
               WHERE ici.produto_id = ? AND substr(ci.data_hora, 1, 7) = ?
               GROUP BY date(ci.data_hora)''', 'consumido')

        linhas = []
        for dia in sorted(mapa.keys()):
            v = mapa[dia]
            saldo = round(v['produzido'] - v['vendido'] - v['perdido'] - v['consumido'], 3)
            linhas.append({
                'data': dia, 'produzido': round(v['produzido'], 3), 'vendido': round(v['vendido'], 3),
                'perdido': round(v['perdido'], 3), 'consumido': round(v['consumido'], 3), 'saldo': saldo,
            })
        totais = {
            chave: round(sum(l[chave] for l in linhas), 3)
            for chave in ('produzido', 'vendido', 'perdido', 'consumido')
        }
        totais['saldo'] = round(totais['produzido'] - totais['vendido'] - totais['perdido'] - totais['consumido'], 3)
        return {
            'produto_id': produto['id'], 'produto_nome': produto['nome'], 'unidade': produto['unidade'],
            'linhas': linhas, 'totais': totais,
        }
    finally:
        conn.close()


def detalhar_producao(producao_id):
    """Detalhe de uma produção específica — reconstrói os insumos usados a
    partir da receita (a receita pode ter mudado depois, então isso é uma
    aproximação pelo estado atual, suficiente pra conferência)."""
    conn = db.get_conn()
    try:
        pr = conn.execute(
            '''SELECT pr.*, p.nome produto_nome, p.unidade, r.id receita_id
               FROM producoes pr JOIN receitas r ON r.id = pr.receita_id JOIN produtos p ON p.id = r.produto_id
               WHERE pr.id = ?''', (producao_id,)).fetchone()
        if not pr:
            return None
        d = dict(pr)
        salvos=conn.execute('SELECT nome,unidade,quantidade,custo_unitario FROM insumos_producao WHERE producao_id=?',(producao_id,)).fetchall()
        if salvos:
            d['insumos']=[dict(i) for i in salvos]
            return d
        d['historico_estimado']=True
        itens = conn.execute(
            '''SELECT p.nome, p.unidade, ri.quantidade
               FROM receita_itens ri JOIN produtos p ON p.id = ri.insumo_id
               WHERE ri.receita_id = ?''', (d['receita_id'],)).fetchall()
        d['insumos'] = [{'nome': i['nome'], 'unidade': i['unidade'], 'quantidade': round(i['quantidade'] * d['multiplicador'], 4)} for i in itens]
        return d
    finally:
        conn.close()
