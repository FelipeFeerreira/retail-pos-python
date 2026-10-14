"""Páginas da nova interface, por área. Cada página é um tk.Frame que usa os
serviços (gestao/operacoes/producao/analises) — sem SQL e sem regra financeira
aqui. `recarregar()` atualiza os dados."""
from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, simpledialog, ttk

from . import componentes as cp
from . import tema

import gestao as g
import operacoes as op
import producao as prod
import validade as val
import analises as an


def _C():
    return tema.cores()


def _F():
    return tema.fonte()


def _pagina(master):
    p = tk.Frame(master, bg=_C()['papel'])
    return p


class PaginaBase(tk.Frame):
    titulo = 'Página'

    def __init__(self, master, shell):
        super().__init__(master, bg=_C()['papel'])
        self.shell = shell
        self._montar()

    def _montar(self):
        raise NotImplementedError

    def recarregar(self):
        pass

    def _cabecalho(self, texto=None, com_periodo=False):
        C = _C()
        cab = tk.Frame(self, bg=C['papel'])
        cab.pack(fill='x', pady=(0, 10))
        tk.Label(cab, text=texto or self.titulo, bg=C['papel'], fg=C['verde2'],
                 font=(_F(), 20, 'bold')).pack(side='left')
        if com_periodo:
            self.periodo = cp.Periodo(cab, comando=self.recarregar)
            self.periodo.pack(side='right')
        return cab


# ---------------------------------------------------------------------------
# INÍCIO
# ---------------------------------------------------------------------------
class InicioPage(PaginaBase):
    titulo = 'Início'

    def _montar(self):
        C = _C()
        cab = tk.Frame(self, bg=C['papel']); cab.pack(fill='x', pady=(0, 10))
        tk.Label(cab, text='Início', bg=C['papel'], fg=C['verde2'], font=(_F(), 20, 'bold')).pack(side='left')
        self.periodo = cp.Periodo(cab, comando=self.recarregar)
        self.periodo.pack(side='right')
        self.aviso = tk.Label(self, text='', bg=C['papel'], fg=C['ambar'], font=(_F(), 10, 'bold'),
                              anchor='w', justify='left', wraplength=1000)
        self.aviso.pack(fill='x')

        linha1 = tk.Frame(self, bg=C['papel']); linha1.pack(fill='x', pady=(4, 8))
        self.cards = {}
        for i, (chave, titulo, destaque) in enumerate([
                ('vendas', 'Vendas', False), ('resultado', 'Resultado líquido gerencial', True),
                ('apos', 'Resultado após retiradas', False), ('dinheiro', 'Dinheiro em caixa', False),
                ('banco', 'Saldo bancário registrado', False)]):
            c = cp.Card(linha1, titulo, destaque=destaque)
            c.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else 6, 0))
            linha1.columnconfigure(i, weight=1)
            self.cards[chave] = c

        linha2 = tk.Frame(self, bg=C['papel']); linha2.pack(fill='x', pady=(0, 8))
        for i, (chave, titulo) in enumerate([
                ('vencidas', 'Contas vencidas'), ('avencer', 'Contas a vencer (7 dias)'),
                ('fiado', 'Fiado a receber'), ('cartao', 'Cartão a receber')]):
            c = cp.Card(linha2, titulo)
            c.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else 6, 0))
            linha2.columnconfigure(i, weight=1)
            self.cards[chave] = c

        tk.Label(self, text='PENDÊNCIAS', bg=C['papel'], fg=C['cinza'], font=(_F(), 9, 'bold')).pack(anchor='w', pady=(6, 2))
        self.lista_pend = cp.tabela(self, [('tipo', 'Tipo', 220, 'w'), ('detalhe', 'Detalhe', 620, 'w'),
                                           ('qtd', 'Qtd', 90, 'e')], altura=8)
        self.lista_pend.pack(fill='both', expand=True)

    def recarregar(self):
        ini, fim = self.periodo.intervalo()
        if not ini or not fim:
            hoje = date.today()
            ini, fim = hoje.replace(month=1, day=1).isoformat(), hoje.isoformat()
        res = g.resultado_gerencial(ini, fim)
        painel = g.painel_financeiro(ini, fim)
        self.cards['vendas'].definir(tema.moeda(res['vendas_liquidas']))
        self.cards['resultado'].definir(tema.moeda(res['resultado_liquido']),
                                        'parcial' if res['parcial'] else 'completo')
        self.cards['apos'].definir(tema.moeda(res['resultado_apos_retiradas']))
        self.cards['dinheiro'].definir(tema.moeda(painel['dinheiro']), 'não é lucro')
        self.cards['banco'].definir(tema.moeda(painel['banco']))
        contas = g.contas_pagar()
        vencidas = sum(r['saldo_centavos'] for r in contas if r['saldo_centavos'] and r['dias'] < 0) / 100
        avencer = sum(r['saldo_centavos'] for r in contas if r['saldo_centavos'] and 0 <= r['dias'] <= 7) / 100
        self.cards['vencidas'].definir(tema.moeda(vencidas))
        self.cards['avencer'].definir(tema.moeda(avencer))
        self.cards['fiado'].definir(tema.moeda(painel['fiado_receber']))
        self.cards['cartao'].definir(tema.moeda(painel['cartao_receber']))

        self.aviso.config(text=('⚠ RESULTADO PARCIAL: ' + '; '.join(res['pendencias'])) if res['parcial'] else '')

        # Pendências operacionais (diagnóstico rápido).
        self.lista_pend.delete(*self.lista_pend.get_children())
        diag = diagnostico()
        for i, d in enumerate(diag):
            tag = 'alerta' if d['qtd'] else 'par'
            self.lista_pend.insert('', 'end', tags=(tag,), values=(d['tipo'], d['detalhe'], d['qtd']))


