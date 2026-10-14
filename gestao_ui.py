"""Telas de gestão para o aplicativo Windows, sem dependências de interface adicionais."""
from datetime import date, timedelta
from pathlib import Path
import csv
import json
import os
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import uuid
import gestao as g
import operacoes as op
import analises as an
import database as db


def _grab_set_safe(dlg):
    try:
        dlg.grab_set()
    except tk.TclError:
        pass


class Tooltip:
    def __init__(self,widget,texto):
        self.widget,self.texto,self.janela=widget,texto,None
        widget.bind('<Enter>',self.mostrar,add='+')
        widget.bind('<Leave>',self.fechar,add='+')
        widget.bind('<ButtonPress>',self.fechar,add='+')

    def mostrar(self,_=None):
        self.fechar()
        self.janela=tk.Toplevel(self.widget)
        self.janela.overrideredirect(True)
        self.janela.geometry(f'+{self.widget.winfo_rootx()+10}+{self.widget.winfo_rooty()+self.widget.winfo_height()+3}')
        tk.Label(self.janela,text=self.texto,bg='#fff4cd',fg='#29251b',padx=10,pady=7,wraplength=320).pack()

    def fechar(self,_=None):
        if self.janela:
            self.janela.destroy(); self.janela=None


class GestaoMixin:
    def _executar_gestao(self,func):
        try:
            return func()
        except Exception as exc:
            messagebox.showerror('Não foi possível concluir',str(exc),parent=self)

    def _formulario(self,titulo,campos,confirmar,descricao=''):
        """Campos: (chave, rótulo, valor inicial, opções ou None)."""
        dlg=tk.Toplevel(self); dlg.title(titulo); dlg.transient(self); _grab_set_safe(dlg)
        self._dlg_formulario=dlg
        dlg.geometry(f'580x{min(760,180+len(campos)*58)}'); dlg.minsize(440,320)
        rodape=ttk.Frame(dlg,padding=12); rodape.pack(side='bottom',fill='x')
        canvas=tk.Canvas(dlg,highlightthickness=0)
        sb=ttk.Scrollbar(dlg,orient='vertical',command=canvas.yview); sb.pack(side='right',fill='y')
        canvas.pack(fill='both',expand=True); canvas.configure(yscrollcommand=sb.set)
        form=ttk.Frame(canvas,padding=18); wid=canvas.create_window((0,0),window=form,anchor='nw')
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(wid,width=e.width))
        form.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        ttk.Label(form,text=titulo,font=('Segoe UI',17,'bold')).pack(anchor='w',pady=(0,10))
        if descricao: ttk.Label(form,text=descricao,wraplength=490,justify='left').pack(fill='x',pady=(0,12))
        valores={}
        for chave,rotulo,inicial,opcoes in campos:
            ttk.Label(form,text=rotulo).pack(anchor='w',pady=(6,2))
            var=tk.StringVar(value=str(inicial if inicial is not None else ''))
            ent=ttk.Combobox(form,textvariable=var,values=opcoes,state='readonly') if opcoes else ttk.Entry(form,textvariable=var,show='•' if 'senha' in chave else '')
            ent.pack(fill='x',ipady=3); valores[chave]=var
            if chave in ('vencimento','emissao','competencia','validade','data'): Tooltip(ent,'Data no formato AAAA-MM-DD. Exemplo: 2026-09-30.')
        def salvar():
            try:
                if confirmar({k:v.get().strip() for k,v in valores.items()}) is False:
                    return
                dlg.destroy()
                self._atualizar_financeiro()
                self._aba_atualizada()
            except Exception as exc: messagebox.showerror('Confira os dados',str(exc),parent=dlg)
        ttk.Button(rodape,text='Confirmar',command=salvar).pack(side='right')
        ttk.Button(rodape,text='Cancelar',command=dlg.destroy).pack(side='right',padx=8)
        dlg.bind('<Escape>',lambda e:dlg.destroy())
        return dlg

    def _parent_ativo(self):
        """Janela certa para abrir messagebox: o formulario aberto (que tem o
        grab) ou a janela principal. Sem isso, o modal pode ficar atras do
        formulario e a tela parecer travada."""
        return getattr(self, '_dlg_formulario', None) or self

    def _tabela_gestao(self,parent,colunas):
        frame=ttk.Frame(parent); frame.pack(fill='both',expand=True,padx=8,pady=8)
        frame.columnconfigure(0,weight=1); frame.rowconfigure(0,weight=1)
        tree=ttk.Treeview(frame,columns=[c[0] for c in colunas],show='headings',selectmode='extended')
        for chave,rotulo,largura in colunas:
            tree.heading(chave,text=rotulo,command=lambda k=chave:self._ordenar_tabela(tree,k))
            tree.column(chave,width=largura,minwidth=65)
        tree.grid(row=0,column=0,sticky='nsew')
        vertical=ttk.Scrollbar(frame,orient='vertical',command=tree.yview); vertical.grid(row=0,column=1,sticky='ns')
        horizontal=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview); horizontal.grid(row=1,column=0,sticky='ew')
        tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        tree.tag_configure('alerta',background='#fff3cd',foreground='#6c4b00')
        tree.tag_configure('saida',foreground='#aa2424'); tree.tag_configure('entrada',foreground='#186c43')
        tree.tag_configure('vencido',background='#fbe6e6',foreground='#9c2020')
        return tree

    def _ordenar_tabela(self,tree,coluna):
        def chave(i):
            v=tree.set(i,coluna)
            try: return (0,float(v.replace('R$','').strip().replace('.','').replace(',','.')))
            except ValueError: return (1,g.normalizar(v))
        reverso=getattr(tree,'_ordem',None)==(coluna,False)
        for pos,i in enumerate(sorted(tree.get_children(),key=chave,reverse=reverso)): tree.move(i,'',pos)
        tree._ordem=(coluna,reverso)

    def _selecionado(self,tree):
        if not tree.selection(): raise g.ErroGestao('Selecione um registro primeiro.')
        return int(tree.selection()[0])

    def _montar_gestao(self):
        estilo=ttk.Style(self)
        estilo.configure('TFrame',background='#f5f6f1')
        estilo.configure('TLabel',background='#f5f6f1',foreground='#173b2d')
        estilo.configure('TLabelframe',background='#f5f6f1')
        estilo.configure('TLabelframe.Label',background='#f5f6f1',foreground='#173b2d')
        estilo.configure('Nav.TButton',font=('Segoe UI',10),padding=(8,5),anchor='w')
        estilo.configure('Financeiro.TNotebook.Tab',font=('Segoe UI',10,'bold'),padding=(9,8))
        self.tab_fin=ttk.Frame(self.nb); self.nb.add(self.tab_fin,text='Financeiro')
        self.tab_gestao=ttk.Frame(self.nb); self.nb.add(self.tab_gestao,text='Gestão')
        # Menu lateral deixa as áreas legíveis mesmo com muitas funções.
        ttk.Style(self).layout('Navegacao.TNotebook.Tab',[])
        self.nb.configure(style='Navegacao.TNotebook')
        self.nav_externa=ttk.Frame(self,width=170)
        self.nav_externa.pack(side='left',fill='y',before=self.nb)
        self.nav_canvas=tk.Canvas(self.nav_externa,width=163,highlightthickness=0,bg='#f5f6f1')
        nav_scroll=ttk.Scrollbar(self.nav_externa,orient='vertical',command=self.nav_canvas.yview)
        nav_scroll.pack(side='right',fill='y');self.nav_canvas.pack(side='left',fill='both',expand=True)
        self.nav_canvas.configure(yscrollcommand=nav_scroll.set)
        self.nav=ttk.Frame(self.nav_canvas,padding=(8,8))
        nav_id=self.nav_canvas.create_window((0,0),window=self.nav,anchor='nw')
        self.nav.bind('<Configure>',lambda e:self.nav_canvas.configure(scrollregion=self.nav_canvas.bbox('all')))
        self.nav_canvas.bind('<Configure>',lambda e:self.nav_canvas.itemconfigure(nav_id,width=e.width))
        self.nav_canvas.bind('<MouseWheel>',lambda e:self.nav_canvas.yview_scroll(-int(e.delta/120),'units'))
        self.nb.pack_configure(side='left',fill='both',expand=True,padx=(4,12),pady=10)
        grupos=[('PRINCIPAL',[('Venda rápida',self.tab_caixa),('Visão geral',self.tab_fin)]),
                ('CLIENTES',[('Clientes e fiado',self.tab_cli)]),
                ('ESTOQUE',[('Produtos',self.tab_prod),('Lotes e validade',self.tab_estoque)]),
                ('OPERACIONAL',[('Consumo interno',self.tab_consumo),('Perdas',self.tab_perdas),('Produção',self.tab_producao)]),
                ('GESTÃO',[('Vendas e análises',self.tab_analises),('Histórico',self.tab_hist),('Ferramentas',self.tab_gestao),('Configurações',self.tab_config)])]
        for titulo,links in grupos:
            ttk.Label(self.nav,text=titulo,font=('Segoe UI',8,'bold')).pack(anchor='w',pady=(9,2))
            for nome,tab in links:
                b=ttk.Button(self.nav,text=nome,style='Nav.TButton',command=lambda t=tab:self.nb.select(t)); b.pack(fill='x',pady=1)
        self.identidade=ttk.Label(self.nav,text='Identificação pendente',wraplength=170); self.identidade.pack(side='bottom',pady=5)
        self._montar_financeiro()
        self._montar_ferramentas()
        ordem=ttk.Frame(self.tab_cli); ordem.grid(row=3,column=0,sticky='ew',pady=6)
        ttk.Label(ordem,text='Ordenar por:').pack(side='left')
        self.ordem_clientes=tk.StringVar(value='Nome A–Z')
        combo=ttk.Combobox(ordem,textvariable=self.ordem_clientes,state='readonly',values=['Nome A–Z','Última compra','Saldo em aberto'])
        combo.pack(side='left',padx=8); combo.bind('<<ComboboxSelected>>',lambda e:self._carrega_clientes())
        ttk.Button(ordem,text='Política de crédito',command=lambda:self._executar_gestao(self._politica_cliente)).pack(side='right')
        extras=ttk.Frame(self.tab_prod); extras.grid(row=3,column=0,sticky='ew',pady=6)
        for nome,func in [('Filtros e ações em lote',self._catalogo_gestao),('Conferir duplicatas',self._duplicatas_ui),('Receber mercadoria',self._receber_mercadoria_ui),('Inventário',self._inventario_ui)]:
            ttk.Button(extras,text=nome,command=lambda f=func:self._executar_gestao(f)).pack(side='left',padx=3)
        ttk.Button(self.tab_hist,text='Cancelar venda / devolução integral',command=lambda:self._executar_gestao(self._cancelar_venda_ui)).grid(row=3,column=0,sticky='w',pady=8)
        aviso=ttk.Label(self.tab_analises,text='Vendas por competência. Custos antigos sem histórico são estimados pelo custo atual; veja as limitações na DRE.',wraplength=900,foreground='#946000')
        if self.tab_analises.pack_slaves(): aviso.pack(side='bottom',fill='x',padx=8)
        else: aviso.grid(row=99,column=0,sticky='ew')
        self._atualizar_financeiro()
        self.nb.select(self.tab_fin)

    def _montar_financeiro(self):
        topo=ttk.Frame(self.tab_fin,padding=10); topo.pack(fill='x')
        ttk.Label(topo,text='Financeiro',font=('Segoe UI',20,'bold')).pack(side='left')
        for nome,func in [('Abrir caixa',self._abrir_caixa_ui),('Fechar caixa',self._fechar_caixa_ui),('Transferir / sangria',self._transferencia_ui),('Nova venda',lambda:self.nb.select(self.tab_caixa))]:
            ttk.Button(topo,text=nome,command=lambda f=func:self._executar_gestao(f)).pack(side='right',padx=3)
        periodo=ttk.Frame(self.tab_fin,padding=(10,0)); periodo.pack(fill='x')
        self.fin_inicio=tk.StringVar(value=date.today().replace(day=1).isoformat()); self.fin_fim=tk.StringVar(value=date.today().isoformat())
        ttk.Label(periodo,text='Período:').pack(side='left')
        for var in (self.fin_inicio,self.fin_fim): ttk.Entry(periodo,textvariable=var,width=12).pack(side='left',padx=5)
        for nome,dias in [('Hoje',0),('7 dias',6),('30 dias',29)]:
            ttk.Button(periodo,text=nome,command=lambda n=dias:self._periodo_financeiro(n)).pack(side='left',padx=2)
        ttk.Button(periodo,text='Atualizar',command=lambda:self._executar_gestao(self._atualizar_financeiro)).pack(side='left',padx=5)
        ttk.Button(periodo,text='Personalizar',command=self._personalizar_painel).pack(side='right')
        self.painel_financeiro=ttk.Frame(self.tab_fin,padding=10); self.painel_financeiro.pack(fill='x')
        self.fin_alertas=ttk.Label(self.tab_fin,wraplength=950,justify='left',foreground='#946000'); self.fin_alertas.pack(fill='x',padx=12,pady=4)
        self.fin_abas=ttk.Notebook(self.tab_fin,style='Financeiro.TNotebook'); self.fin_abas.pack(fill='both',expand=True,padx=8,pady=8)
        abas=[]
        for nome in ('Movimentações','Contas a pagar','Contas a receber','Cartões','Contas e saldos','DRE gerencial'):
            f=ttk.Frame(self.fin_abas); self.fin_abas.add(f,text=nome); abas.append(f)
        movimentos,pagar,receber,cartoes,contas,dre=abas
        barra=ttk.Frame(movimentos); barra.pack(fill='x',padx=8,pady=5)
        for nome,func in [('Outras entradas/saídas',self._movimento_manual_ui),('Exportar CSV',self._exportar_movimentos),('Conciliação',self._conciliacao_ui)]:
            ttk.Button(barra,text=nome,command=lambda f=func:self._executar_gestao(f)).pack(side='left',padx=3)
        self.fin_mov=self._tabela_gestao(movimentos,[('data','Data',95),('conta','Conta',145),('categoria','Categoria',150),('descricao','Descrição',230),('valor','Valor',105),('conciliado','Conciliado',85)])
        barra=ttk.Frame(pagar); barra.pack(fill='x',padx=8,pady=5)
        for nome,func in [('Nova conta',self._nova_conta_ui),('Registrar pagamento',self._pagar_ui),('Histórico / estorno',self._historico_pagamentos_ui),('Calendário',self._calendario_pagar),('Exportar CSV',lambda:self._exportar_dados(g.contas_pagar(),'contas_pagar'))]:
            ttk.Button(barra,text=nome,command=lambda f=func:self._executar_gestao(f)).pack(side='left',padx=3)
        self.filtro_pagar=tk.StringVar(value='Todas')
        filtro=ttk.Combobox(barra,textvariable=self.filtro_pagar,values=['Todas','Em aberto','Vencidas','Próximos 3 dias','Pagas'],state='readonly',width=17)
        filtro.pack(side='right'); filtro.bind('<<ComboboxSelected>>',lambda e:self._atualizar_financeiro())
        self.fin_pagar=self._tabela_gestao(pagar,[('credor','Credor',155),('descricao','Descrição',190),('vencimento','Vencimento',100),('saldo','Saldo',100),('status','Situação',150),('categoria','Categoria',145)])
        self.fin_pagar.bind('<Double-1>',lambda e:self._executar_gestao(self._pagar_ui))
        ttk.Label(receber,text='Principal e encargos são separados. Títulos antigos sem vencimento precisam de conferência.').pack(anchor='w',padx=10,pady=8)
        self.fin_receber=self._tabela_gestao(receber,[('cliente','Cliente',220),('venda','Venda',65),('vencimento','Vencimento',105),('saldo','Principal',100),('encargos','Encargos',100),('status','Situação',170)])
        self.fin_receber.bind('<Double-1>',lambda e:self._abrir_cliente_titulo())
        ttk.Button(cartoes,text='Confirmar liquidação selecionada',command=lambda:self._executar_gestao(self._liquidar_cartao_ui)).pack(anchor='w',padx=10,pady=8)
        self.fin_cartoes=self._tabela_gestao(cartoes,[('origem','Origem',130),('referencia','Referência',80),('bruto','Bruto',105),('taxa','Taxa',100),('previsto','Previsão (conferir)',145),('situacao','Situação',150)])
        barra=ttk.Frame(contas); barra.pack(fill='x',padx=10,pady=8)
        ttk.Button(barra,text='Conferir saldo inicial',command=lambda:self._executar_gestao(self._saldo_inicial_ui)).pack(side='left')
        ttk.Button(barra,text='Adicionar conta',command=self._nova_conta_financeira_ui).pack(side='left',padx=8)
        self.fin_contas=self._tabela_gestao(contas,[('nome','Conta',210),('tipo','Tipo',95),('base','Data base',100),('saldo','Saldo calculado',130),('conferida','Saldo inicial conferido?',190)])
        # Painel gerencial estruturado (competência) + bloco "caixa não é lucro".
        self.dre_cab=ttk.Label(dre,text='',font=('Segoe UI',11,'bold')); self.dre_cab.pack(anchor='w',padx=10,pady=(8,0))
        self.dre_aviso=ttk.Label(dre,text='',foreground='#946000',wraplength=900,justify='left'); self.dre_aviso.pack(anchor='w',padx=10,pady=(0,4))
        corpo_dre=ttk.Frame(dre); corpo_dre.pack(fill='both',expand=True,padx=8,pady=(0,8))
        corpo_dre.columnconfigure(0,weight=3); corpo_dre.columnconfigure(1,weight=2); corpo_dre.rowconfigure(0,weight=1)
        self.dre_tree=ttk.Treeview(corpo_dre,columns=('componente','valor'),show='headings',height=15)
        self.dre_tree.heading('componente',text='Resultado gerencial (competência)')
        self.dre_tree.heading('valor',text='Valor')
        self.dre_tree.column('componente',width=340); self.dre_tree.column('valor',width=130,anchor='e')
        self.dre_tree.tag_configure('total',font=('Segoe UI',10,'bold'))
        self.dre_tree.tag_configure('sub',foreground='#24475c')
        self.dre_tree.tag_configure('pessoal',foreground='#9A6700')
        self.dre_tree.grid(row=0,column=0,sticky='nsew')
        self.dre_tree.bind('<Double-1>',lambda e:self._detalhar_componente())
        self.caixa_tree=ttk.Treeview(corpo_dre,columns=('item','valor'),show='headings',height=15)
        self.caixa_tree.heading('item',text='Caixa não é lucro (saldos e movimento)')
        self.caixa_tree.heading('valor',text='Valor')
        self.caixa_tree.column('item',width=240); self.caixa_tree.column('valor',width=120,anchor='e')
        self.caixa_tree.tag_configure('total',font=('Segoe UI',10,'bold'))
        self.caixa_tree.grid(row=0,column=1,sticky='nsew',padx=(8,0))
        barra_dre=ttk.Frame(dre); barra_dre.pack(fill='x',padx=10,pady=(0,6))
        ttk.Button(barra_dre,text='Ver lançamentos do componente selecionado',command=self._detalhar_componente).pack(side='left')

    def _periodo_financeiro(self,dias):
        self.fin_inicio.set((date.today()-timedelta(days=dias)).isoformat()); self.fin_fim.set(date.today().isoformat()); self._atualizar_financeiro()

    def _personalizar_painel(self):
        opcoes={'Entradas reais':'entradas','Saídas reais':'saidas','Fluxo líquido':'fluxo','Vendas (competência)':'vendas','Ticket médio':'ticket'}
        atuais=g.config('painel_'+g.USUARIO,list(opcoes.values()))
        dlg=tk.Toplevel(self); dlg.title('Indicadores do painel'); dlg.transient(self); _grab_set_safe(dlg)
        vals={}
        for nome,chave in opcoes.items():
            vals[chave]=tk.BooleanVar(value=chave in atuais)
            ttk.Checkbutton(dlg,text=nome,variable=vals[chave]).pack(anchor='w',padx=20,pady=7)
        def salvar():
            with g.transacao() as c: c.execute('INSERT OR REPLACE INTO gestao_config(chave,valor) VALUES(?,?)',('painel_'+g.USUARIO,json.dumps([k for k,v in vals.items() if v.get()])))
            dlg.destroy(); self._atualizar_financeiro()
        ttk.Button(dlg,text='Salvar',command=salvar).pack(pady=15)

    def _atualizar_financeiro(self):
        if not hasattr(self,'painel_financeiro'): return
        inicio,fim=self.fin_inicio.get(),self.fin_fim.get()
        d=g.resumo_financeiro(inicio,fim)
        for w in self.painel_financeiro.winfo_children(): w.destroy()
        cartoes=[('Entradas reais','entradas','#16734c'),('Saídas reais','saidas','#ac3030'),('Fluxo líquido','fluxo','#24475c'),('Vendas (competência)','vendas','#24475c'),('Ticket médio','ticket','#24475c')]
        visiveis=g.config('painel_'+g.USUARIO,[k for n,k,c in cartoes])
        for i,(nome,chave,cor) in enumerate(x for x in cartoes if x[1] in visiveis):
            f=ttk.LabelFrame(self.painel_financeiro,text=nome,padding=10); f.grid(row=0,column=i,sticky='ew',padx=4)
            self.painel_financeiro.columnconfigure(i,weight=1)
            ttk.Label(f,text=self._moeda(d[chave]),foreground=cor,font=('Segoe UI',17,'bold')).pack(anchor='w')
        pagar=g.contas_pagar(); pendencias=[r for r in pagar if r['saldo_centavos'] and r['dias']<=3]
        saldos=g.contas_saldos(); nao_conferidas=[r['nome'] for r in saldos if not r['conferida']]
        mig=g.consultar("SELECT valor FROM gestao_config WHERE chave='migracao_v1'")[0]['valor']
        alerta=f'Caixa realizado registrado a partir de {mig[:10]}; histórico anterior não foi inferido. '
        if nao_conferidas: alerta+='Conferir saldos iniciais: '+', '.join(nao_conferidas)+'. '
        alerta+=f'{len(pendencias)} conta(s) vencida(s) ou vencendo em até 3 dias.'
        validade=g.consultar("SELECT COUNT(*) n FROM lotes_validade WHERE quantidade>0 AND data_validade<=date('now','localtime','+7 days')")[0]['n']
        estoque=g.consultar('SELECT COUNT(*) n FROM produtos WHERE ativo=1 AND quantidade_estoque<=estoque_minimo')[0]['n']
        alerta+=f' Estoque: {estoque} produto(s) no mínimo; {validade} lote(s) vencido(s) ou próximo(s) de vencer.'
        self.fin_alertas.config(text=alerta,wraplength=max(600,self.tab_fin.winfo_width()-35))
        for tree in (self.fin_mov,self.fin_pagar,self.fin_receber,self.fin_cartoes,self.fin_contas): tree.delete(*tree.get_children())
        self._movimentos_rows=g.consultar('SELECT m.*,c.nome conta FROM movimentos_financeiros m JOIN contas_financeiras c ON c.id=m.conta_id WHERE data BETWEEN ? AND ? ORDER BY data DESC,m.id DESC',(inicio,fim))
        for r in self._movimentos_rows:
            self.fin_mov.insert('','end',iid=r['id'],values=(r['data'],r['conta'],r['categoria'],r['descricao'],self._moeda(r['valor_centavos']/100),'Sim' if r['conciliado'] else 'Não'),tags=('entrada' if r['valor_centavos']>0 else 'saida',))
        for r in pagar:
            filtro=self.filtro_pagar.get()
            if filtro=='Em aberto' and not r['saldo_centavos']: continue
            if filtro=='Vencidas' and (not r['saldo_centavos'] or r['dias']>=0): continue
            if filtro=='Próximos 3 dias' and (not r['saldo_centavos'] or not 0<=r['dias']<=3): continue
            if filtro=='Pagas' and r['saldo_centavos']: continue
            tag='vencido' if r['dias']<0 and r['saldo_centavos'] else ('alerta' if r['dias']<=3 and r['saldo_centavos'] else '')
            self.fin_pagar.insert('','end',iid=r['id'],values=(r['credor'],r['descricao'],r['vencimento'],self._moeda(r['saldo_centavos']/100),r['status'],r['categoria']),tags=(tag,))
        for cli in g.consultar('SELECT id,nome FROM clientes ORDER BY nome'):
            titulos=g.titulos_cliente(cli['id'])
            for t in titulos:
                if t['saldo_centavos']<=0: continue
                self.fin_receber.insert('','end',iid=t['id'],values=(cli['nome'],t['venda_id'],t['vencimento'] or 'Conferir',self._moeda(t['saldo_centavos']/100),self._moeda(t['encargos_centavos']/100),t['status']+(' • atrasado' if t['atraso'] else '')),tags=('vencido' if t['atraso'] else '',))
            residual=g.centavos(op.saldo_fiado(cli['id']))-sum(t['saldo_centavos'] for t in titulos)
            if residual>0:
                self.fin_receber.insert('','end',iid=-cli['id'],values=(cli['nome'],'Ajuste','Conferir',self._moeda(residual/100),'—','Saldo ajustado / legado'),tags=('alerta',))
        for r in g.consultar('SELECT * FROM recebiveis_cartao ORDER BY liquidado IS NOT NULL,previsto'):
            self.fin_cartoes.insert('','end',iid=r['id'],values=(r['origem'],r['referencia'],self._moeda(r['bruto_centavos']/100),self._moeda(r['taxa_centavos']/100),r['previsto'],r['liquidado'] or 'A liquidar'))
        for r in saldos:
            self.fin_contas.insert('','end',iid=r['id'],values=(r['nome'],r['tipo'],r['data_base'],self._moeda(r['saldo_centavos']/100),'Sim' if r['conferida'] else 'PENDENTE'),tags=(() if r['conferida'] else ('alerta',)))
        self._desenha_resultado_gerencial(inicio, fim)

    def _desenha_resultado_gerencial(self, inicio, fim):
        res = g.resultado_gerencial(inicio, fim)
        painel = g.painel_financeiro(inicio, fim)
        self.dre_cab.config(text=f"Resultado gerencial por competência — {res['inicio']} a {res['fim']}")
        self.dre_aviso.config(text=('⚠ RESULTADO PARCIAL: ' + '; '.join(res['pendencias']) +
                                    '. Não trate o valor como exato.') if res['parcial'] else '')
        self._dre_componentes = {}
        self.dre_tree.delete(*self.dre_tree.get_children())
        linhas = [
            ('vendas', 'Vendas líquidas de descontos e cancelamentos', res['vendas_liquidas'], ''),
            ('cmv', '(−) CMV histórico das mercadorias vendidas', -res['cmv'], ''),
            (None, f"= Margem bruta ({res['margem_pct']:.1f}%)", res['margem_bruta'], 'sub'),
            ('taxas', '(−) Taxas de cartão e outros meios', -res['taxas'], ''),
            ('perdas', '(−) Perdas de mercadorias (a preço de custo)', -res['perdas'], ''),
            ('consumo_operacional', '(−) Consumo operacional', -res['consumo_operacional'], ''),
            ('consumo_equipe', '(−) Consumo da equipe', -res['consumo_equipe'], ''),
            ('consumo_outro', '(−) Consumo a classificar', -res['consumo_outro'], ''),
            ('despesas_competencia', '(−) Despesas da loja por competência', -res['despesas_competencia'], ''),
            (None, '(+) Outras receitas', res['outras_receitas'], ''),
            (None, '(−) Outras despesas', -res['outras_despesas'], ''),
            (None, '= RESULTADO LÍQUIDO GERENCIAL', res['resultado_liquido'], 'total'),
            ('retiradas_pessoais', '(−) Retiradas pessoais/familiares (a preço de custo)', -res['retiradas_pessoais'], 'pessoal'),
            (None, '= RESULTADO APÓS RETIRADAS PESSOAIS/FAMILIARES', res['resultado_apos_retiradas'], 'total'),
        ]
        for i, (comp, rotulo, valor, tag) in enumerate(linhas):
            iid = comp or f'linha{i}'
            if comp:
                self._dre_componentes[iid] = comp
            self.dre_tree.insert('', 'end', iid=iid, tags=(tag,) if tag else (), values=(rotulo, self._moeda(valor)))

        self.caixa_tree.delete(*self.caixa_tree.get_children())
        for rotulo, valor, tag in [
            ('Dinheiro em caixa', painel['dinheiro'], 'total'),
            ('Saldo bancário registrado', painel['banco'], 'total'),
            ('Cartão a receber (não liquidado)', painel['cartao_receber'], ''),
            ('Fiado a receber', painel['fiado_receber'], ''),
            ('Contas a pagar em aberto', painel['contas_pagar'], ''),
            ('Entradas efetivas do período', painel['entradas'], ''),
            ('Saídas efetivas do período', -painel['saidas'], ''),
            ('Fluxo efetivo do período', painel['fluxo'], 'total'),
        ]:
            self.caixa_tree.insert('', 'end', tags=(tag,) if tag else (), values=(rotulo, self._moeda(valor)))
        for f in an.vendas_por_forma_pagamento(inicio, fim):
            extra = ' (a receber)' if f['forma'] == 'fiado' else ''
            self.caixa_tree.insert('', 'end', values=(f"  recebido · {f['rotulo']} ({f['n']}){extra}", self._moeda(f['total'])))

    def _detalhar_componente(self):
        sel = self.dre_tree.selection()
        comp = self._dre_componentes.get(sel[0]) if sel else None
        if not comp:
            messagebox.showinfo('Detalhar componente',
                                'Selecione uma linha do resultado que tenha lançamentos '
                                '(vendas, CMV, taxas, perdas, consumo, despesas ou retiradas).')
            return
        rows = g.lancamentos_componente(comp, self.fin_inicio.get(), self.fin_fim.get())
        self._listar_registros(f"Lançamentos — {comp.replace('_', ' ')}", rows)

    def _contas_opcoes(self):
        return [f"{r['id']} — {r['nome']}" for r in g.contas_saldos()]

    def _abrir_caixa_ui(self):
        self._formulario('Abrir caixa',[('valor','Dinheiro contado na gaveta (R$)','0',None)],lambda v:g.abrir_caixa(v['valor']),
                         'O fundo de abertura não é receita. Confira também o saldo inicial da conta Caixa na primeira utilização.')

    def _fechar_caixa_ui(self):
        self._formulario('Fechar caixa',[('valor','Dinheiro contado na gaveta (R$)','',None),('motivo','Justificativa de eventual diferença','',None)],lambda v:g.fechar_caixa(v['valor'],v['motivo']))

    def _transferencia_ui(self):
        contas=self._contas_opcoes()
        self._formulario('Transferência / sangria / suprimento',[('origem','Conta de origem',contas[0],contas),('destino','Conta de destino',contas[-1],contas),('valor','Valor (R$)','',None),('descricao','Descrição','Transferência interna',None)],
                         lambda v:g.transferencia(int(v['origem'].split(' — ')[0]),int(v['destino'].split(' — ')[0]),v['valor'],v['descricao']))

    def _nova_conta_ui(self):
        hoje=date.today().isoformat()
        self._formulario('Nova conta a pagar',[('credor','Credor / fornecedor','',None),('descricao','Descrição','',None),('valor','Valor original (R$)','',None),('vencimento','Vencimento',hoje,None),('emissao','Emissão',hoje,None),('competencia','Competência (mês em que a despesa conta no resultado)',hoje,None),('categoria','Categoria','Despesas fixas',g.CATEGORIAS_CONTA),('documento','Número do documento / boleto','',None),('compra_ref','Referência da compra de estoque (opcional)','',None)],lambda v:g.criar_conta_pagar(**v),
                         'A despesa entra no resultado pela COMPETÊNCIA e no caixa quando for paga. Mercadoria para revenda e Investimento não são despesa operacional.')

    def _pagar_ui(self):
        tid=self._selecionado(self.fin_pagar); t=next(x for x in g.contas_pagar() if x['id']==tid)
        if not t['saldo_centavos']: raise g.ErroGestao('Esta conta está quitada.')
        contas=self._contas_opcoes(); chave=uuid.uuid4().hex
        self._formulario('Registrar pagamento',[('valor','Principal a quitar (R$)',t['saldo_centavos']/100,None),('encargos','Encargos pagos (R$)','0',None),('desconto','Desconto obtido (R$)','0',None),('data','Data do pagamento',date.today().isoformat(),None),('conta','Conta de origem',contas[-1],contas),('metodo','Método','Pix',['Pix','Dinheiro','Transferência','Débito']),('comprovante','Caminho do comprovante (opcional)','',None)],
                         lambda v:g.pagar_conta(tid,v['valor'],int(v['conta'].split(' — ')[0]),v['metodo'],v['data'],v['encargos'],v['desconto'],self._guardar_comprovante(v['comprovante']),chave),f"{t['credor']} — {t['descricao']}")

    def _guardar_comprovante(self,caminho):
        if not caminho: return ''
        import shutil
        origem=Path(caminho)
        if not origem.is_file(): raise g.ErroGestao('Comprovante não encontrado.')
        destino=Path(db.DB_PATH).parent/'comprovantes'; destino.mkdir(exist_ok=True)
        arq=destino/(uuid.uuid4().hex+origem.suffix)
        shutil.copy2(origem,arq); return str(arq)

    def _historico_pagamentos_ui(self):
        tid=self._selecionado(self.fin_pagar)
        rows=g.consultar('SELECT * FROM pagamentos_contas WHERE titulo_id=? ORDER BY id DESC',(tid,))
        self._listar_registros('Pagamentos da conta',rows,lambda r:self._pedir_estorno('pagamento',r['id']))

    def _calendario_pagar(self):
        rows=[{'data':r['vencimento'],'credor':r['credor'],'descricao':r['descricao'],'saldo':r['saldo_centavos']/100,'situacao':r['status']} for r in g.contas_pagar() if r['saldo_centavos']]
        self._listar_registros('Agenda de vencimentos — ordenada por dia',rows)

    def _liquidar_cartao_ui(self):
        rid=self._selecionado(self.fin_cartoes); r=g.consultar('SELECT * FROM recebiveis_cartao WHERE id=?',(rid,))[0]
        contas=self._contas_opcoes()
        self._formulario('Liquidação de cartão',[('conta','Conta de destino',contas[-1],contas),('taxa','Taxa efetiva (R$)',r['taxa_centavos']/100,None)],lambda v:g.liquidar_cartao(rid,int(v['conta'].split(' — ')[0]),v['taxa']),f"Bruto: {self._moeda(r['bruto_centavos']/100)}. Confirme somente após crédito no banco.")

    def _saldo_inicial_ui(self):
        cid=self._selecionado(self.fin_contas)
        r=g.consultar('SELECT * FROM contas_financeiras WHERE id=?',(cid,))[0]
        self._formulario('Conferir saldo inicial',[('valor','Saldo anterior às movimentações novas (R$)','',None)],lambda v:g.definir_saldo_inicial(cid,v['valor']),f"Conta {r['nome']}. Informe o saldo na data base {r['data_base']}, antes dos movimentos do novo módulo.")

    def _nova_conta_financeira_ui(self):
        def salvar(v):
            g.permitir('financeiro')
            if not v['nome']: raise g.ErroGestao('Informe o nome da conta.')
            with g.transacao() as c:
                c.execute('INSERT INTO contas_financeiras(nome,tipo) VALUES(?,?)',(v['nome'],v['tipo']))
                g.auditar(c,'criar','conta',v['nome'])
        self._formulario('Adicionar conta',[('nome','Nome','',None),('tipo','Tipo','banco',['banco','dinheiro'])],salvar)

    def _movimento_manual_ui(self):
        contas=self._contas_opcoes()
        def salvar(v):
            g.permitir('financeiro'); valor=g.centavos(v['valor'])
            if valor<=0 or not v['descricao']: raise g.ErroGestao('Informe valor positivo e descrição.')
            if v['sentido']=='Saída': valor=-valor
            with g.transacao() as c: g.movimento(c,int(v['conta'].split(' — ')[0]),valor,v['categoria'],v['descricao'],'manual',uuid.uuid4().hex,data=v['data'])
        self._formulario('Outra movimentação financeira',[('sentido','Movimentação','Entrada',['Entrada','Saída']),('conta','Conta',contas[0],contas),('valor','Valor (R$)','',None),('categoria','Categoria','Aporte',['Aporte','Retirada','Outras receitas','Outras despesas','Investimento']),('descricao','Descrição / justificativa','',None),('data','Data',date.today().isoformat(),None)],salvar,'Despesas operacionais devem ser cadastradas em Contas a pagar (competência + caixa). Aporte, Retirada e Transferência NÃO são receita nem despesa. Use "Outras receitas/despesas" só para o que não passa por conta a pagar.')

    def _exportar_dados(self,rows,nome):
        caminho=filedialog.asksaveasfilename(parent=self,defaultextension='.csv',initialfile=nome+'.csv',filetypes=[('CSV','*.csv')])
        if caminho: g.exportar_csv(caminho,rows)

    def _exportar_movimentos(self): self._exportar_dados(self._movimentos_rows,'fluxo_caixa')

    def _listar_registros(self,titulo,rows,acao=None):
        dlg=tk.Toplevel(self); dlg.title(titulo); dlg.geometry('1000x550'); dlg.transient(self)
        ttk.Label(dlg,text=titulo,font=('Segoe UI',16,'bold')).pack(anchor='w',padx=15,pady=12)
        if not rows:
            ttk.Label(dlg,text='Nenhum registro encontrado.').pack(pady=20); return
        cols=list(rows[0])
        tree=self._tabela_gestao(dlg,[(k,k.replace('_',' ').capitalize(),150) for k in cols])
        for i,r in enumerate(rows): tree.insert('','end',iid=i,values=[r[k] for k in cols])
        barra=ttk.Frame(dlg,padding=10); barra.pack(fill='x')
        ttk.Button(barra,text='Exportar CSV',command=lambda:self._executar_gestao(lambda:self._exportar_dados(rows,'relatorio'))).pack(side='left')
        if acao:
            ttk.Button(barra,text='Abrir / executar no selecionado',command=lambda:self._executar_gestao(lambda:acao(rows[self._selecionado(tree)]))).pack(side='right')

    def _cliente_selecionado(self):
        cid=self._selecionado(self.tvcli)
        return op.obter_cliente(cid)

    def _politica_cliente(self): self._politica_ui(self._cliente_selecionado()['id'])

    def _politica_ui(self,cid=None):
        if cid:
            c=db.get_conn()
            try: p=g.politica_cliente(c,cid)
            finally: c.close()
        else: p=g.config('politica_fiado',{})
        self._formulario('Política de fiado'+(' do cliente' if cid else ' padrão'),[('limite_credito','Limite de crédito (R$)',p.get('limite_credito',200),None),('prazo_dias','Prazo em dias',p.get('prazo_dias'),None),('juros_dia','Juros simples por dia (%)',p.get('juros_dia'),None),('multa_dia','Multa por dia de atraso (%)',p.get('multa_dia'),None)],lambda v:g.salvar_politica(cid,**v),
                         'Encargos diários sobre o principal ainda aberto, sem capitalização. A alteração vale para novas vendas; títulos antigos mantêm a regra original.')

    def _detalhes_cliente(self):
        try: cliente=self._cliente_selecionado()
        except Exception as exc: messagebox.showinfo('Cliente',str(exc)); return
        cid=cliente['id']; dlg=tk.Toplevel(self); dlg.title('Cliente — '+cliente['nome']); dlg.geometry('940x650'); dlg.transient(self)
        ttk.Label(dlg,text=cliente['nome'],font=('Segoe UI',19,'bold')).pack(anchor='w',padx=16,pady=12)
        ttk.Label(dlg,text=f"Telefone: {cliente['telefone']}   |   Principal em aberto: {self._moeda(op.saldo_fiado(cid))}").pack(anchor='w',padx=16)
        barra=ttk.Frame(dlg,padding=12); barra.pack(fill='x')
        def acao(func): dlg.destroy(); self._executar_gestao(func)
        for nome,func in [('Receber pagamento',self._receber_fiado),('Nova venda fiado',lambda:self._nova_venda_cliente(cliente)),('Editar cadastro',lambda:self._modal_cliente(cliente)),('Política de crédito',lambda:self._politica_ui(cid)),('Histórico completo',self._ver_consumo_cliente)]:
            ttk.Button(barra,text=nome,command=lambda f=func:acao(f)).pack(side='left',padx=3)
        tree=self._tabela_gestao(dlg,[('venda','Venda',60),('vencimento','Vencimento',105),('principal','Principal aberto',120),('juros','Juros',95),('multa','Multa',95),('status','Situação',155)])
        for t in g.titulos_cliente(cid):
            tree.insert('','end',iid=t['id'],values=(t['venda_id'],t['vencimento'] or 'Conferir',self._moeda(t['saldo_centavos']/100),self._moeda(t['juros_centavos']/100),self._moeda(t['multa_centavos']/100),t['status']+(' / atrasado' if t['atraso'] else '')))
        ttk.Button(dlg,text='Definir vencimento de título legado selecionado',command=lambda:self._executar_gestao(lambda:self._vencimento_legado(self._selecionado(tree)))).pack(pady=6)
        ttk.Button(dlg,text='Recibos / estornar recebimento',command=lambda:self._listar_registros('Recebimentos',g.consultar('SELECT id,data_hora,valor,encargos_centavos,forma_pagamento,tipo,estornado FROM pagamentos_fiado WHERE cliente_id=? ORDER BY id DESC',(cid,)),lambda r:self._recibo_opcoes(r))).pack(pady=6)

    def _vencimento_legado(self,tid):
        def salvar(v):
            g.permitir('credito')
            with g.transacao() as c:
                t=c.execute('SELECT * FROM titulos_receber WHERE id=?',(tid,)).fetchone()
                if not t['legado']: raise g.ErroGestao('Use a política para novas vendas; este título não é legado.')
                c.execute('UPDATE titulos_receber SET vencimento=? WHERE id=?',(g.data_iso(v['vencimento']),tid))
                g.auditar(c,'vencimento_legado','titulo',tid,v)
        self._formulario('Conferir vencimento',[('vencimento','Vencimento acordado','',None)],salvar,'A conferência não aplica encargos retroativos aos títulos antigos.')

    def _nova_venda_cliente(self,cliente):
        self.cliente_fiado=cliente; self.forma.set('fiado'); self.label_cliente.config(text=cliente['nome']); self._atualizar_visibilidade_pagamento(); self.nb.select(self.tab_caixa); self.entrada.focus_set()

    def _abrir_cliente_titulo(self):
        def abrir():
            tid=self._selecionado(self.fin_receber); cid=-tid if tid<0 else g.consultar('SELECT cliente_id FROM titulos_receber WHERE id=?',(tid,))[0]['cliente_id']
            self._carrega_clientes(); self.tvcli.selection_set(str(cid)); self._detalhes_cliente()
        self._executar_gestao(abrir)

    def _receber_fiado(self):
        cli=self._cliente_selecionado(); cid=cli['id']; saldo=op.saldo_fiado(cid)
        if saldo<=0: raise g.ErroGestao('Cliente sem saldo a receber.')
        taxas=self._config_taxas() if hasattr(self,'_config_taxas') else {}
        vouchers=taxas.get('vouchers') or [{'nome':'TICKET','taxa':0},{'nome':'VR/VA','taxa':0},{'nome':'Sodexo','taxa':0},{'nome':'Alelo','taxa':0}]
        nomes_voucher=[v['nome'] for v in vouchers]
        FORMAS=['Dinheiro','Pix','Cartão de crédito','Cartão de débito','Voucher']

        dlg=tk.Toplevel(self); dlg.title('Receber pagamento — '+cli['nome']); dlg.geometry('470x600')
        dlg.configure(bg='#ffffff'); dlg.transient(self); _grab_set_safe(dlg); self._dlg_formulario=dlg
        dlg.resizable(False,False); dlg.bind('<Escape>',lambda e:dlg.destroy())
        frm=ttk.Frame(dlg,padding=16); frm.pack(fill='both',expand=True)
        ttk.Label(frm,text=cli['nome'],font=('Segoe UI',16,'bold')).pack(anchor='w')
        ttk.Label(frm,text=f'Principal em aberto: {self._moeda(saldo)}').pack(anchor='w',pady=(0,12))

        ttk.Label(frm,text='Quanto ele(a) pagou agora (R$)').pack(anchor='w',pady=(6,2))
        var_valor=tk.StringVar(value=f'{saldo:.2f}'.replace('.',','))
        ttk.Entry(frm,textvariable=var_valor).pack(fill='x',ipady=4)

        ttk.Label(frm,text='Forma de pagamento').pack(anchor='w',pady=(10,2))
        var_forma=tk.StringVar(value='Dinheiro')
        cb_forma=ttk.Combobox(frm,textvariable=var_forma,values=FORMAS,state='readonly'); cb_forma.pack(fill='x')

        ttk.Label(frm,text='Bandeira (só para Voucher)').pack(anchor='w',pady=(10,2))
        var_bandeira=tk.StringVar(value=nomes_voucher[0])
        cb_bandeira=ttk.Combobox(frm,textvariable=var_bandeira,values=nomes_voucher,state='disabled'); cb_bandeira.pack(fill='x')

        ttk.Label(frm,text='Encargos (atraso)').pack(anchor='w',pady=(10,2))
        var_enc=tk.StringVar(value='Cobrar encargos calculados')
        ttk.Combobox(frm,textvariable=var_enc,values=['Cobrar encargos calculados','Dispensar encargos (gerente/financeiro)'],state='readonly').pack(fill='x')

        ttk.Label(frm,text='Observação (opcional)').pack(anchor='w',pady=(10,2))
        var_obs=tk.StringVar(); ttk.Entry(frm,textvariable=var_obs).pack(fill='x')

        resumo=tk.Label(frm,text='',justify='left',bg='#ffffff',fg='#173b2d',font=('Consolas',10))
        resumo.pack(anchor='w',pady=(14,4))

        def pct_da_forma():
            f=var_forma.get()
            if f=='Pix': return float(taxas.get('pix',0) or 0)
            if f=='Cartão de crédito': return float(taxas.get('credito',0) or 0)
            if f=='Cartão de débito': return float(taxas.get('debito',0) or 0)
            if f=='Voucher':
                v=next((x for x in vouchers if x['nome']==var_bandeira.get()),None)
                return float((v or {}).get('taxa',0) or 0)
            return 0.0

        def calcular():
            principal=self._para_float(var_valor.get(),0)
            cobrar=var_enc.get()=='Cobrar encargos calculados'
            enc=0
            if cobrar and principal>0:
                restante=g.centavos(principal)
                for t in g.titulos_cliente(cid):
                    usar=min(restante,max(0,t['saldo_centavos']))
                    if usar: enc+=round(t['encargos_centavos']*usar/t['saldo_centavos']); restante-=usar
            pct=pct_da_forma()
            base=principal+enc/100.0
            taxa=round(base*pct/100.0,2)
            return principal, enc, pct, taxa, round(base+taxa,2)

        def atualizar(*_):
            principal,enc,pct,taxa,total=calcular()
            linhas=[f'Principal: {self._moeda(principal)}', f'Encargos: {self._moeda(enc/100)}']
            if pct>0: linhas.append(f'Taxa {var_forma.get()} ({pct}%): {self._moeda(taxa)}')
            linhas.append(f'Total a receber: {self._moeda(total)}')
            resumo.config(text='\n'.join(linhas))

        def toggle_bandeira(*_):
            cb_bandeira.configure(state='readonly' if var_forma.get()=='Voucher' else 'disabled')
            atualizar()

        var_valor.trace_add('write',atualizar)
        var_enc.trace_add('write',atualizar)
        cb_forma.bind('<<ComboboxSelected>>',toggle_bandeira)
        cb_bandeira.bind('<<ComboboxSelected>>',atualizar)
        toggle_bandeira()

        def confirmar():
            principal,enc,pct,taxa,total=calcular()
            if principal<=0:
                messagebox.showerror('Valor','Informe um valor maior que zero.',parent=dlg); return
            cobrar=var_enc.get()=='Cobrar encargos calculados'
            forma=var_forma.get(); obs=var_obs.get().strip()
            if forma=='Voucher': obs=(f'Voucher {var_bandeira.get()} '+obs).strip()
            msg=f"Principal: {self._moeda(principal)}\nEncargos: {self._moeda(enc/100)}"
            if pct>0: msg+=f"\nTaxa {forma} ({pct}%): {self._moeda(taxa)}"
            msg+=f"\nTotal a receber: {self._moeda(total)}\n\nConfirmar o recebimento?"
            try: dlg.lift()
            except Exception: pass
            if not messagebox.askyesno('Confirmar recebimento',msg,parent=dlg): return
            try:
                pid=g.receber_fiado(cid,principal,obs,forma,uuid.uuid4().hex,cobrar,taxa_centavos=g.centavos(taxa))
            except Exception as exc:
                messagebox.showerror('Erro',str(exc),parent=dlg); return
            dlg.destroy()
            self._mostrar_recibo(pid)
            self._atualizar_financeiro()
            self._aba_atualizada()

        bot=ttk.Frame(frm); bot.pack(side='bottom',fill='x',pady=(10,0))
        ttk.Button(bot,text='Confirmar pagamento',command=confirmar).pack(side='right')
        ttk.Button(bot,text='Cancelar',command=dlg.destroy).pack(side='right',padx=8)

    def _mostrar_recibo(self,pid):
        texto=g.recibo_fiado(pid)
        pasta=Path(db.DB_PATH).parent/'recibos'; pasta.mkdir(exist_ok=True)
        (pasta/f'recebimento_{pid}.txt').write_text(texto,encoding='utf-8')
        dlg=tk.Toplevel(self); dlg.title(f'Recibo #{pid}'); dlg.geometry('560x420')
        t=tk.Text(dlg,font=('Consolas',11),wrap='word'); t.pack(fill='both',expand=True); t.insert('1.0',texto); t.config(state='disabled')
        def imprimir():
            from impressora import imprimir_cupom
            imprimir_cupom(texto)
        ttk.Button(dlg,text='Imprimir',command=lambda:self._executar_gestao(imprimir)).pack(pady=10)

    def _recibo_opcoes(self,r):
        self._mostrar_recibo(r['id'])
        if r['tipo']=='recebimento' and not r['estornado'] and g.PERFIL=='gerente':
            if messagebox.askyesno('Estorno','Deseja estornar este recebimento?',parent=self._parent_ativo()): self._pedir_estorno('recebimento',r['id'])

    def _pedir_estorno(self,tipo,rid):
        motivo=simpledialog.askstring('Estorno','Motivo obrigatório:',parent=self)
        if motivo:
            (g.estornar_pagamento if tipo=='pagamento' else g.estornar_recebimento)(rid,motivo); self._atualizar_financeiro()

    def _montar_ferramentas(self):
        ttk.Label(self.tab_gestao,text='Ferramentas de gestão',font=('Segoe UI',20,'bold')).pack(anchor='w',padx=18,pady=16)
        self.ferramentas=ttk.Notebook(self.tab_gestao); self.ferramentas.pack(fill='both',expand=True,padx=12,pady=8)
        grupos=[('Estoque e produção',[
            ('Catálogo, filtros e ações em lote',self._catalogo_gestao),('Conferir duplicatas',self._duplicatas_ui),('Compra com vários produtos',self._compra_varios_ui),('Inventário físico',self._inventario_ui),('Movimentações de estoque',lambda:self._listar_registros('Movimentações',g.consultar('SELECT m.*,p.nome FROM movimentacoes_estoque m JOIN produtos p ON p.id=m.produto_id ORDER BY m.id DESC LIMIT 2000'))),('Perdas e consumo por mês / categoria',self._relatorio_operacional),('Giro e sugestão de reposição',self._reposicao_ui),('Registrar consumo recorrente',self._consumo_recorrente_ui)]),
                ('Financeiro', [('Política padrão do fiado',lambda:self._politica_ui()),('Conciliação bancária CSV',self._conciliacao_ui),('Orçamento mensal',self._orcamento_ui),('Cancelar venda / devolver total',self._cancelar_venda_ui),('Venda com pagamento dividido',self._venda_dividida_ui)]),
                ('Segurança e preferências',[('Cadastrar usuário e perfil',self._novo_usuario_ui),('Trocar usuário',self._login_gestao),('Sair (bloquear)',self._sair_usuario),('Auditoria',self._auditoria_ui),('Backup completo agora',self._backup_completo_ui),('Verificar / restaurar backup',self._restaurar_backup_ui),('Tamanho de fonte',self._fonte_ui)])]
        for nome,acoes in grupos:
            f=ttk.Frame(self.ferramentas,padding=15); self.ferramentas.add(f,text=nome)
            for titulo,func in acoes:
                ttk.Button(f,text=titulo,command=lambda fn=func:self._executar_gestao(fn)).pack(fill='x',pady=6)

    def _catalogo_gestao(self):
        dlg=tk.Toplevel(self); dlg.title('Catálogo e ações em lote'); dlg.geometry('1100x650')
        filtros=ttk.Frame(dlg,padding=10); filtros.pack(fill='x')
        vars={}
        for chave,nome,opcoes in [('busca','Nome / SKU',None),('categoria','Categoria',None),('fornecedor','Fornecedor',None),('situacao','Situação',['Todos','Ativos','Inativos']),('estoque','Estoque',['Todos','Abaixo do mínimo','Zerados','Validade próxima'])]:
            f=ttk.Frame(filtros); f.pack(side='left',padx=4); ttk.Label(f,text=nome).pack(anchor='w')
            vars[chave]=tk.StringVar(value='Todos' if opcoes else '')
            w=ttk.Combobox(f,textvariable=vars[chave],values=opcoes,state='readonly',width=18) if opcoes else ttk.Entry(f,textvariable=vars[chave],width=18)
            w.pack()
        tree=self._tabela_gestao(dlg,[('nome','Produto',220),('sku','SKU',100),('categoria','Categoria',125),('fornecedor','Fornecedor',125),('estoque','Estoque',85),('minimo','Mínimo',70),('preco','Preço',90),('ativo','Ativo',65),('perecivel','Perecível',75)])
        cache={}
        def carregar():
            tree.delete(*tree.get_children()); cache.clear()
            for r in g.consultar('SELECT * FROM produtos ORDER BY nome'):
                if vars['busca'].get() and g.normalizar(vars['busca'].get()) not in g.normalizar(r['nome']+' '+r['sku']+' '+(r['codigo_barras'] or '')): continue
                if vars['categoria'].get().casefold() not in (r['categoria'] or '').casefold(): continue
                if vars['fornecedor'].get().casefold() not in r['fornecedor'].casefold(): continue
                if vars['situacao'].get()=='Ativos' and not r['ativo']: continue
                if vars['situacao'].get()=='Inativos' and r['ativo']: continue
                if vars['estoque'].get()=='Zerados' and r['quantidade_estoque']>0: continue
                if vars['estoque'].get()=='Abaixo do mínimo' and r['quantidade_estoque']>=r['estoque_minimo']: continue
                if vars['estoque'].get()=='Validade próxima' and not g.consultar("SELECT 1 FROM lotes_validade WHERE produto_id=? AND quantidade>0 AND data_validade<=date('now','localtime','+7 days')",(r['id'],)): continue
                cache[r['id']]=r; tree.insert('','end',iid=r['id'],values=(r['nome'],r['sku'],r['categoria'],r['fornecedor'],r['quantidade_estoque'],r['estoque_minimo'],self._moeda(r['preco_venda']),'Sim' if r['ativo'] else 'Não','Sim' if r['perecivel'] else 'Não'))
        ttk.Button(filtros,text='Filtrar',command=carregar).pack(side='left',padx=6)
        def lote(acao):
            ids=[int(i) for i in tree.selection()]
            if not ids: raise g.ErroGestao('Selecione os produtos (Ctrl/clique).')
            if acao=='preco':
                pct=simpledialog.askfloat('Alteração em lote','Percentual de alteração (ex.: 5 ou -5):',parent=dlg)
                if pct is None: return
                previa='\n'.join(f"{cache[i]['nome']}: {self._moeda(cache[i]['preco_venda'])} → {self._moeda(cache[i]['preco_venda']*(1+pct/100))}" for i in ids[:15])
                if not messagebox.askyesno('Prévia',previa+f'\nAplicar em {len(ids)} produto(s)?',parent=dlg): return
                g.alterar_produtos_lote(ids,percentual=pct)
            elif acao=='categoria':
                categoria=simpledialog.askstring('Categoria','Nova categoria:',parent=dlg)
                if categoria: g.alterar_produtos_lote(ids,categoria=categoria)
            else:
                if messagebox.askyesno('Confirmar',f'{acao} {len(ids)} produto(s)?',parent=dlg): g.alterar_produtos_lote(ids,ativo=acao=='Ativar')
            carregar()
        barra=ttk.Frame(dlg,padding=10); barra.pack(fill='x')
        for nome,acao in [('Preço em lote','preco'),('Categoria em lote','categoria'),('Ativar','Ativar'),('Inativar','Inativar')]:
            ttk.Button(barra,text=nome,command=lambda a=acao:self._executar_gestao(lambda:lote(a))).pack(side='left',padx=3)
        ttk.Button(barra,text='Cadastro adicional',command=lambda:self._executar_gestao(lambda:self._produto_extra_ui(self._selecionado(tree),carregar))).pack(side='left',padx=3)
        ttk.Button(barra,text='Histórico de preços',command=lambda:self._executar_gestao(lambda:self._listar_registros('Histórico de preços',g.consultar('SELECT * FROM historico_precos WHERE produto_id=? ORDER BY id DESC',(self._selecionado(tree),))))).pack(side='left',padx=3)
        ttk.Button(barra,text='Promoção',command=lambda:self._executar_gestao(lambda:self._promocao_ui(self._selecionado(tree)))).pack(side='left',padx=3)
        carregar()

    def _produto_extra_ui(self,pid,callback):
        r=op.obter_produto(pid)
        def salvar(v):
            g.permitir('estoque')
            if not v['sku']: raise g.ErroGestao('SKU obrigatório.')
            with g.transacao() as c:
                c.execute('UPDATE produtos SET sku=?,fornecedor=?,perecivel=? WHERE id=?',(v['sku'],v['fornecedor'],int(v['perecivel']=='Sim'),pid)); g.auditar(c,'editar','produto',pid,v)
            callback()
        self._formulario('Cadastro adicional — '+r['nome'],[('sku','SKU interno único',r['sku'],None),('fornecedor','Fornecedor',r['fornecedor'],None),('perecivel','Exigir validade no recebimento?','Sim' if r['perecivel'] else 'Não',['Sim','Não'])],salvar)

    def _promocao_ui(self,pid):
        def salvar(v):
            g.permitir('estoque'); ini=g.data_iso(v['inicio']); fim=g.data_iso(v['fim']); preco=g.centavos(v['preco'])/100
            if fim<ini or preco<0: raise g.ErroGestao('Vigência ou preço inválidos.')
            with g.transacao() as c:
                c.execute('INSERT INTO promocoes(produto_id,inicio,fim,preco) VALUES(?,?,?,?)',(pid,ini,fim,preco)); g.auditar(c,'promoção','produto',pid,v)
        self._formulario('Promoção por período',[('inicio','Início',date.today().isoformat(),None),('fim','Fim',date.today().isoformat(),None),('preco','Preço promocional (R$)','',None)],salvar,'Prevalece o menor preço vigente, sem acumular percentuais de promoção.')

    def _duplicatas_ui(self):
        def consolidar(r):
            if messagebox.askyesno('Conferência física obrigatória',f"Manter {r['nome']} (#{r['principal']}) e inativar {r['nome_similar']} (#{r['duplicado']})?\n\nOs saldos {r['saldo_a']} e {r['saldo_b']} representam estoques FÍSICOS DISTINTOS e podem ser somados?\nSe houver dúvida, cancele e faça inventário."):
                g.consolidar_produtos(r['principal'],r['duplicado'],True)
                messagebox.showinfo('Concluído','Estoque consolidado; histórico original preservado.')
        self._listar_registros('Possíveis duplicatas — revisão obrigatória',g.duplicatas(),consolidar)

    def _produtos_opcoes(self): return [f"{r['id']} — {r['nome']} ({r['unidade']})" for r in op.listar_produtos()]

    def _abrir_registrar_producao(self):
        import producao
        import app as _app
        COR = _app.COR
        FONTE = _app.FONTE
        receitas = producao.listar_receitas()
        if not receitas:
            messagebox.showinfo('Produção', 'Cadastre primeiro uma receita com insumos e rendimento.')
            return

        dlg = tk.Toplevel(self)
        dlg.title('Registrar produção')
        dlg.geometry('640x640')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Registrar produção', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 15, 'bold')).pack(anchor='w', padx=24, pady=(14, 8))

        def campo(rotulo, valor_inicial='', dica=''):
            tk.Label(dlg, text=rotulo, bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(8, 2))
            ent = tk.Entry(dlg, font=(FONTE, 10), relief='solid', bd=1)
            ent.pack(fill='x', padx=24, ipady=4)
            if valor_inicial:
                ent.insert(0, valor_inicial)
            if dica:
                tk.Label(dlg, text=dica, bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 7)).pack(anchor='w', padx=24)
            return ent

        tk.Label(dlg, text='RECEITA', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(8, 2))
        combo = ttk.Combobox(dlg, state='readonly', font=(FONTE, 10), values=[f"{r['id']} — {r['nome']} ({r['unidade']})" for r in receitas])
        combo.current(0)
        combo.pack(fill='x', padx=24)

        ent_mult = campo('QUANTAS VEZES FEZ A RECEITA (ex.: 1, 2, 0.5)', '1')
        ent_rend = campo('RENDIMENTO REAL (vazio = rendimento da receita)', '', 'Quantidade final obtida de verdade.')
        ent_val = campo('VALIDADE DO PRODUTO FINAL (AAAA-MM-DD)')
        ent_resp = campo('RESPONSÁVEL', g.USUARIO)
        ent_obs = campo('OBSERVAÇÕES / QUALIDADE')

        tk.Label(dlg, text='PRÉVIA (insumos, rendimento e custo)', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 10, 'bold')).pack(anchor='w', padx=24, pady=(12, 2))
        lbl_previa = tk.Label(dlg, text='', bg=COR['zebra'], fg=COR['verde2'], font=('Consolas', 9), justify='left',
                              anchor='nw', wraplength=580)
        lbl_previa.pack(fill='both', expand=True, padx=24, pady=(0, 8), ipady=6)
        estado = {'faltando': False, 'inativo': False}

        def atualizar_previa(*_):
            r = receitas[combo.current()]
            mult = self._para_float(ent_mult.get(), 0)
            if mult <= 0:
                lbl_previa.config(text='Informe um multiplicador maior que zero.')
                estado['faltando'] = estado['inativo'] = False
                return
            linhas, custo_total, sem_custo = [], 0.0, 0
            faltando = inativo = False
            for it in r['itens']:
                p = op.obter_produto(it['insumo_id'])
                if not p:
                    linhas.append(f"  ⚠ insumo {it['insumo_id']} não encontrado")
                    faltando = True
                    continue
                nec = round(it['quantidade'] * mult, 4)
                disp = p['quantidade_estoque']
                custo = p['preco_custo']
                if custo and custo > 0:
                    custo_total += nec * custo
                else:
                    sem_custo += 1
                if not p['ativo']:
                    inativo = True
                ok = (disp + 1e-6) >= nec and p['ativo']
                if not ok:
                    faltando = True
                custo_txt = self._moeda(custo) if (custo and custo > 0) else 'custo desconhecido'
                linhas.append(f"  {p['nome']}: precisa {nec:g} {p['unidade']} · disponível {disp:g} · {custo_txt}"
                              + ('' if ok else '  ⚠'))
            rend_prev = round(r['rendimento'] * mult, 3)
            rend_real = self._para_float(ent_rend.get(), 0) or rend_prev
            texto = (f"Rendimento previsto: {rend_prev:g} {r['unidade']}   ·   real: {rend_real:g} {r['unidade']}\n"
                     + '\n'.join(linhas)
                     + f"\nCusto estimado dos insumos: {self._moeda(custo_total)}"
                     + (f"  (+{sem_custo} insumo(s) sem custo)" if sem_custo else ''))
            if faltando:
                texto += '\n⚠ Há insumo com saldo insuficiente ou inativo — a produção será rejeitada.'
            lbl_previa.config(text=texto)
            estado['faltando'] = faltando
            estado['inativo'] = inativo

        combo.bind('<<ComboboxSelected>>', atualizar_previa)
        for e in (ent_mult, ent_rend):
            e.bind('<KeyRelease>', atualizar_previa)
        atualizar_previa()

        # Chave estável por abertura do formulário: duplo clique/reenvio não gera duas produções.
        chave = uuid.uuid4().hex

        def registrar():
            mult = self._para_float(ent_mult.get(), 0)
            if mult <= 0:
                messagebox.showerror('Produção', 'Informe quantas vezes a receita foi feita.', parent=dlg)
                return
            if estado['faltando']:
                messagebox.showerror('Produção',
                                     'Não dá para produzir: há insumo com saldo insuficiente ou inativo.\n'
                                     'Reponha o insumo ou ajuste o multiplicador.', parent=dlg)
                return
            validade = ent_val.get().strip()
            if not validade:
                messagebox.showerror('Produção', 'Informe a validade do produto final.', parent=dlg)
                return
            try:
                g.data_iso(validade)
            except Exception:
                messagebox.showerror('Produção', 'Validade inválida (use AAAA-MM-DD).', parent=dlg)
                return
            receita_id = int(combo.get().split(' — ')[0])
            try:
                r = g.registrar_producao(receita_id, mult, ent_obs.get().strip(), validade,
                                         self._para_float(ent_rend.get(), 0) or None,
                                         ent_resp.get().strip() or g.USUARIO, chave=chave)
            except Exception as exc:
                messagebox.showerror('Produção', str(exc), parent=dlg)
                return
            dlg.destroy()
            self._toast(f"Produção #{r['id']}: {r['quantidade_produzida']:g} de {r['produto_nome']}; "
                        f"custo unitário {self._moeda(r['custo_unitario'])}.")
            self._carrega_producao()
            self._carrega_produtos()

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=(4, 16), side='bottom')
        ttk.Button(botoes, text='REGISTRAR PRODUÇÃO', style='Primary.TButton', command=registrar).pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=6)

    def _abrir_novo_lote_global(self):
        # Cadastro de validade para estoque existente; nova compra usa recebimento integrado.
        produtos=self._produtos_opcoes()
        if not produtos: return
        def salvar(v):
            import validade
            validade.registrar_lote(int(v['produto'].split(' — ')[0]),v['quantidade'],v['validade'],v['observacao'])
        self._formulario('Detalhar estoque existente em lote',[('produto','Produto',produtos[0],produtos),('quantidade','Quantidade já existente no estoque','',None),('validade','Validade','',None),('observacao','Origem / observação','Conferência de lote',None)],salvar,
                         'Esta tela não recebe mercadoria nem aumenta o saldo total. Para compras novas use Receber mercadoria ou Compra com vários produtos.')

    def _receber_mercadoria_ui(self):
        produtos=self._produtos_opcoes()
        if not produtos: raise g.ErroGestao('Cadastre produtos primeiro.')
        contas=self._contas_opcoes(); chave=uuid.uuid4().hex
        def salvar(v):
            pid=int(v['produto'].split(' — ')[0])
            g.receber_compra([dict(produto_id=pid,quantidade=v['quantidade'],custo=v['custo'],validade=v['validade'])],v['fornecedor'],v['documento'],v['vencimento'],v['forma'],int(v['conta'].split(' — ')[0]),chave)
        self._formulario('Receber mercadoria e obrigação',[('produto','Produto',produtos[0],produtos),('quantidade','Quantidade na unidade do produto','',None),('custo','Custo unitário de aquisição (R$)','',None),('validade','Validade (obrigatória para perecível)','',None),('fornecedor','Fornecedor','',None),('documento','Documento / referência única da compra','',None),('vencimento','Vencimento',date.today().isoformat(),None),('forma','Condição','A prazo',['A prazo','À vista']),('conta','Conta de origem (se à vista)',contas[-1],contas)],salvar,
                         'Estoque, lote, custo médio e conta a pagar são registrados juntos. À vista também registra a saída de dinheiro. Para vários itens do mesmo documento, use a compra com vários produtos em Ferramentas.')

    def _inventario_ui(self):
        produtos=self._produtos_opcoes()
        if not produtos: raise g.ErroGestao('Cadastre produtos primeiro.')
        def salvar(v):
            pid=int(v['produto'].split(' — ')[0]); p=op.obter_produto(pid)
            if messagebox.askyesno('Confirmar inventário',f"Saldo atual: {p['quantidade_estoque']}\nContagem: {v['quantidade']}\nConfirmar ajuste?",parent=self._parent_ativo()):
                g.ajustar_estoque(pid,v['quantidade'],'ajuste',v['motivo'],v['validade'] or None)
        self._formulario('Inventário físico',[('produto','Produto',produtos[0],produtos),('quantidade','Quantidade física contada','',None),('motivo','Justificativa da divergência','Inventário periódico',None),('validade','Validade para entrada de diferença perecível','',None)],salvar,
                         'Conte um produto por vez com suas movimentações suspensas. Ajustes de saída reduzem lotes por FEFO; confira a distribuição física dos lotes antes de confirmar.')

    def _compra_varios_ui(self):
        produtos=self._produtos_opcoes()
        if not produtos: raise g.ErroGestao('Cadastre os produtos primeiro.')
        dlg=tk.Toplevel(self);dlg.title('Compra com vários produtos');dlg.geometry('970x570');dlg.transient(self)
        entrada=ttk.Frame(dlg,padding=10);entrada.pack(fill='x')
        variaveis={}
        for chave,rotulo,valor in [('produto','Produto',produtos[0]),('quantidade','Quantidade','1'),('custo','Custo unitário',''),('validade','Validade AAAA-MM-DD','')]:
            f=ttk.Frame(entrada);f.pack(side='left',padx=4);ttk.Label(f,text=rotulo).pack(anchor='w')
            variaveis[chave]=tk.StringVar(value=valor)
            w=ttk.Combobox(f,textvariable=variaveis[chave],values=produtos,state='readonly',width=35) if chave=='produto' else ttk.Entry(f,textvariable=variaveis[chave],width=16)
            w.pack()
        itens=[]
        tree=self._tabela_gestao(dlg,[('produto','Produto',330),('qtd','Quantidade',110),('custo','Custo unitário',130),('validade','Validade',140)])
        def adicionar():
            v={k:x.get() for k,x in variaveis.items()}; pid=int(v['produto'].split(' — ')[0]);qtd=g.quantidade(v['quantidade']);custo=g.centavos(v['custo'])/100
            if custo<0: raise g.ErroGestao('Custo inválido.')
            if v['validade']: g.data_iso(v['validade'])
            itens.append(dict(produto_id=pid,quantidade=qtd,custo=custo,validade=v['validade']))
            tree.insert('','end',iid=len(itens)-1,values=(v['produto'],qtd,self._moeda(custo),v['validade']))
        ttk.Button(entrada,text='Adicionar',command=lambda:self._executar_gestao(adicionar)).pack(side='left',padx=6)
        def remover():
            for i in tree.selection(): itens[int(i)]=None;tree.delete(i)
        def finalizar():
            ativos=[x for x in itens if x]
            if not ativos: raise g.ErroGestao('Adicione os itens da compra.')
            contas=self._contas_opcoes();chave=uuid.uuid4().hex
            total=sum(g.centavos(x['quantidade']*x['custo']) for x in ativos)/100
            def salvar(v):
                g.receber_compra(ativos,v['fornecedor'],v['documento'],v['vencimento'],v['forma'],int(v['conta'].split(' — ')[0]),chave);dlg.destroy()
            self._formulario('Confirmar compra',[('fornecedor','Fornecedor','',None),('documento','Documento único','',None),('vencimento','Vencimento',date.today().isoformat(),None),('forma','Condição','A prazo',['A prazo','À vista']),('conta','Conta (compra à vista)',contas[-1],contas)],salvar,f'{len(ativos)} item(ns). Total: {self._moeda(total)}. Estoque e obrigação serão registrados juntos.')
        barra=ttk.Frame(dlg,padding=10);barra.pack(fill='x')
        ttk.Button(barra,text='Remover selecionados',command=remover).pack(side='left')
        ttk.Button(barra,text='Conferir e registrar compra',command=lambda:self._executar_gestao(finalizar)).pack(side='right')

    def _consumo_recorrente_ui(self):
        produtos=self._produtos_opcoes()
        if not produtos: raise g.ErroGestao('Cadastre os produtos primeiro.')
        # Chave estável por abertura do formulário: duplo clique/reenvio não
        # gera dois consumos. Motivos iguais aos da aba Consumo interno, para a
        # classificação gerencial (operacional/equipe/pessoal) ficar consistente.
        chave=uuid.uuid4().hex
        def salvar(v):
            g.registrar_baixa([dict(produto_id=int(v['produto'].split(' — ')[0]),quantidade=v['quantidade'])],
                              v['motivo'],v['observacao'],False,g.USUARIO,v['centro'],chave)
        self._formulario('Consumo interno confirmado',[('produto','Produto',produtos[0],produtos),('quantidade','Quantidade efetivamente utilizada','',None),('motivo','Finalidade',op.MOTIVOS_CONSUMO[0],op.MOTIVOS_CONSUMO),('centro','Centro de custo (opcional)','',None),('observacao','Observação / referência do período','',None)],
                         salvar,
                         'Use os totais mensais como referência, mas confirme a quantidade real. O sistema não baixa estoque automaticamente por estimativa.')

    def _relatorio_operacional(self):
        rows=g.consultar("""SELECT strftime('%Y-%m',p.data_hora) mes,'Perda' tipo,pr.categoria,p.motivo,COUNT(DISTINCT p.id) ocorrencias,SUM(i.subtotal) custo
            FROM perdas p JOIN itens_perda i ON i.perda_id=p.id JOIN produtos pr ON pr.id=i.produto_id GROUP BY mes,pr.categoria,p.motivo
            UNION ALL SELECT strftime('%Y-%m',p.data_hora),'Consumo interno',pr.categoria,p.motivo,COUNT(DISTINCT p.id),SUM(i.subtotal)
            FROM consumo_interno p JOIN itens_consumo_interno i ON i.consumo_id=p.id JOIN produtos pr ON pr.id=i.produto_id GROUP BY strftime('%Y-%m',p.data_hora),pr.categoria,p.motivo ORDER BY mes DESC""")
        self._listar_registros('Consumo e perdas por mês, categoria e motivo',rows)
        frequentes=g.consultar("SELECT pr.nome,COUNT(DISTINCT p.id) ocorrencias,SUM(i.subtotal) custo FROM perdas p JOIN itens_perda i ON i.perda_id=p.id JOIN produtos pr ON pr.id=i.produto_id WHERE date(p.data_hora)>=date('now','localtime','-30 days') GROUP BY pr.id HAVING COUNT(DISTINCT p.id)>=3")
        if frequentes: self._listar_registros('Alerta: 3 ou mais perdas do produto em 30 dias',frequentes)

    def _reposicao_ui(self):
        rows=g.relatorio_reposicao()
        self._listar_registros('Reposição sugerida para 7 dias — conferir sazonalidade e prazo do fornecedor',rows)

    def _conciliacao_ui(self):
        g.permitir('financeiro')
        dlg=tk.Toplevel(self); dlg.title('Conciliação bancária'); dlg.geometry('1000x650')
        barra=ttk.Frame(dlg,padding=10); barra.pack(fill='x')
        contas=self._contas_opcoes(); conta=tk.StringVar(value=contas[-1]); ttk.Combobox(barra,textvariable=conta,values=contas,state='readonly',width=30).pack(side='left')
        extrato=self._tabela_gestao(dlg,[('data','Data',110),('desc','Extrato bancário pendente',430),('valor','Valor',120)])
        sistema=self._tabela_gestao(dlg,[('data','Data',110),('desc','Movimento do sistema pendente',430),('valor','Valor',120)])
        def carregar():
            cid=int(conta.get().split(' — ')[0]); extrato.delete(*extrato.get_children()); sistema.delete(*sistema.get_children())
            for r in g.consultar('SELECT * FROM extrato_bancario WHERE conta_id=? AND movimento_id IS NULL ORDER BY data',(cid,)):
                extrato.insert('','end',iid=r['id'],values=(r['data'],r['descricao'],self._moeda(r['valor_centavos']/100)))
            for r in g.consultar('SELECT * FROM movimentos_financeiros WHERE conta_id=? AND conciliado=0 ORDER BY data',(cid,)):
                sistema.insert('','end',iid=r['id'],values=(r['data'],r['descricao'],self._moeda(r['valor_centavos']/100)))
        def importar():
            path=filedialog.askopenfilename(filetypes=[('CSV','*.csv')],parent=dlg)
            if path: g.importar_extrato(path,int(conta.get().split(' — ')[0])); carregar()
        def conciliar(): g.conciliar(self._selecionado(extrato),self._selecionado(sistema)); carregar()
        ttk.Button(barra,text='Importar CSV',command=lambda:self._executar_gestao(importar)).pack(side='left',padx=5)
        ttk.Button(barra,text='Atualizar',command=carregar).pack(side='left')
        ttk.Button(barra,text='Conciliar selecionados',command=lambda:self._executar_gestao(conciliar)).pack(side='left',padx=5)
        ttk.Label(dlg,text='CSV: data;descricao;valor;identificador — valores de saída negativos. A importação não cria entradas/saídas.').pack(pady=10)
        carregar()

    def _orcamento_ui(self):
        def salvar(v):
            g.permitir('financeiro'); g.data_iso(v['mes']+'-01')
            with g.transacao() as c: c.execute('INSERT OR REPLACE INTO orcamentos(mes,categoria,valor_centavos) VALUES(?,?,?)',(v['mes'],v['categoria'],g.centavos(v['valor'])))
            rows=g.consultar("SELECT o.mes,o.categoria,o.valor_centavos/100.0 orcado,COALESCE(-SUM(m.valor_centavos),0)/100.0 realizado_caixa FROM orcamentos o LEFT JOIN movimentos_financeiros m ON strftime('%Y-%m',m.data)=o.mes AND m.categoria=o.categoria AND m.valor_centavos<0 GROUP BY o.mes,o.categoria")
            self._listar_registros('Orçado x realizado — despesas pagas',rows)
        self._formulario('Orçamento mensal',[('mes','Mês (AAAA-MM)',date.today().strftime('%Y-%m'),None),('categoria','Categoria','Despesas fixas',['Despesas fixas','Despesas variáveis','Mercadoria para revenda','Investimento']),('valor','Orçamento (R$)','',None)],salvar)

    def _cancelar_venda_ui(self):
        self._formulario('Cancelar venda / devolver integralmente',[('venda','Número da venda','',None),('motivo','Motivo e confirmação de devolução física','',None)],lambda v:g.cancelar_venda(int(v['venda']),v['motivo']),
                         'Estoque e lotes serão devolvidos; valores recebidos serão estornados. Confirme somente se a devolução do dinheiro e dos produtos ocorreu. Venda com fiado recebido exige estorno prévio dos recebimentos.')

    def _venda_dividida_ui(self):
        if not self.carrinho: raise g.ErroGestao('Monte a venda no PDV antes de dividir o pagamento.')
        # Total em centavos, item a item — igual ao back-end, para a soma dos
        # meios de pagamento bater exatamente com o total calculado.
        bruto_c=g.centavos_itens(self.carrinho)
        desc_c=sum(g.centavos(i.get('desconto',0)) for i in self.carrinho)
        total=max(0,bruto_c-desc_c)/100
        formas=['dinheiro','pix','cartao_credito','cartao_debito']; chave=uuid.uuid4().hex
        def salvar(v):
            itens=[{'produto_id':i['produto_id'],'quantidade':i['quantidade']} for i in self.carrinho]
            venda=op.registrar_venda(itens,desconto=desc_c/100,cliente_id=self.cliente_fiado['id'] if self.cliente_fiado else None,chave_operacao=chave,pagamentos=[{'forma':v['forma1'],'valor':v['valor1']},{'forma':v['forma2'],'valor':v['valor2']}])
            self._ultimo_venda=venda['id']; self.carrinho=[]; self.cliente_fiado=None; self.label_cliente.config(text='Nenhum'); self._render_car()
            self._toast(f"Venda #{venda['id']} concluída com pagamento dividido.")
        self._formulario('Pagamento dividido',[('forma1','Primeiro meio','dinheiro',formas),('valor1','Valor do primeiro meio (R$)','',None),('forma2','Segundo meio','pix',formas),('valor2','Valor do segundo meio (R$)','',None)],salvar,f'Total do carrinho: {self._moeda(total)}. A soma precisa coincidir exatamente. Taxas de cartão são conferidas na liquidação.')

    def _novo_usuario_ui(self):
        self._formulario('Cadastrar usuário',[('nome','Nome de acesso','',None),('senha','Senha (mínimo 8 caracteres)','',None),('perfil','Perfil','caixa',list(g.PERMISSOES))],lambda v:g.criar_usuario(**v))

    def _login_gestao(self):
        users=g.consultar('SELECT nome FROM usuarios WHERE ativo=1 ORDER BY nome')
        if not users:
            def criar(v):
                g.criar_usuario(v['nome'],v['senha'],'gerente'); g.autenticar(v['nome'],v['senha']); self._atualizar_identidade()
            dlg=self._formulario('Primeiro acesso — gerente',[('nome','Nome de acesso','',None),('senha','Senha (mínimo 8 caracteres)','',None)],criar,
                                 'Cadastre o gerente para identificar operações e configurar perfis. Não há senha padrão.')
        else:
            def entrar(v):
                if not g.autenticar(v['nome'],v['senha']): raise g.ErroGestao('Usuário ou senha inválidos.')
                self._atualizar_identidade()
            dlg=self._formulario('Entrar no sistema',[('nome','Usuário',users[0]['nome'],[r['nome'] for r in users]),('senha','Senha','',None)],entrar)
        # Fechar o diálogo inicial não libera acesso anônimo.
        if not getattr(self,'_autenticado',False):
            dlg.protocol('WM_DELETE_WINDOW',self.destroy)
            dlg.bind('<Escape>',lambda e:self.destroy())
            for f in dlg.winfo_children():
                for w in f.winfo_children():
                    if isinstance(w,ttk.Button) and w.cget('text')=='Cancelar': w.configure(command=self.destroy)
        def verificar(_=None):
            if g.USUARIO!='Sistema local': self._autenticado=True
        dlg.bind('<Destroy>',verificar,add='+')

    def _sair_usuario(self):
        """Encerra a sessão e volta à tela de login, sem permissões ativas."""
        if not self._senha_configurada():
            return
        if not messagebox.askyesno('Sair', 'Encerrar a sessão atual e bloquear o sistema?'):
            return
        g.sair()
        self._atualizar_identidade()
        self._toast('Sessão encerrada.')
        self._login_gestao()

    def _auditoria_ui(self):
        g.permitir('configurar'); self._listar_registros('Auditoria de operações',g.consultar('SELECT * FROM auditoria ORDER BY id DESC LIMIT 2000'))

    def _backup_completo_ui(self):
        from backup import backup_completo
        destino=backup_completo()
        messagebox.showinfo('Backup','Cópia verificada em:\n'+str(destino))

    def _restaurar_backup_ui(self):
        g.permitir('configurar')
        caminho=filedialog.askopenfilename(filetypes=[('Banco SQLite','*.db')],parent=self)
        if not caminho: return
        from backup import validar_banco, restaurar_backup
        try:
            validar_banco(caminho)
        except Exception as exc:
            messagebox.showerror('Backup inválido', str(exc), parent=self); return
        if not messagebox.askyesno('Restaurar banco', 'Backup validado. Restaurar substituirá o banco atual e encerrará o aplicativo. Uma cópia do estado atual será guardada. Confirmar?'): return
        try:
            seguranca=restaurar_backup(caminho)
        except Exception as exc:
            messagebox.showerror('Falha ao restaurar', str(exc), parent=self); return
        messagebox.showinfo('Restaurado', f'Banco restaurado.\nCópia do estado anterior em:\n{seguranca}\n\nAbra novamente o aplicativo.'); self.destroy()

    def _fonte_ui(self):
        import tkinter.font as tkfont
        tamanho=simpledialog.askinteger('Fonte','Tamanho de fonte (10 a 18):',minvalue=10,maxvalue=18,parent=self)
        if tamanho:
            for nome in ('TkDefaultFont','TkTextFont','TkMenuFont'): tkfont.nametofont(nome).configure(size=tamanho)
            ttk.Style(self).configure('Treeview',font=('Segoe UI',tamanho),rowheight=max(30,tamanho*2+8))
            ttk.Style(self).configure('TButton',font=('Segoe UI',tamanho))