# ---------------------------------------------------------------------------
# RESULTADOS
# ---------------------------------------------------------------------------
class ResultadosPage(PaginaBase):
    titulo = 'Resultados'

    def _montar(self):
        C = _C()
        cab = self._cabecalho('Resultados', com_periodo=True)
        self.aviso = tk.Label(self, text='', bg=C['papel'], fg=C['ambar'], font=(_F(), 9, 'bold'), anchor='w')
        self.aviso.pack(fill='x')
        corpo = tk.Frame(self, bg=C['papel']); corpo.pack(fill='both', expand=True)
        corpo.columnconfigure(0, weight=3); corpo.columnconfigure(1, weight=2); corpo.rowconfigure(0, weight=1)
        self.tree = cp.tabela(corpo, [('comp', 'Resultado gerencial (competência)', 360, 'w'), ('valor', 'Valor', 130, 'e')], altura=18)
        self.tree.grid(row=0, column=0, sticky='nsew')
        self.tree.bind('<Double-1>', lambda e: self._detalhar())
        self.caixa = cp.tabela(corpo, [('item', 'Caixa não é lucro', 240, 'w'), ('valor', 'Valor', 120, 'e')], altura=18)
        self.caixa.grid(row=0, column=1, sticky='nsew', padx=(8, 0))
        barra = tk.Frame(self, bg=C['papel']); barra.pack(fill='x', pady=6)
        ttk.Button(barra, text='Ver lançamentos do componente', style='Secondary.TButton', command=self._detalhar).pack(side='left')
        self._comp = {}

    def recarregar(self):
        ini, fim = self.periodo.intervalo()
        if not ini or not fim:
            hoje = date.today(); ini, fim = hoje.replace(month=1, day=1).isoformat(), hoje.isoformat()
        res = g.resultado_gerencial(ini, fim)
        painel = g.painel_financeiro(ini, fim)
        self.aviso.config(text=('⚠ RESULTADO PARCIAL: ' + '; '.join(res['pendencias'])) if res['parcial'] else '')
        self.tree.delete(*self.tree.get_children())
        self._comp = {}
        linhas = [
            ('vendas', 'Vendas líquidas de descontos e cancelamentos', res['vendas_liquidas'], ''),
            ('cmv', '(−) CMV histórico das mercadorias vendidas', -res['cmv'], ''),
            (None, f"= Margem bruta ({res['margem_pct']:.1f}%)", res['margem_bruta'], ''),
            ('taxas', '(−) Taxas de cartão e outros meios', -res['taxas'], ''),
            ('perdas', '(−) Perdas de mercadorias (custo)', -res['perdas'], ''),
            ('consumo_operacional', '(−) Consumo operacional', -res['consumo_operacional'], ''),
            ('consumo_equipe', '(−) Consumo da equipe', -res['consumo_equipe'], ''),
            ('consumo_outro', '(−) Consumo a classificar', -res['consumo_outro'], ''),
            ('despesas_competencia', '(−) Despesas da loja por competência', -res['despesas_competencia'], ''),
            ('outras_receitas', '(+) Outras receitas', res['outras_receitas'], ''),
            ('outras_despesas', '(−) Outras despesas', -res['outras_despesas'], ''),
            (None, '= RESULTADO LÍQUIDO GERENCIAL', res['resultado_liquido'], 'total'),
            ('retiradas_pessoais', '(−) Retiradas pessoais/familiares (custo)', -res['retiradas_pessoais'], 'pessoal'),
            (None, '= RESULTADO APÓS RETIRADAS', res['resultado_apos_retiradas'], 'total'),
        ]
        for i, (comp, rot, val, tag) in enumerate(linhas):
            iid = comp or f'L{i}'
            if comp:
                self._comp[iid] = comp
            self.tree.insert('', 'end', iid=iid, tags=(tag,) if tag else (), values=(rot, tema.moeda(val)))
        self.caixa.delete(*self.caixa.get_children())
        for rot, val, tag in [
                ('Dinheiro em caixa', painel['dinheiro'], 'total'),
                ('Saldo bancário registrado', painel['banco'], 'total'),
                ('Cartão a receber', painel['cartao_receber'], ''),
                ('Fiado a receber', painel['fiado_receber'], ''),
                ('Contas a pagar em aberto', painel['contas_pagar'], ''),
                ('Entradas efetivas', painel['entradas'], ''),
                ('Saídas efetivas', -painel['saidas'], ''),
                ('Fluxo efetivo', painel['fluxo'], 'total')]:
            self.caixa.insert('', 'end', tags=(tag,) if tag else (), values=(rot, tema.moeda(val)))

    def _detalhar(self):
        sel = self.tree.selection()
        comp = self._comp.get(sel[0]) if sel else None
        if not comp:
            messagebox.showinfo('Detalhar', 'Selecione uma linha com lançamentos (vendas, CMV, taxas, perdas, consumo, despesas, outras).')
            return
        ini, fim = self.periodo.intervalo()
        rows = g.lancamentos_componente(comp, ini, fim)
        dlg = tk.Toplevel(self); dlg.title('Lançamentos'); dlg.geometry('760x520'); dlg.transient(self)
        tk.Label(dlg, text=comp.replace('_', ' ').title(), font=(_F(), 14, 'bold')).pack(anchor='w', padx=14, pady=10)
        if not rows:
            tk.Label(dlg, text='Nenhum lançamento.').pack(pady=20); return
        tv = cp.tabela(dlg, [('ref', 'Referência', 140, 'w'), ('data', 'Data', 150, 'w'),
                             ('descricao', 'Descrição', 330, 'w'), ('valor', 'Valor', 110, 'e')], altura=18)
        for i, r in enumerate(rows):
            tv.insert('', 'end', tags=('par' if i % 2 == 0 else 'impar',),
                      values=(r['ref'], r['data'], r['descricao'], tema.moeda(r['valor'])))
        tv.pack(fill='both', expand=True, padx=14, pady=(0, 14))
        tk.Label(dlg, text=f"Total: {tema.moeda(sum(r['valor'] for r in rows))}", font=(_F(), 11, 'bold')).pack(anchor='e', padx=14, pady=(0, 12))


# ---------------------------------------------------------------------------
# OPERACIONAL (consumo, perdas, produção)
# ---------------------------------------------------------------------------
class OperacionalPage(PaginaBase):
    titulo = 'Operacional'

    def _montar(self):
        C = _C()
        self._cabecalho('Operacional')
        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True)
        self.aba_consumo = ConsumoAba(nb, self.shell)
        self.aba_perda = PerdaAba(nb, self.shell)
        self.aba_prod = ProducaoAba(nb, self.shell)
        nb.add(self.aba_consumo, text=' Consumo interno / retiradas ')
        nb.add(self.aba_perda, text=' Perdas ')
        nb.add(self.aba_prod, text=' Produção ')

    def recarregar(self):
        for aba in (self.aba_consumo, self.aba_perda, self.aba_prod):
            aba.recarregar()


class _BaixaAba(tk.Frame):
    """Base para consumo/perda: busca produto, quantidade, carrinho, prévia,
    confirmação, histórico e estorno."""

    perda = False
    com_lote = False

    def __init__(self, master, shell):
        super().__init__(master, bg=_C()['branco'])
        self.shell = shell
        self.carrinho = []
        self._montar()

    def _montar(self):
        C = _C()
        topo = tk.Frame(self, bg=C['branco']); topo.pack(fill='x', padx=12, pady=10)
        esq = tk.Frame(topo, bg=C['branco']); esq.pack(side='left', fill='both', expand=True)
        dir_ = tk.Frame(topo, bg=C['branco']); dir_.pack(side='left', fill='both', expand=True, padx=(12, 0))

        tk.Label(esq, text='ITENS', bg=C['branco'], fg=C['cinza'], font=(_F(), 9, 'bold')).pack(anchor='w')
        self.tv = cp.tabela(esq, [('nome', 'Produto', 260, 'w'), ('lote', 'Lote', 120, 'w'),
                                  ('qtd', 'Qtd', 80, 'e'), ('custo', 'Custo', 100, 'e')], altura=8)
        self.tv.pack(fill='both', expand=True, pady=(4, 6))
        btns = tk.Frame(esq, bg=C['branco']); btns.pack(fill='x')
        ttk.Button(btns, text='Remover item', style='Secondary.TButton', command=self._remover).pack(side='left')
        self.lbl_total = tk.Label(esq, text='Total: R$ 0,00', bg=C['amarelo'], fg=C['verde2'], font=(_F(), 12, 'bold'))
        self.lbl_total.pack(fill='x', pady=6, ipady=6)

        tk.Label(dir_, text='BUSCAR PRODUTO (nome ou código)', bg=C['branco'], fg=C['cinza'], font=(_F(), 9, 'bold')).pack(anchor='w')
        self.busca = cp.BuscaProduto(dir_)
        self.busca.pack(fill='x', pady=(4, 6))
        qtd_linha = tk.Frame(dir_, bg=C['branco']); qtd_linha.pack(fill='x')
        tk.Label(qtd_linha, text='Quantidade', bg=C['branco'], fg=C['cinza'], font=(_F(), 8, 'bold')).pack(side='left')
        self.qtd = tk.Entry(qtd_linha, width=8, font=(_F(), 11), justify='center'); self.qtd.insert(0, '1')
        self.qtd.pack(side='left', padx=6)
        ttk.Button(qtd_linha, text='Adicionar', style='Primary.TButton', command=self._adicionar).pack(side='left')

        if not self.perda:
            self.finalidade = cp.combo(dir_, 'FINALIDADE (classifica o resultado)',
                                       ['Operacional', 'Equipe', 'Pessoal/família', 'Outro'])
            self.motivo = cp.campo(dir_, 'MOTIVO (texto livre, opcional)')
            self.responsavel = cp.campo(dir_, 'RESPONSÁVEL', g.USUARIO)
            self.obs = cp.campo(dir_, 'OBSERVAÇÃO', '')
        else:
            self.motivo = cp.combo(dir_, 'MOTIVO', op.MOTIVOS_PERDA)
            self.responsavel = cp.campo(dir_, 'RESPONSÁVEL', g.USUARIO)
            self.obs = cp.campo(dir_, 'OBSERVAÇÃO', '')

        ttk.Button(dir_, text='REGISTRAR', style='Primary.TButton', command=self._confirmar).pack(fill='x', pady=(10, 0))

        tk.Label(self, text='HISTÓRICO', bg=C['branco'], fg=C['cinza'], font=(_F(), 9, 'bold')).pack(anchor='w', padx=12)
        self.hist = cp.tabela(self, [('data', 'Data/hora', 160, 'w'), ('motivo', 'Motivo/finalidade', 300, 'w'),
                                     ('valor', 'Valor', 120, 'e')], altura=6)
        self.hist.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self.hist.bind('<Double-1>', lambda e: self._estornar())

    # --- ações ---
    def _adicionar(self):
        p = self.busca.produto
        if not p:
            messagebox.showwarning('Produto', 'Busque e selecione o produto na lista.'); return
        qtd = cp.parse_float(self.qtd.get(), 0)
        if qtd <= 0:
            messagebox.showwarning('Quantidade', 'Informe uma quantidade maior que zero.'); return
        lote_id = None
        if self.com_lote:
            lote_id = self._escolher_lote(p)
            if lote_id == 'cancelar':
                return
        ja = sum(i['quantidade'] for i in self.carrinho if i['produto_id'] == p['id'])
        if qtd > float(p['quantidade_estoque']) - ja + 0.001:
            messagebox.showwarning('Estoque insuficiente',
                                   f"Disponível: {tema.formatq(p['quantidade_estoque'], p['unidade'])}. "
                                   'Registre entrada/inventário antes.')
            return
        self.carrinho.append({'produto_id': p['id'], 'nome': p['nome'], 'unidade': p['unidade'],
                              'quantidade': qtd, 'preco_custo': p['preco_custo'], 'lote_id': lote_id,
                              'validade': (p.get('_lote_validade') if lote_id else None)})
        self.busca.limpar(); self.qtd.delete(0, 'end'); self.qtd.insert(0, '1')
        self._render()

    def _escolher_lote(self, p):
        lotes = val.lotes_produto(p['id'])
        if not lotes:
            return None
        dlg = tk.Toplevel(self); dlg.title(f'Lote de {p["nome"]}'); dlg.geometry('520x400'); dlg.transient(self)
        tk.Label(dlg, text='Escolha o lote (lote vencido pode ser perdido, mas não consumido):',
                 font=(_F(), 10), wraplength=480, justify='left').pack(anchor='w', padx=14, pady=10)
        tv = cp.tabela(dlg, [('val', 'Validade', 220, 'w'), ('qtd', 'Saldo', 120, 'e')], altura=8)
        for i, l in enumerate(lotes):
            venc = bool(l['data_validade'] and l['data_validade'] < date.today().isoformat())
            tv.insert('', 'end', iid=str(i), tags=('ruim' if venc else 'par',),
                      values=(f"{l['data_validade'] or 'sem validade'}{' (VENCIDO)' if venc else ''}", tema.formatq(l['quantidade'], p['unidade'])))
        tv.pack(fill='both', expand=True, padx=14)
        res = {'v': 'cancelar'}

        def usar():
            s = tv.selection()
            if not s:
                return
            l = lotes[int(s[0])]
            if not self.perda and l['data_validade'] and l['data_validade'] < date.today().isoformat():
                messagebox.showerror('Lote vencido', 'Lote vencido só pode ser baixado como PERDA.', parent=dlg); return
            p['_lote_validade'] = l['data_validade']
            res['v'] = l['id']; dlg.destroy()

        def sem():
            res['v'] = None; dlg.destroy()
        b = tk.Frame(dlg); b.pack(fill='x', padx=14, pady=10)
        ttk.Button(b, text='Usar lote', style='Primary.TButton', command=usar).pack(side='right')
        ttk.Button(b, text='Sem lote (FEFO)', style='Secondary.TButton', command=sem).pack(side='right', padx=6)
        self.wait_window(dlg)
        return res['v']

    def _render(self):
        self.tv.delete(*self.tv.get_children())
        total = 0.0
        for i, it in enumerate(self.carrinho):
            lote = ''
            if it.get('lote_id'):
                lote = it.get('validade') or 'lote'
            custo = it['quantidade'] * it['preco_custo'] if (it['preco_custo'] or 0) > 0 else None
            if custo:
                total += custo
            self.tv.insert('', 'end', iid=str(i), tags=('par' if i % 2 == 0 else 'impar',),
                           values=(it['nome'], lote, tema.formatq(it['quantidade'], it['unidade']),
                                   tema.moeda(custo) if custo is not None else 'custo desconhecido'))
        sem = sum(1 for i in self.carrinho if not (i['preco_custo'] or 0) > 0)
        self.lbl_total.config(text=f"Total (custo): {tema.moeda(total)}" + (f'  (+{sem} sem custo)' if sem else ''))

    def _remover(self):
        s = self.tv.selection()
        if s:
            self.carrinho.pop(int(s[0])); self._render()

    def _confirmar(self):
        if not self.carrinho:
            messagebox.showinfo('Itens', 'Adicione ao menos um item.'); return
        if not self.perda:
            fin = {'Operacional': 'operacional', 'Equipe': 'equipe', 'Pessoal/família': 'pessoal', 'Outro': 'outro'}[self.finalidade.get()]
        else:
            fin = ''
        motivo = (self.motivo.get() if isinstance(self.motivo, tk.StringVar) else self.motivo.get()).strip()
        obs = self.obs.get().strip(); resp = self.responsavel.get().strip() or g.USUARIO
        if not messagebox.askyesno('Confirmar', f"{len(self.carrinho)} item(ns). Baixar do estoque?"):
            return
        itens = [{'produto_id': i['produto_id'], 'quantidade': i['quantidade'], 'lote_id': i.get('lote_id')} for i in self.carrinho]
        try:
            if self.perda:
                r = op.registrar_perda(itens, motivo, obs, resp)
            else:
                r = op.registrar_consumo_interno(itens, motivo, obs, resp, finalidade=fin)
        except Exception as exc:
            messagebox.showerror('Erro ao salvar', str(exc)); return
        self.carrinho = []; self._render()
        self.shell.notificar(f"Lançamento #{r['id']} registrado — {tema.moeda(r['valor_total'])}.")
        self.recarregar()
        self.shell.atualizar_inicio()

    def _estornar(self):
        s = self.hist.selection()
        if not s:
            return
        baixa_id = int(s[0])
        motivo = simpledialog.askstring('Estornar', 'Motivo do estorno (original preservado):', parent=self)
        if not motivo or not motivo.strip():
            return
        try:
            if self.perda:
                op.estornar_perda(baixa_id, motivo.strip())
            else:
                op.estornar_consumo_interno(baixa_id, motivo.strip())
        except Exception as exc:
            messagebox.showerror('Erro', str(exc)); return
        self.recarregar(); self.shell.atualizar_inicio()
        self.shell.notificar('Lançamento estornado.')

    def recarregar(self):
        self.hist.delete(*self.hist.get_children())
        if self.perda:
            registros = op.listar_perdas()
        else:
            registros = op.listar_consumo_interno()
        for i, r in enumerate(registros):
            est = bool(r.get('estornado'))
            rot = (r['motivo'] or '—')
            if not self.perda:
                rot = f"{op.NOMES_GRUPO_CONSUMO.get(op.grupo_consumo(r['motivo'], r.get('finalidade')), 'Outro')}" + (f" · {r['motivo']}" if r['motivo'] else '')
            tag = 'ruim' if est else ('par' if i % 2 == 0 else 'impar')
            self.hist.insert('', 'end', iid=str(r['id']), tags=(tag,),
                             values=(r['data_hora'], rot + ('  ESTORNADO' if est else ''), tema.moeda(r['valor_total'])))


class ConsumoAba(_BaixaAba):
    perda = False


class PerdaAba(_BaixaAba):
    perda = True
    com_lote = True


class ProducaoAba(tk.Frame):
    def __init__(self, master, shell):
        super().__init__(master, bg=_C()['branco'])
        self.shell = shell
        self.receitas = []
        self._montar()

    def _montar(self):
        C = _C()
        topo = tk.Frame(self, bg=C['branco']); topo.pack(fill='x', padx=12, pady=10)
        esq = tk.Frame(topo, bg=C['branco']); esq.pack(side='left', fill='both', expand=True)
        dir_ = tk.Frame(topo, bg=C['branco']); dir_.pack(side='left', fill='both', expand=True, padx=(12, 0))
        self.receitas = prod.listar_receitas()
        opcoes = [f"{r['id']} — {r['nome']} ({r['unidade']})" for r in self.receitas]
        self.var_receita = cp.combo(dir_, 'RECEITA', opcoes) if opcoes else tk.StringVar(value='')
        self.mult = cp.campo(dir_, 'QUANTAS VEZES FEZ A RECEITA', '1')
        self.rend = cp.campo(dir_, 'RENDIMENTO REAL (vazio = previsto)', '')
        self.validade = cp.campo(dir_, 'VALIDADE DO PRODUTO FINAL (AAAA-MM-DD)')
        self.obs = cp.campo(dir_, 'OBSERVAÇÃO', '')
        ttk.Button(dir_, text='REGISTRAR PRODUÇÃO', style='Primary.TButton', command=self._registrar).pack(fill='x', pady=(10, 0))
        tk.Label(esq, text='PRÉVIA', bg=C['branco'], fg=C['cinza'], font=(_F(), 9, 'bold')).pack(anchor='w')
        self.previa = tk.Label(esq, text='Selecione a receita e o multiplicador.', bg=C['zebra'], fg=C['verde2'],
                               font=('Consolas', 9), justify='left', anchor='nw', wraplength=440)
        self.previa.pack(fill='both', expand=True, pady=(4, 6), ipady=6)
        for w in (self.mult, self.rend):
            w.bind('<KeyRelease>', lambda e: self._atualizar())
        self.var_receita.trace_add('write', lambda *a: self._atualizar())

        tk.Label(self, text='HISTÓRICO DE PRODUÇÕES', bg=C['branco'], fg=C['cinza'], font=(_F(), 9, 'bold')).pack(anchor='w', padx=12)
        self.hist = cp.tabela(self, [('data', 'Data', 150, 'w'), ('produto', 'Produto', 220, 'w'),
                                     ('qtd', 'Produzido', 110, 'e'), ('custo', 'Custo', 110, 'e')], altura=6)
        self.hist.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self.hist.bind('<Double-1>', lambda e: self._estornar())

    def _receita_atual(self):
        if not self.receitas:
            return None
        try:
            rid = int(self.var_receita.get().split(' — ')[0])
        except (ValueError, IndexError):
            return None
        return next((r for r in self.receitas if r['id'] == rid), None)

    def _atualizar(self):
        r = self._receita_atual()
        if not r:
            self.previa.config(text='Selecione a receita.'); return
        mult = cp.parse_float(self.mult.get(), 0)
        if mult <= 0:
            self.previa.config(text='Informe o multiplicador.'); return
        linhas, custo, faltando = [], 0.0, False
        for it in r['itens']:
            p = op.obter_produto(it['insumo_id'])
            nec = it['quantidade'] * mult
            ok = p and p['quantidade_estoque'] + 1e-6 >= nec and p['ativo']
            if not ok:
                faltando = True
            if p and (p['preco_custo'] or 0) > 0:
                custo += nec * p['preco_custo']
            nome = p['nome'] if p else f"#{it['insumo_id']}"
            disp = p['quantidade_estoque'] if p else 0
            linhas.append(f"  {nome}: precisa {nec:g}, disponível {disp:g}" + ('' if ok else '  ⚠'))
        produz = round(r['rendimento'] * mult, 3)
        txt = f"Rendimento previsto: {produz:g} {r['unidade']}\n" + '\n'.join(linhas) + f"\nCusto estimado: {tema.moeda(custo)}"
        if faltando:
            txt += '\n⚠ Insumo insuficiente/inativo — a produção será rejeitada.'
        self.previa.config(text=txt)

    def _registrar(self):
        r = self._receita_atual()
        if not r:
            messagebox.showwarning('Receita', 'Escolha a receita.'); return
        mult = cp.parse_float(self.mult.get(), 0)
        if mult <= 0:
            messagebox.showwarning('Multiplicador', 'Informe quantas vezes fez a receita.'); return
        validade = self.validade.get().strip()
        if not validade:
            messagebox.showwarning('Validade', 'Informe a validade do produto final.'); return
        try:
            res = g.registrar_producao(r['id'], mult, self.obs.get().strip(), validade,
                                       cp.parse_float(self.rend.get(), 0) or None)
        except Exception as exc:
            messagebox.showerror('Erro ao salvar', str(exc)); return
        self.shell.notificar(f"Produção #{res['id']}: {res['quantidade_produzida']:g} · custo unitário {tema.moeda(res['custo_unitario'])}.")
        self.recarregar(); self.shell.atualizar_inicio()

    def _estornar(self):
        s = self.hist.selection()
        if not s:
            return
        pid = int(s[0])
        motivo = simpledialog.askstring('Estornar produção', 'Motivo (só se o produto não foi usado depois):', parent=self)
        if not motivo or not motivo.strip():
            return
        try:
            g.estornar_producao(pid, motivo.strip())
        except Exception as exc:
            messagebox.showerror('Não foi possível estornar', str(exc)); return
        self.recarregar(); self.shell.atualizar_inicio()
        self.shell.notificar('Produção estornada.')

    def recarregar(self):
        self.receitas = prod.listar_receitas()
        self.hist.delete(*self.hist.get_children())
        for i, pr in enumerate(prod.listar_producoes(100)):
            est = bool(pr.get('estornado'))
            tag = 'ruim' if est else ('par' if i % 2 == 0 else 'impar')
            self.hist.insert('', 'end', iid=str(pr['id']), tags=(tag,),
                             values=(pr['data_hora'], pr['produto_nome'] + ('  ESTORNADA' if est else ''),
                                     tema.formatq(pr['quantidade_produzida'], pr['unidade']), tema.moeda(pr['custo_total'])))


# ---------------------------------------------------------------------------
# PRODUTOS E ESTOQUE
# ---------------------------------------------------------------------------
class ProdutosPage(PaginaBase):
    titulo = 'Produtos e estoque'

    def _montar(self):
        C = _C()
        cab = self._cabecalho('Produtos e estoque')
        ttk.Button(cab, text='Novo produto', style='Primary.TButton', command=self._novo).pack(side='right', padx=4)
        ttk.Button(cab, text='Ajustar estoque', style='Secondary.TButton', command=self._ajustar).pack(side='right', padx=4)
        ttk.Button(cab, text='Editar', style='Secondary.TButton', command=self._editar).pack(side='right', padx=4)
        barra = tk.Frame(self, bg=C['papel']); barra.pack(fill='x', pady=(0, 6))
        self.busca = tk.Entry(barra, font=(_F(), 11), width=40); self.busca.pack(side='left')
        self.busca.bind('<KeyRelease>', lambda e: self.recarregar())
        ttk.Button(barra, text='Lotes / validade', style='Secondary.TButton', command=self._lotes).pack(side='right')
        self.tv = cp.tabela(self, [('nome', 'Produto', 300, 'w'), ('un', 'Un', 50, 'center'),
                                   ('estoque', 'Estoque', 110, 'e'), ('custo', 'Custo', 110, 'e'),
                                   ('venda', 'Venda', 110, 'e')], altura=18)
        self.tv.pack(fill='both', expand=True)
        self.tv.bind('<Double-1>', lambda e: self._editar())
        self._cache = {}

    def recarregar(self):
        termo = self.busca.get().strip()
        produtos = op.listar_produtos(termo) if termo else op.listar_produtos()
        self._cache = {}
        self.tv.delete(*self.tv.get_children())
        for i, p in enumerate(produtos):
            self._cache[p['id']] = p
            tag = 'par'
            if (p['quantidade_estoque'] or 0) < 0:
                tag = 'ruim'
            elif (p['preco_custo'] or 0) <= 0:
                tag = 'alerta'
            elif i % 2:
                tag = 'impar'
            self.tv.insert('', 'end', iid=str(p['id']), tags=(tag,), values=(
                p['nome'], p['unidade'], tema.formatq(p['quantidade_estoque'], p['unidade']),
                tema.moeda(p['preco_custo']) if (p['preco_custo'] or 0) > 0 else 'desconhecido',
                tema.moeda(p['preco_venda'])))

    def _sel(self):
        s = self.tv.selection()
        return self._cache.get(int(s[0])) if s else None

    def _novo(self):
        _FormProduto(self, None, self.recarregar)

    def _editar(self):
        p = self._sel()
        if p:
            _FormProduto(self, p, self.recarregar)

    def _ajustar(self):
        p = self._sel()
        if not p:
            return
        dlg = tk.Toplevel(self); dlg.title(f'Ajustar estoque — {p["nome"]}'); dlg.geometry('380x320'); dlg.transient(self)
        tk.Label(dlg, text=f"Estoque atual: {tema.formatq(p['quantidade_estoque'], p['unidade'])}", font=(_F(), 10)).pack(anchor='w', padx=20, pady=12)
        e_qtd = cp.campo(dlg, 'NOVA QUANTIDADE CONTADA', p['quantidade_estoque'])
        e_mot = cp.campo(dlg, 'MOTIVO / DOCUMENTO')
        e_val = cp.campo(dlg, 'VALIDADE (se perecível)')

        def salvar():
            try:
                g.ajustar_estoque(p['id'], cp.parse_float(e_qtd.get(), 0), 'ajuste', e_mot.get().strip() or 'Inventário', validade=e_val.get().strip() or None)
            except Exception as exc:
                messagebox.showerror('Erro', str(exc), parent=dlg); return
            dlg.destroy(); self.recarregar(); self.shell.notificar('Estoque ajustado.')
        ttk.Button(dlg, text='Salvar ajuste', style='Primary.TButton', command=salvar).pack(pady=12)

    def _lotes(self):
        p = self._sel()
        if not p:
            return
        lotes = val.lotes_produto(p['id'])
        dlg = tk.Toplevel(self); dlg.title(f'Lotes de {p["nome"]}'); dlg.geometry('560x460'); dlg.transient(self)
        tv = cp.tabela(dlg, [('val', 'Validade', 180, 'w'), ('qtd', 'Saldo', 100, 'e'), ('obs', 'Observação', 220, 'w')], altura=12)
        for i, l in enumerate(lotes):
            venc = bool(l['data_validade'] and l['data_validade'] < date.today().isoformat())
            tv.insert('', 'end', tags=('ruim' if venc else 'par',),
                      values=(l['data_validade'] or 'sem validade', tema.formatq(l['quantidade'], p['unidade']), l['observacao'] or ''))
        tv.pack(fill='both', expand=True, padx=14, pady=10)

        def novo_lote():
            qtd = simpledialog.askfloat('Novo lote', 'Quantidade:', parent=dlg)
            if not qtd:
                return
            dv = simpledialog.askstring('Novo lote', 'Validade (AAAA-MM-DD):', parent=dlg)
            try:
                val.registrar_lote(p['id'], qtd, dv or None)
            except Exception as exc:
                messagebox.showerror('Erro', str(exc), parent=dlg); return
            dlg.destroy(); self._lotes(); self.recarregar()
        ttk.Button(dlg, text='Adicionar lote', style='Primary.TButton', command=novo_lote).pack(pady=(0, 12))


class _FormProduto(tk.Toplevel):
    def __init__(self, master, produto, ao_salvar):
        super().__init__(master)
        self.produto = produto; self.ao_salvar = ao_salvar
        self.title('Editar produto' if produto else 'Novo produto'); self.geometry('440x620'); self.transient(master)
        self.configure(bg=_C()['branco'])
        self.e_nome = cp.campo(self, 'NOME', produto['nome'] if produto else '')
        self.e_cod = cp.campo(self, 'CÓDIGO DE BARRAS', produto['codigo_barras'] if produto else '')
        self.v_un = cp.combo(self, 'UNIDADE', ['UN', 'KG'], produto['unidade'] if produto else 'UN')
        self.e_custo = cp.campo(self, 'PREÇO DE CUSTO', produto['preco_custo'] if produto else '0')
        self.e_venda = cp.campo(self, 'PREÇO DE VENDA', produto['preco_venda'] if produto else '0')
        self.e_min = cp.campo(self, 'ESTOQUE MÍNIMO', produto['estoque_minimo'] if produto else '3')
        if not produto:
            self.e_estoque = cp.campo(self, 'ESTOQUE INICIAL', '0')
        self.conhecido = tk.BooleanVar(value=bool(produto.get('custo_conhecido')) if produto else False)
        tk.Checkbutton(self, text='Custo conhecido (marque para custo zero legítimo)', variable=self.conhecido,
                       bg=_C()['branco'], font=(_F(), 8)).pack(anchor='w', padx=20, pady=(8, 0))
        ttk.Button(self, text='Salvar', style='Primary.TButton', command=self._salvar).pack(fill='x', padx=20, pady=16)

    def _salvar(self):
        nome = self.e_nome.get().strip()
        if not nome:
            messagebox.showerror('Nome', 'Informe o nome.', parent=self); return
        custo = cp.parse_float(self.e_custo.get(), 0)
        conhecido = bool(self.conhecido.get()) or custo > 0
        try:
            if self.produto:
                op.atualizar_produto(self.produto['id'], nome, self.e_cod.get().strip() or None, None,
                                     self.v_un.get(), custo, cp.parse_float(self.e_venda.get(), 0),
                                     cp.parse_float(self.e_min.get(), 3), custo_conhecido=conhecido)
            else:
                op.criar_produto(nome, self.e_cod.get().strip() or None, None, self.v_un.get(), custo,
                                 cp.parse_float(self.e_venda.get(), 0), cp.parse_float(self.e_estoque.get(), 0),
                                 cp.parse_float(self.e_min.get(), 3), custo_conhecido=conhecido)
        except Exception as exc:
            messagebox.showerror('Erro ao salvar', str(exc), parent=self); return
        self.destroy(); self.ao_salvar(); self.master.shell.notificar('Produto salvo.') if hasattr(self.master, 'shell') else None


# ---------------------------------------------------------------------------
# COMPRAS
# ---------------------------------------------------------------------------
class ComprasPage(PaginaBase):
    titulo = 'Compras'

    def _montar(self):
        C = _C()
        self._cabecalho('Compras — receber mercadoria')
        corpo = tk.Frame(self, bg=C['papel']); corpo.pack(fill='both', expand=True)
        esq = tk.Frame(corpo, bg=C['branco']); esq.pack(side='left', fill='both', expand=True)
        dir_ = tk.Frame(corpo, bg=C['branco']); dir_.pack(side='left', fill='both', expand=True, padx=(10, 0))
        self.e_forn = cp.campo(dir_, 'FORNECEDOR', '')
        self.e_doc = cp.campo(dir_, 'DOCUMENTO', '')
        self.e_venc = cp.campo(dir_, 'VENCIMENTO (AAAA-MM-DD)', (date.today() + timedelta(days=30)).isoformat())
        self.v_forma = cp.combo(dir_, 'CONDIÇÃO', ['A prazo', 'À vista'])
        self.carrinho = []
        tk.Label(esq, text='ITENS', bg=C['branco'], fg=C['cinza'], font=(_F(), 9, 'bold')).pack(anchor='w')
        self.busca = cp.BuscaProduto(esq); self.busca.pack(fill='x', pady=(4, 4))
        linha = tk.Frame(esq, bg=C['branco']); linha.pack(fill='x')
        self.e_qtd = tk.Entry(linha, width=8); self.e_qtd.insert(0, '1'); self.e_qtd.pack(side='left')
        tk.Label(linha, text='Qtd', bg=C['branco'], font=(_F(), 8)).pack(side='left', padx=4)
        self.e_custo = tk.Entry(linha, width=10); self.e_custo.pack(side='left')
        tk.Label(linha, text='Custo', bg=C['branco'], font=(_F(), 8)).pack(side='left', padx=4)
        self.e_val = tk.Entry(linha, width=12); self.e_val.pack(side='left')
        tk.Label(linha, text='Validade', bg=C['branco'], font=(_F(), 8)).pack(side='left', padx=4)
        ttk.Button(linha, text='Adicionar', command=self._add).pack(side='left', padx=6)
        self.tv = cp.tabela(esq, [('nome', 'Produto', 220, 'w'), ('qtd', 'Qtd', 70, 'e'),
                                  ('custo', 'Custo', 90, 'e'), ('sub', 'Subtotal', 100, 'e')], altura=10)
        self.tv.pack(fill='both', expand=True, pady=6)
        self.lbl = tk.Label(esq, text='Total: R$ 0,00', bg=C['amarelo'], fg=C['verde2'], font=(_F(), 12, 'bold'))
        self.lbl.pack(fill='x', ipady=6)
        ttk.Button(dir_, text='RECEBER COMPRA', style='Primary.TButton', command=self._receber).pack(fill='x', pady=(12, 0))

    def _add(self):
        p = self.busca.produto
        if not p:
            messagebox.showwarning('Produto', 'Busque e selecione o produto.'); return
        qtd = cp.parse_float(self.e_qtd.get(), 0)
        custo = cp.parse_float(self.e_custo.get(), 0)
        if qtd <= 0 or custo < 0:
            messagebox.showwarning('Valores', 'Informe quantidade e custo válidos.'); return
        if p.get('perecivel') and not self.e_val.get().strip():
            messagebox.showwarning('Validade', 'Produto perecível exige validade.'); return
        self.carrinho.append({'produto_id': p['id'], 'nome': p['nome'], 'quantidade': qtd, 'custo': custo,
                              'validade': self.e_val.get().strip() or None})
        self.busca.limpar(); self.e_qtd.delete(0, 'end'); self.e_qtd.insert(0, '1'); self.e_custo.delete(0, 'end'); self.e_val.delete(0, 'end')
        self._render()

    def _render(self):
        self.tv.delete(*self.tv.get_children())
        total = 0.0
        for i, it in enumerate(self.carrinho):
            sub = it['quantidade'] * it['custo']; total += sub
            self.tv.insert('', 'end', tags=('par' if i % 2 == 0 else 'impar',),
                           values=(it['nome'], f"{it['quantidade']:g}", tema.moeda(it['custo']), tema.moeda(sub)))
        self.lbl.config(text=f'Total: {tema.moeda(total)}')

    def _receber(self):
        if not self.carrinho:
            messagebox.showinfo('Itens', 'Adicione itens.'); return
        if not self.e_forn.get().strip() or not self.e_doc.get().strip():
            messagebox.showwarning('Dados', 'Informe fornecedor e documento.'); return
        try:
            comp = g.receber_compra(
                [{'produto_id': i['produto_id'], 'quantidade': i['quantidade'], 'custo': i['custo'], 'validade': i['validade']} for i in self.carrinho],
                self.e_forn.get().strip(), self.e_doc.get().strip(), self.e_venc.get().strip(), self.v_forma.get())
        except Exception as exc:
            messagebox.showerror('Erro ao salvar', str(exc)); return
        self.carrinho = []; self._render()
        self.shell.notificar(f'Compra #{comp} recebida (estoque + conta a pagar).')
        self.shell.atualizar_inicio()

    def recarregar(self):
        pass


# ---------------------------------------------------------------------------
# FINANCEIRO
# ---------------------------------------------------------------------------
class FinanceiroPage(PaginaBase):
    titulo = 'Financeiro'

    def _montar(self):
        C = _C()
        cab = self._cabecalho('Financeiro')
        ttk.Button(cab, text='Nova conta a pagar', style='Primary.TButton', command=self._nova).pack(side='right', padx=4)
        ttk.Button(cab, text='Registrar pagamento', style='Secondary.TButton', command=self._pagar).pack(side='right', padx=4)
        nb = ttk.Notebook(self); nb.pack(fill='both', expand=True)
        self.aba_pagar = tk.Frame(nb, bg=C['branco']); nb.add(self.aba_pagar, text=' Contas a pagar ')
        self.aba_mov = tk.Frame(nb, bg=C['branco']); nb.add(self.aba_mov, text=' Movimentos ')

    def recarregar(self):
        for w in self.aba_pagar.winfo_children():
            w.destroy()
        self.tv = cp.tabela(self.aba_pagar, [('credor', 'Credor', 180, 'w'), ('desc', 'Descrição', 220, 'w'),
                                             ('venc', 'Vencimento', 110, 'w'), ('saldo', 'Saldo', 110, 'e'),
                                             ('status', 'Situação', 140, 'w')], altura=18)
        self.tv.pack(fill='both', expand=True, padx=10, pady=10)
        for i, r in enumerate(g.contas_pagar()):
            tag = 'ruim' if (r['saldo_centavos'] and r['dias'] < 0) else ('alerta' if (r['saldo_centavos'] and r['dias'] <= 3) else ('par' if i % 2 == 0 else 'impar'))
            self.tv.insert('', 'end', iid=str(r['id']), tags=(tag,), values=(
                r['credor'], r['descricao'], r['vencimento'], tema.moeda(r['saldo_centavos'] / 100), r['status']))
        for w in self.aba_mov.winfo_children():
            w.destroy()
        mov = cp.tabela(self.aba_mov, [('data', 'Data', 100, 'w'), ('conta', 'Conta', 140, 'w'),
                                       ('cat', 'Categoria', 150, 'w'), ('desc', 'Descrição', 260, 'w'),
                                       ('valor', 'Valor', 110, 'e')], altura=18)
        mov.pack(fill='both', expand=True, padx=10, pady=10)
        for i, m in enumerate(g.consultar('SELECT m.*,c.nome conta FROM movimentos_financeiros m JOIN contas_financeiras c ON c.id=m.conta_id ORDER BY m.data DESC, m.id DESC LIMIT 500')):
            mov.insert('', 'end', tags=('par' if i % 2 == 0 else 'impar',), values=(
                m['data'], m['conta'], m['categoria'], m['descricao'], tema.moeda(m['valor_centavos'] / 100)))

    def _nova(self):
        dlg = tk.Toplevel(self); dlg.title('Nova conta a pagar'); dlg.geometry('440x600'); dlg.transient(self)
        dlg.configure(bg=_C()['branco'])
        e_credor = cp.campo(dlg, 'CREDOR', '')
        e_desc = cp.campo(dlg, 'DESCRIÇÃO', '')
        e_valor = cp.campo(dlg, 'VALOR (R$)', '')
        e_comp = cp.campo(dlg, 'COMPETÊNCIA (AAAA-MM-DD)', date.today().isoformat())
        e_venc = cp.campo(dlg, 'VENCIMENTO (AAAA-MM-DD)', date.today().isoformat())
        v_cat = cp.combo(dlg, 'CATEGORIA', g.CATEGORIAS_CONTA)
        e_doc = cp.campo(dlg, 'DOCUMENTO', '')

        def salvar():
            try:
                g.criar_conta_pagar(e_credor.get().strip(), e_desc.get().strip(), cp.parse_float(e_valor.get(), 0),
                                    e_venc.get().strip(), v_cat.get(), competencia=e_comp.get().strip(), documento=e_doc.get().strip())
            except Exception as exc:
                messagebox.showerror('Erro ao salvar', str(exc), parent=dlg); return
            dlg.destroy(); self.recarregar(); self.shell.notificar('Conta criada.')
        ttk.Button(dlg, text='Salvar', style='Primary.TButton', command=salvar).pack(fill='x', padx=20, pady=16)

    def _pagar(self):
        s = self.tv.selection()
        if not s:
            return
        tid = int(s[0])
        t = next((r for r in g.contas_pagar() if r['id'] == tid), None)
        if not t or not t['saldo_centavos']:
            messagebox.showinfo('Conta', 'Conta já quitada.'); return
        dlg = tk.Toplevel(self); dlg.title(f"Pagar — {t['credor']}"); dlg.geometry('400x340'); dlg.transient(self)
        tk.Label(dlg, text=f"Saldo: {tema.moeda(t['saldo_centavos']/100)}", font=(_F(), 11)).pack(anchor='w', padx=20, pady=12)
        e_valor = cp.campo(dlg, 'VALOR A PAGAR (R$)', t['saldo_centavos'] / 100)
        contas = [f"{r['id']} — {r['nome']}" for r in g.contas_saldos()]
        v_conta = cp.combo(dlg, 'CONTA DE ORIGEM', contas, contas[-1])
        v_met = cp.combo(dlg, 'MÉTODO', ['Pix', 'Dinheiro', 'Transferência', 'Débito'])

        def salvar():
            try:
                g.pagar_conta(tid, cp.parse_float(e_valor.get(), 0), int(v_conta.get().split(' — ')[0]), v_met.get())
            except Exception as exc:
                messagebox.showerror('Erro ao salvar', str(exc), parent=dlg); return
            dlg.destroy(); self.recarregar(); self.shell.atualizar_inicio(); self.shell.notificar('Pagamento registrado.')
        ttk.Button(dlg, text='Registrar pagamento', style='Primary.TButton', command=salvar).pack(fill='x', padx=20, pady=16)


# ---------------------------------------------------------------------------
# DIAGNÓSTICO E SANEAMENTO
# ---------------------------------------------------------------------------
def diagnostico():
    """Achados de dados (somente leitura). Devolve lista de {tipo, detalhe, qtd}."""
    achados = []
    neg = g.consultar("SELECT COUNT(*) n FROM produtos WHERE ativo=1 AND quantidade_estoque<0")[0]['n']
    achados.append({'tipo': 'Estoque negativo', 'detalhe': 'Produtos com saldo abaixo de zero (regularize por inventário).', 'qtd': neg})
    semcusto = g.consultar("SELECT COUNT(*) n FROM produtos WHERE ativo=1 AND (preco_custo<=0 OR preco_custo IS NULL)")[0]['n']
    achados.append({'tipo': 'Custo desconhecido', 'detalhe': 'Produtos sem custo confiável (resultado fica parcial).', 'qtd': semcusto})
    div = g.consultar("""SELECT COUNT(*) n FROM produtos p WHERE p.ativo=1 AND
        (SELECT COALESCE(SUM(l.quantidade),0) FROM lotes_validade l WHERE l.produto_id=p.id AND l.quantidade>0) > p.quantidade_estoque+0.001""")[0]['n']
    achados.append({'tipo': 'Lotes x estoque', 'detalhe': 'Lotes somando mais que o estoque do produto.', 'qtd': div})
    semval = g.consultar("""SELECT COUNT(*) n FROM produtos p WHERE p.ativo=1 AND p.perecivel=1 AND p.quantidade_estoque>0 AND
        (SELECT COALESCE(SUM(l.quantidade),0) FROM lotes_validade l WHERE l.produto_id=p.id AND l.quantidade>0 AND l.data_validade IS NOT NULL) < p.quantidade_estoque-0.001""")[0]['n']
    achados.append({'tipo': 'Perecível sem validade', 'detalhe': 'Estoque perecível sem cobertura de lote/validade.', 'qtd': semval})
    pend = g.consultar("SELECT COUNT(*) n FROM consumo_interno WHERE estornado=0 AND (finalidade IS NULL OR finalidade='')")[0]['n']
    achados.append({'tipo': 'Consumo a classificar', 'detalhe': 'Lançamentos de consumo sem finalidade definida.', 'qtd': pend})
    return achados


class DiagnosticoPage(PaginaBase):
    titulo = 'Diagnóstico'

    def _montar(self):
        C = _C()
        cab = self._cabecalho('Diagnóstico e saneamento')
        tk.Label(self, text='Nada é alterado automaticamente. Cada item abre uma conferência assistida.',
                 bg=C['papel'], fg=C['cinza'], font=(_F(), 9)).pack(anchor='w', pady=(0, 6))
        self.tv = cp.tabela(self, [('tipo', 'Achado', 240, 'w'), ('detalhe', 'O que fazer', 560, 'w'), ('qtd', 'Qtd', 80, 'e')], altura=10)
        self.tv.pack(fill='both', expand=True, pady=(0, 8))
        barra = tk.Frame(self, bg=C['papel']); barra.pack(fill='x')
        ttk.Button(barra, text='Abrir produtos para conferir', style='Secondary.TButton', command=self._abrir_produtos).pack(side='left')
        ttk.Button(barra, text='Atualizar', style='Secondary.TButton', command=self.recarregar).pack(side='left', padx=6)
        self.lista_neg = cp.tabela(self, [('nome', 'Produto (estoque negativo)', 300, 'w'),
                                          ('estoque', 'Estoque', 120, 'e')], altura=8)
        self.lista_neg.pack(fill='both', expand=True)

    def recarregar(self):
        self.tv.delete(*self.tv.get_children())
        for i, d in enumerate(diagnostico()):
            tag = 'alerta' if d['qtd'] else 'par'
            self.tv.insert('', 'end', tags=(tag,), values=(d['tipo'], d['detalhe'], d['qtd']))
        self.lista_neg.delete(*self.lista_neg.get_children())
        for r in g.consultar("SELECT nome,unidade,quantidade_estoque FROM produtos WHERE ativo=1 AND quantidade_estoque<0 ORDER BY quantidade_estoque LIMIT 200"):
            self.lista_neg.insert('', 'end', tags=('ruim',), values=(r['nome'], tema.formatq(r['quantidade_estoque'], r['unidade'])))

    def _abrir_produtos(self):
        self.shell.ir_para('Produtos e estoque')


# ---------------------------------------------------------------------------
# VENDAS (PDV básico + lista)
# ---------------------------------------------------------------------------
class VendasPage(PaginaBase):
    titulo = 'Vendas'

    def _montar(self):
        C = _C()
        self._cabecalho('Vendas')
        corpo = tk.Frame(self, bg=C['papel']); corpo.pack(fill='both', expand=True)
        esq = tk.Frame(corpo, bg=C['branco']); esq.pack(side='left', fill='both', expand=True)
        dir_ = tk.Frame(corpo, bg=C['branco']); dir_.pack(side='left', fill='both', expand=True, padx=(10, 0))
        self.busca = cp.BuscaProduto(esq); self.busca.pack(fill='x', padx=10, pady=(10, 6))
        self.carrinho = []
        self.tv = cp.tabela(esq, [('nome', 'Produto', 220, 'w'), ('qtd', 'Qtd', 70, 'e'), ('sub', 'Subtotal', 100, 'e')], altura=10)
        self.tv.pack(fill='both', expand=True, padx=10)
        ttk.Button(esq, text='Adicionar', command=self._add).pack(pady=6)
        self.lbl = tk.Label(esq, text='Total: R$ 0,00', bg=C['amarelo'], fg=C['verde2'], font=(_F(), 13, 'bold'))
        self.lbl.pack(fill='x', padx=10, pady=(0, 10), ipady=6)
        self.v_forma = cp.combo(dir_, 'FORMA DE PAGAMENTO', ['dinheiro', 'pix', 'cartao_debito', 'cartao_credito', 'voucher'])
        self.e_desc = cp.campo(dir_, 'DESCONTO (R$)', '0')
        ttk.Button(dir_, text='FINALIZAR VENDA', style='Primary.TButton', command=self._finalizar).pack(fill='x', pady=(12, 0))
        tk.Label(dir_, text='ÚLTIMAS VENDAS', bg=C['branco'], fg=C['cinza'], font=(_F(), 9, 'bold')).pack(anchor='w', pady=(12, 2))
        self.hist = cp.tabela(dir_, [('data', 'Data', 130, 'w'), ('forma', 'Pagamento', 100, 'w'), ('total', 'Total', 90, 'e')], altura=8)
        self.hist.pack(fill='both', expand=True)

    def _add(self):
        p = self.busca.produto
        if not p:
            messagebox.showwarning('Produto', 'Busque e selecione o produto.'); return
        self.carrinho.append({'produto_id': p['id'], 'nome': p['nome'], 'quantidade': 1, 'preco_unitario': g.preco_vigente(p['id'])})
        self.busca.limpar(); self._render()

    def _render(self):
        self.tv.delete(*self.tv.get_children())
        total = 0.0
        for i, it in enumerate(self.carrinho):
            sub = it['quantidade'] * it['preco_unitario']; total += sub
            self.tv.insert('', '', tags=('par' if i % 2 == 0 else 'impar',), values=(it['nome'], it['quantidade'], tema.moeda(sub)))
        self.lbl.config(text=f'Total: {tema.moeda(total)}')

    def _finalizar(self):
        if not self.carrinho:
            messagebox.showinfo('Venda', 'Carrinho vazio.'); return
        try:
            r = op.registrar_venda([{'produto_id': i['produto_id'], 'quantidade': i['quantidade']} for i in self.carrinho],
                                   self.v_forma.get(), cp.parse_float(self.e_desc.get(), 0))
        except Exception as exc:
            messagebox.showerror('Erro ao salvar', str(exc)); return
        self.carrinho = []; self._render()
        self.shell.notificar(f"Venda #{r['id']} finalizada — {tema.moeda(r['valor_total'])}.")
        self.recarregar(); self.shell.atualizar_inicio()

    def recarregar(self):
        self.hist.delete(*self.hist.get_children())
        for i, v in enumerate(op.listar_vendas()):
            tag = 'ruim' if v.get('cancelada') else ('par' if i % 2 == 0 else 'impar')
            self.hist.insert('', 'end', tags=(tag,), values=(v['data_hora'], v['forma_pagamento'],
                                                             tema.moeda(v['valor_total']) + (' CANCELADA' if v.get('cancelada') else '')))


# ---------------------------------------------------------------------------
# ADMINISTRAÇÃO
# ---------------------------------------------------------------------------
class AdministracaoPage(PaginaBase):
    titulo = 'Administração'

    def _montar(self):
        C = _C()
        self._cabecalho('Administração')
        barra = tk.Frame(self, bg=C['papel']); barra.pack(fill='x', pady=(0, 8))
        ttk.Button(barra, text='Backup agora', style='Primary.TButton', command=self._backup).pack(side='left', padx=4)
        ttk.Button(barra, text='Restaurar backup', style='Secondary.TButton', command=self._restaurar).pack(side='left', padx=4)
        ttk.Button(barra, text='Atualizar', style='Secondary.TButton', command=self.recarregar).pack(side='left', padx=4)
        tk.Label(self, text='USUÁRIOS', bg=C['papel'], fg=C['cinza'], font=(_F(), 9, 'bold')).pack(anchor='w')
        self.tv = cp.tabela(self, [('nome', 'Usuário', 240, 'w'), ('perfil', 'Perfil', 160, 'w'), ('ativo', 'Ativo', 80, 'w')], altura=10)
        self.tv.pack(fill='both', expand=True)
        tk.Label(self, text='Versão do esquema: %s' % __import__('database').SCHEMA_VERSAO, bg=C['papel'],
                 fg=C['cinza'], font=(_F(), 9)).pack(anchor='w', pady=(8, 0))

    def recarregar(self):
        self.tv.delete(*self.tv.get_children())
        for i, u in enumerate(g.consultar('SELECT nome,perfil,ativo FROM usuarios ORDER BY nome')):
            self.tv.insert('', 'end', tags=('par' if i % 2 == 0 else 'impar',),
                           values=(u['nome'], u['perfil'], 'Sim' if u['ativo'] else 'Não'))

    def _backup(self):
        try:
            from backup import backup_completo
            destino = backup_completo()
        except Exception as exc:
            messagebox.showerror('Backup', str(exc)); return
        self.shell.notificar(f'Backup verificado em {destino}.')

    def _restaurar(self):
        from tkinter import filedialog
        from backup import validar_banco, restaurar_backup
        caminho = filedialog.askopenfilename(filetypes=[('Banco SQLite', '*.db')])
        if not caminho:
            return
        try:
            validar_banco(caminho)
        except Exception as exc:
            messagebox.showerror('Backup inválido', str(exc)); return
        if not messagebox.askyesno('Restaurar', 'Substituirá o banco atual e encerrará o app. Uma cópia do estado atual será guardada. Confirmar?'):
            return
        try:
            seg = restaurar_backup(caminho)
        except Exception as exc:
            messagebox.showerror('Falha ao restaurar', str(exc)); return
        messagebox.showinfo('Restaurado', f'Cópia do estado anterior em:\n{seg}\nAbra novamente o aplicativo.')
        self.shell.destroy()
