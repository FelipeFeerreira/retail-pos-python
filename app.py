import os
# Neste ambiente (Ubuntu/XWayland) o daemon de metodo de entrada (IBus) pode
# ficar preso consumindo 100% de CPU. O Tkinter consulta o XIM a cada widget
# criado, e cada consulta espera ~90ms por uma resposta do IBus, deixando a
# interface extremamente lenta (dezenas de segundos para abrir). Como este
# sistema nao usa teclado com metodo de entrada, desativamos o XIM para o Tk.
os.environ['XMODIFIERS'] = '@im=none'

import re
import hashlib
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP

import database as db
import operacoes as op
import analises as an
import importar_planilha as iplan
from backup import backup_diario, registrar_fiado_recente
from impressora import impressoras_windows, imprimir_cupom, testar_impressao, largura_papel, carregar_config, salvar_config
from idioma import T, definir_idioma, idioma_atual
from balanca import LeitorBalanca
from gerar_catalogo import gerar_catalogo_xlsx
from precificacao import gerar_planilha_entrada
import importar_entrada as ientrada
import importar_nfe as nfe
import categorias as catmod
from relatorio_xlsx import gerar_relatorio_xlsx
import cascos
import producao as prod
import validade as val
import gestao as g
from gestao_ui import GestaoMixin
import uuid

COR = {
    'verde': '#1B5240', 'verde2': '#123A2A', 'amarelo': '#F3B22B',
    'vermelho': '#C23B2E', 'papel': '#F5F6F1', 'branco': '#FFFFFF',
    'cinza': '#6B695F', 'linha': '#E2E0D5', 'verdeclaro': '#E4EFE7',
    'vermelhoclaro': '#FBE8E4', 'amareloclaro': '#FDF2DC', 'ambar': '#9A6700',
    'zebra': '#FAFBF7',
}
COR_ESCURO = {
    'verde': '#2E8B62', 'verde2': '#0C2419', 'amarelo': '#F3B22B',
    'vermelho': '#E2725B', 'papel': '#131C17', 'branco': '#1E2A23',
    'cinza': '#94A29A', 'linha': '#2C3A33', 'verdeclaro': '#1F3628',
    'vermelhoclaro': '#47231E', 'amareloclaro': '#46381C', 'ambar': '#D6A84E',
    'zebra': '#202D26',
}
_COR_PADRAO = {
    'verde': '#1B5240', 'verde2': '#123A2A', 'amarelo': '#F3B22B',
    'vermelho': '#C23B2E', 'papel': '#F5F6F1', 'branco': '#FFFFFF',
    'cinza': '#6B695F', 'linha': '#E2E0D5', 'verdeclaro': '#E4EFE7',
    'vermelhoclaro': '#FBE8E4', 'amareloclaro': '#FDF2DC', 'ambar': '#9A6700',
    'zebra': '#FAFBF7',
}


def _aplicar_paleta():
    """Aplica o tema salvo em config.json mutando o dicionário COR."""
    tema = (carregar_config().get('tema') or 'claro')
    global COR
    COR = dict(COR_ESCURO) if tema == 'escuro' else dict(_COR_PADRAO)
FONTE = 'Segoe UI'
# Sentinela pra distinguir "não me diga qual selecionar, mantenha a seleção
# atual" (valor padrão) de "selecione explicitamente nada" (None de verdade).
_MANTER_SELECAO = object()


def _uppercase_ao_digitar(entry):
    """Converte automaticamente o texto do campo para MAIÚSCULAS enquanto a pessoa digita,
    preservando a posição do cursor. Funciona em qualquer tk.Entry/ttk.Combobox editável."""
    def _ao_soltar_tecla(event):
        texto = entry.get()
        maiusculo = texto.upper()
        if texto != maiusculo:
            pos = entry.index(tk.INSERT)
            entry.delete(0, 'end')
            entry.insert(0, maiusculo)
            entry.icursor(pos)
    entry.bind('<KeyRelease>', _ao_soltar_tecla, add='+')


def _grab_set_safe(dlg):
    """Torna o diálogo modal sem quebrar no Linux, onde a janela pode ainda
    não estar visível quando grab_set() é chamado logo após a criação."""
    try:
        dlg.grab_set()
    except tk.TclError:
        pass


def _preencher_tree(tree, linhas, tag_por_linha=None):
    """Preenche uma Treeview com zebra-striping automático, preservando tags extras
    (como 'zero'/'baixo' de estoque) — a zebra some quando a linha já tem outra tag."""
    tree.delete(*tree.get_children())
    tree.tag_configure('par', background=COR['branco'])
    tree.tag_configure('impar', background=COR['zebra'])
    for i, (iid, valores) in enumerate(linhas):
        extra = tag_por_linha(valores) if tag_por_linha else ''
        tag = extra if extra else ('par' if i % 2 == 0 else 'impar')
        tree.insert('', 'end', iid=iid, tags=(tag,), values=valores)


class App(GestaoMixin, tk.Tk):
    def __init__(self):
        # className define o WM_CLASS da janela, para o icone correto aparecer
        # e agrupar na barra de tarefas (dock) do Ubuntu.
        super().__init__(className='Mercadinho')
        # Monta toda a interface com a janela oculta: o Tkinter recalcula o layout
        # a cada widget criado enquanto a janela esta visivel, o que deixava a
        # abertura do sistema muito lenta. So exibimos no final.
        self.withdraw()
        _aplicar_paleta()
        self.title(T('sistema'))
        self.minsize(1000, 600)
        self.configure(bg=COR['papel'])
        self.bind('<F11>', self._alternar_tela_cheia_total)
        self.bind('<Escape>', self._sair_tela_cheia_total)
        self._sem_bordas = False

        db.init_db()
        try:
            backup_diario()
        except Exception:
            pass

        self.carrinho = []
        self.cliente_fiado = None
        self.quantidade_pendente = None
        self.alertados_zero = set()
        self.alertados_baixo = set()
        self.produtos_cache = {}
        self._resultados = []
        self.forma = tk.StringVar(value='dinheiro')
        self._ultimo_venda = None
        self.janela_cliente = None
        self._visor_agradecendo = False

        self.carrinho_consumo = []
        self.quantidade_pendente_consumo = None
        self._resultados_consumo = []

        self.carrinho_perda = []
        self.quantidade_pendente_perda = None
        self._resultados_perda = []

        self.protocol('WM_DELETE_WINDOW', self._fechar)
        self._style()
        self._iniciar_balanca()
        self._menu()
        self._topo()
        self._notebook()
        self._montar_caixa()
        self._montar_produtos()
        self._montar_clientes()
        self._montar_consumo()
        self._montar_perdas()
        self._montar_producao()
        self._montar_painel()
        self._montar_analises()
        self._montar_estoque()
        self._montar_historico()
        self._montar_configuracoes()
        self._montar_gestao()
        self._atalhos()
        self._relogio()
        self.deiconify()
        self._tela_cheia()
        self.lift()
        self.after(1000, self._tarefas_30min)
        self.after(200, self._login_gestao)
        self.entrada.focus_set()

    def _iniciar_balanca(self):
        conf = carregar_config()
        porta = conf.get('balanca_porta', '')
        protocolo = conf.get('balanca_protocolo', 'P05A (Toledo 8217)')
        baudrate = conf.get('balanca_baudrate')
        parity = conf.get('balanca_parity')
        self.balanca = (LeitorBalanca.criar_para_toledo_8217(porta, protocolo, baudrate=baudrate, parity=parity)
                        if porta else LeitorBalanca())
        self._balanca_status = 'Balança: não configurada'
        if porta:
            ok = self.balanca.iniciar()
            self._balanca_status = f'Balança {porta} conectada' if ok else f'Balança {porta}: {self.balanca.erro}'

    def _config_balanca(self):
        portas = LeitorBalanca.portas_disponiveis()
        conf = carregar_config()
        dlg = tk.Toplevel(self)
        dlg.title('Configurar balança')
        dlg.geometry('620x560')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.bind('<Escape>', lambda e: (dlg.destroy(), self._iniciar_balanca()))

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Balança Toledo 8217 (Prix)', bg=COR['branco'], fg=COR['verde2'],
                 font=(FONTE, 15, 'bold')).pack(anchor='w', padx=20, pady=(14, 2))
        tk.Label(dlg, text='Na balança, use o protocolo P05A (parâmetro C09) e o mesmo baud rate configurado aqui (C10, padrão de fábrica 2400).',
                 bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8), wraplength=560, justify='left').pack(anchor='w', padx=20)

        tk.Label(dlg, text='PORTA SERIAL', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=20, pady=(14, 3))
        dispositivos = [f"{p['device']} — {p['descricao']}" for p in portas]
        var_porta = tk.StringVar(value=conf.get('balanca_porta', ''))
        combo = ttk.Combobox(dlg, textvariable=var_porta, values=dispositivos)
        combo.pack(fill='x', padx=20)
        _uppercase_ao_digitar(combo)
        if not dispositivos:
            tk.Label(dlg, text='Nenhuma porta detectada — digite manualmente (Windows: COM3; Linux: /dev/ttyUSB0).',
                     bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8), wraplength=560, justify='left').pack(anchor='w', padx=20, pady=(4, 0))

        linha = tk.Frame(dlg, bg=COR['branco'])
        linha.pack(fill='x', padx=20, pady=(14, 0))
        col_proto = tk.Frame(linha, bg=COR['branco'])
        col_proto.pack(side='left', fill='x', expand=True, padx=(0, 8))
        tk.Label(col_proto, text='PROTOCOLO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w')
        var_proto = tk.StringVar(value=conf.get('balanca_protocolo', 'P05A (Toledo 8217)'))
        ttk.Combobox(col_proto, textvariable=var_proto, values=list(LeitorBalanca.PROTOCOLOS.keys()), state='readonly').pack(fill='x')
        col_baud = tk.Frame(linha, bg=COR['branco'])
        col_baud.pack(side='left', padx=(0, 8))
        tk.Label(col_baud, text='BAUD RATE', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w')
        var_baud = tk.StringVar(value=str(conf.get('balanca_baudrate', 2400)))
        ttk.Combobox(col_baud, textvariable=var_baud, values=[str(b) for b in LeitorBalanca.BAUDRATES], state='readonly', width=8).pack()
        col_par = tk.Frame(linha, bg=COR['branco'])
        col_par.pack(side='left')
        tk.Label(col_par, text='PARIDADE', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w')
        var_par = tk.StringVar(value=LeitorBalanca.PARIDADES.get(conf.get('balanca_parity', 'N'), 'Nenhuma'))
        ttk.Combobox(col_par, textvariable=var_par, values=list(LeitorBalanca.PARIDADES.values()), state='readonly', width=9).pack()

        lbl_peso = tk.Label(dlg, text='Peso: — kg', bg=COR['verdeclaro'], fg=COR['verde2'], font=('Consolas', 16, 'bold'))
        lbl_peso.pack(fill='x', padx=20, pady=(14, 4), ipady=6)
        lbl_bruto = tk.Label(dlg, text='Bytes recebidos: (nenhum ainda)', bg=COR['branco'], fg=COR['cinza'],
                             font=('Consolas', 8), anchor='w', justify='left', wraplength=560)
        lbl_bruto.pack(fill='x', padx=20)
        resultado = tk.Label(dlg, text='', bg=COR['branco'], fg=COR['cinza'], justify='left', anchor='w', wraplength=560)
        resultado.pack(fill='x', padx=20, pady=(8, 0))

        def extrair_porta(texto):
            return texto.split(' — ', 1)[0].strip() if texto else ''

        def _paridade_codigo():
            for cod, nome in LeitorBalanca.PARIDADES.items():
                if nome == var_par.get():
                    return cod
            return 'N'

        def _mostrar_peso(peso):
            try:
                dlg.after(0, lambda: lbl_peso.config(text=f'Peso: {peso:.3f} kg'))
            except tk.TclError:
                pass

        def _mostrar_bruto(dados):
            def _upd():
                try:
                    legivel = (dados.decode('ascii', errors='replace')
                               .replace('\x02', '<STX>').replace('\x03', '<ETX>').replace('\r', '<CR>'))
                    hexa = ' '.join(f'{b:02X}' for b in dados[:24])
                    lbl_bruto.config(text=f'Bytes: {hexa}\nTexto: {legivel[:80]}')
                except tk.TclError:
                    pass
            try:
                dlg.after(0, _upd)
            except tk.TclError:
                pass

        def testar():
            porta = extrair_porta(var_porta.get())
            if not porta:
                resultado.config(text='Informe uma porta.', fg=COR['vermelho'])
                return
            self.balanca.parar()
            self.balanca = LeitorBalanca.criar_para_toledo_8217(
                porta, var_proto.get(), callback_peso=_mostrar_peso,
                baudrate=int(var_baud.get()), parity=_paridade_codigo(), callback_bruto=_mostrar_bruto)
            ok = self.balanca.iniciar()
            if ok:
                resultado.config(text=f'✓ Conectada em {porta}. Coloque um peso na balança e aguarde aparecer acima.', fg=COR['verde'])
            else:
                resultado.config(text=f'✗ Não conectou: {self.balanca.erro}', fg=COR['vermelho'])

        def salvar():
            porta = extrair_porta(var_porta.get())
            salvar_config({'balanca_porta': porta, 'balanca_protocolo': var_proto.get(),
                           'balanca_baudrate': int(var_baud.get()), 'balanca_parity': _paridade_codigo()})
            dlg.destroy()
            self._iniciar_balanca()
            self._toast('Configuração da balança salva')

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=20, pady=(12, 16), side='bottom')
        ttk.Button(botoes, text='Testar conexão', style='Secondary.TButton', command=testar).pack(side='left')
        ttk.Button(botoes, text='Salvar', style='Primary.TButton', command=salvar).pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton',
                   command=lambda: (dlg.destroy(), self._iniciar_balanca())).pack(side='right', padx=6)

    def _validar_nome(self, texto_proposto):
        return bool(re.fullmatch(r'[A-Za-zÀ-ÿ0-9 ]*', texto_proposto))

    def _validar_codigo(self, texto_proposto):
        return texto_proposto == '' or texto_proposto.isdigit()

    def _tela_cheia(self):
        largura = self.winfo_screenwidth()
        altura = self.winfo_screenheight()
        self.geometry(f'{largura}x{altura}+0+0')
        try:
            self.state('zoomed')
        except tk.TclError:
            try:
                self.attributes('-zoomed', True)
            except tk.TclError:
                pass

    def _alternar_tela_cheia_total(self, event=None):
        self._sem_bordas = not self._sem_bordas
        self.attributes('-fullscreen', self._sem_bordas)
        if not self._sem_bordas:
            self._tela_cheia()

    def _sair_tela_cheia_total(self, event=None):
        if self._sem_bordas:
            self._sem_bordas = False
            self.attributes('-fullscreen', False)
            self._tela_cheia()

    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use('clam')
        except tk.TclError:
            pass
        F = FONTE
        s.configure('TNotebook', background=COR['papel'], borderwidth=0)
        s.configure('TNotebook.Tab', padding=(22, 12), font=(F, 11, 'bold'),
                    background=COR['verdeclaro'], foreground=COR['verde2'])
        s.map('TNotebook.Tab',
              background=[('selected', COR['amarelo'])],
              foreground=[('selected', COR['verde2'])])
        s.configure('Treeview', font=(F, 10), rowheight=30, fieldbackground=COR['branco'],
                    background=COR['branco'], borderwidth=0)
        s.configure('Treeview.Heading', font=(F, 9, 'bold'), background=COR['verdeclaro'],
                    foreground=COR['verde2'], relief='flat', padding=(8, 8))
        s.map('Treeview', background=[('selected', COR['verde'])], foreground=[('selected', 'white')])
        # Estilo maior/mais legível só para o carrinho da venda atual: letra e linhas maiores,
        # para dar pra ver bem os produtos, a quantidade e o subtotal de vários itens de uma vez.
        s.configure('Carrinho.Treeview', font=(F, 12), rowheight=34, fieldbackground=COR['branco'],
                    background=COR['branco'], borderwidth=0)
        s.configure('Carrinho.Treeview.Heading', font=(F, 10, 'bold'), background=COR['verdeclaro'],
                    foreground=COR['verde2'], relief='flat', padding=(8, 8))
        s.map('Carrinho.Treeview', background=[('selected', COR['verde'])], foreground=[('selected', 'white')])
        s.configure('TButton', font=(F, 10, 'bold'), padding=8)
        s.configure('TRadiobutton', background=COR['branco'], font=(F, 10))
        s.configure('TCombobox', font=(F, 10))
        s.configure('Primary.TButton', font=(F, 13, 'bold'), padding=14,
                    background=COR['verde'], foreground='white', borderwidth=0)
        s.map('Primary.TButton',
              background=[('active', COR['verde2']), ('pressed', COR['verde2'])],
              foreground=[('active', 'white'), ('pressed', 'white')])
        s.configure('Secondary.TButton', font=(F, 10), padding=8,
                    background=COR['verdeclaro'], foreground=COR['verde2'])
        s.map('Secondary.TButton', background=[('active', '#D3E5D8')])

    def _menu(self):
        m = tk.Menu(self)
        ar = tk.Menu(m, tearoff=0)
        ar.add_command(label=T('backup_agora'), command=self._backup_manual)
        ar.add_command(label=T('configurar_impressora'), command=self._config_impressora)
        ar.add_command(label=T('configurar_balanca'), command=self._config_balanca)
        ar.add_separator()
        ar.add_command(label=T('abrir_tela_cliente'), command=self._abrir_visor_cliente)
        ar.add_command(label=T('gerar_catalogo'), command=self._gerar_catalogo)
        ar.add_separator()
        ar.add_command(label=T('gerar_planilha_entrada'), command=self._gerar_entrada_mercadoria)
        ar.add_command(label=T('importar_entrada'), command=self._importar_entrada_mercadoria)
        ar.add_command(label=T('importar_nfe'), command=self._importar_nfe)
        ar.add_command(label=T('revisar_categorias'), command=self._revisar_categorias)
        ar.add_command(label=T('exportar_relatorio'), command=self._exportar_relatorio)
        ar.add_separator()
        ar.add_command(label=T('alterar_senha_menu'), command=lambda: self._definir_senha(alterar=self._senha_configurada()))
        ar.add_separator()
        ar.add_command(label=T('sair'), command=self._fechar)
        m.add_cascade(label=T('arquivo'), menu=ar)
        aj = tk.Menu(m, tearoff=0)
        aj.add_command(label=T('atalhos_do_teclado'), command=self._ajuda_atalhos)
        m.add_cascade(label=T('ajuda'), menu=aj)
        self.config(menu=m)

    def _topo(self):
        f = tk.Frame(self, bg=COR['verde2'], height=58)
        f.pack(fill='x')
        f.pack_propagate(False)
        marca = tk.Frame(f, bg=COR['verde2'])
        marca.pack(side='left', padx=22)
        tk.Label(marca, text='🧺', bg=COR['verde2'], font=('Segoe UI Emoji', 18)).pack(side='left')
        tk.Label(marca, text=' FMG', bg=COR['verde2'], fg='white', font=(FONTE, 18, 'bold')).pack(side='left')
        tk.Label(marca, text='  ' + T('mercadinho').upper(), bg=COR['verde2'], fg='#B8D0C2', font=(FONTE, 11)).pack(side='left', pady=(6, 0))
        tk.Label(f, text='F11: tela cheia total', bg=COR['verde2'], fg='#6E9683', font=(FONTE, 8)).place(relx=0.5, rely=0.5, anchor='center')
        self.status = tk.Label(f, text=T('status_sqlite'), bg=COR['verde2'], fg='#B8D0C2', font=(FONTE, 9))
        self.status.pack(side='right', padx=22)
        tk.Frame(self, bg=COR['amarelo'], height=3).pack(fill='x')

    def _notebook(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill='both', expand=True, padx=14, pady=14)
        self.tab_caixa = tk.Frame(self.nb, bg=COR['papel'])
        self.tab_prod = tk.Frame(self.nb, bg=COR['papel'])
        self.tab_cli = tk.Frame(self.nb, bg=COR['papel'])
        self.tab_consumo = tk.Frame(self.nb, bg=COR['papel'])
        self.tab_perdas = tk.Frame(self.nb, bg=COR['papel'])
        self.tab_producao = tk.Frame(self.nb, bg=COR['papel'])
        self.tab_pain = tk.Frame(self.nb, bg=COR['papel'])
        self.tab_analises = tk.Frame(self.nb, bg=COR['papel'])
        self.tab_hist = tk.Frame(self.nb, bg=COR['papel'])
        self.tab_estoque = tk.Frame(self.nb, bg=COR['papel'])
        self.tab_config = tk.Frame(self.nb, bg=COR['papel'])
        for i, (tab, nome) in enumerate([
            (self.tab_caixa, 'tab_caixa'), (self.tab_prod, 'tab_produtos'),
            (self.tab_cli, 'tab_clientes'), (self.tab_consumo, 'tab_consumo'),
            (self.tab_perdas, 'tab_perdas'), (self.tab_producao, 'tab_producao'),
            (self.tab_pain, 'tab_painel'), (self.tab_analises, 'tab_analises'),
            (self.tab_hist, 'tab_historico'), (self.tab_estoque, 'tab_estoque'),
            (self.tab_config, 'tab_configuracoes')
        ]):
            self.nb.add(tab, text=f' {T(nome)} ')
        self.nb.bind('<<NotebookTabChanged>>', lambda e: self._atualizar_aba_selecionada())

    def _config_taxas(self):
        conf = carregar_config()
        return {
            'credito': conf.get('taxa_credito', 0),
            'debito': conf.get('taxa_debito', 0),
            'pix': conf.get('taxa_pix', 0.5),
            'vouchers': conf.get('vouchers', [{'nome': 'Alelo', 'taxa': 4.0}, {'nome': 'Sodexo', 'taxa': 4.0}, {'nome': 'VR/VA', 'taxa': 4.0}]),
        }

    def _montar_configuracoes(self):
        for w in self.tab_config.winfo_children():
            w.destroy()
        p = self.tab_config
        p.columnconfigure(0, weight=1)
        self.label_config = tk.Label(p, text=T('config_titulo'), bg=COR['papel'], fg=COR['verde2'], font=(FONTE, 20, 'bold'))
        self.label_config.grid(row=0, column=0, sticky='w', pady=(0, 14))

        bloco_taxas = tk.Frame(p, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_taxas.grid(row=1, column=0, sticky='ew', pady=(0, 16))
        tk.Label(bloco_taxas, text=T('taxas_maquininha'), bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 13, 'bold')).pack(anchor='w', padx=20, pady=(16, 10))
        linha_taxas = tk.Frame(bloco_taxas, bg=COR['branco'])
        linha_taxas.pack(fill='x', padx=20, pady=(0, 18))
        conf = self._config_taxas()

        tk.Label(linha_taxas, text='CARTÃO DE CRÉDITO (%)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).grid(row=0, column=0, sticky='w', padx=(0, 30))
        tk.Label(linha_taxas, text='CARTÃO DE DÉBITO (%)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).grid(row=0, column=1, sticky='w', padx=(0, 30))
        tk.Label(linha_taxas, text='PIX (%)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).grid(row=0, column=2, sticky='w')
        self.entrada_taxa_credito = tk.Entry(linha_taxas, font=('Consolas', 12), relief='solid', bd=1, width=10)
        self.entrada_taxa_credito.insert(0, str(conf['credito']))
        self.entrada_taxa_credito.grid(row=1, column=0, sticky='w', padx=(0, 30), pady=(4, 0), ipady=4)
        self.entrada_taxa_debito = tk.Entry(linha_taxas, font=('Consolas', 12), relief='solid', bd=1, width=10)
        self.entrada_taxa_debito.insert(0, str(conf['debito']))
        self.entrada_taxa_debito.grid(row=1, column=1, sticky='w', padx=(0, 30), pady=(4, 0), ipady=4)
        self.entrada_taxa_pix = tk.Entry(linha_taxas, font=('Consolas', 12), relief='solid', bd=1, width=10)
        self.entrada_taxa_pix.insert(0, str(conf['pix']))
        self.entrada_taxa_pix.grid(row=1, column=2, sticky='w', pady=(4, 0), ipady=4)
        for _campo_taxa in (self.entrada_taxa_credito, self.entrada_taxa_debito, self.entrada_taxa_pix):
            _uppercase_ao_digitar(_campo_taxa)
        tk.Label(bloco_taxas, text='A taxa de Pix não é cobrada do cliente — ela só é descontada do lucro estimado do Painel, como o custo da maquininha/conta ao receber por Pix.',
                 bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8), wraplength=560, justify='left').pack(anchor='w', padx=20, pady=(8, 0))

        def salvar_taxas():
            try:
                credito = self._para_float(self.entrada_taxa_credito.get(), 0)
                debito = self._para_float(self.entrada_taxa_debito.get(), 0)
                pix = self._para_float(self.entrada_taxa_pix.get(), 0)
                salvar_config({'taxa_credito': credito, 'taxa_debito': debito, 'taxa_pix': pix})
                self._toast('Taxas salvas')
            except Exception as exc:
                messagebox.showerror('Erro', str(exc))
        ttk.Button(bloco_taxas, text=T('salvar_taxas'), style='Primary.TButton', command=salvar_taxas).pack(anchor='w', padx=20, pady=(0, 16))

        bloco_vouchers = tk.Frame(p, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_vouchers.grid(row=2, column=0, sticky='ew')
        cab_v = tk.Frame(bloco_vouchers, bg=COR['branco'])
        cab_v.pack(fill='x', padx=20, pady=(16, 10))
        tk.Label(cab_v, text=T('vouchers_aceitos'), bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 13, 'bold')).pack(side='left')
        ttk.Button(cab_v, text=T('adicionar_voucher'), style='Secondary.TButton', command=lambda: self._modal_voucher()).pack(side='right')

        self.frame_vouchers = tk.Frame(bloco_vouchers, bg=COR['branco'])
        self.frame_vouchers.pack(fill='x', padx=20, pady=(0, 18))
        self._carregar_vouchers_config()

        conf_atual = carregar_config()

        bloco_aparencia = tk.Frame(p, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_aparencia.grid(row=3, column=0, sticky='ew', pady=(16, 0))
        tk.Label(bloco_aparencia, text=T('apar_idioma'), bg=COR['branco'], fg=COR['verde2'],
                 font=(FONTE, 13, 'bold')).pack(anchor='w', padx=20, pady=(16, 10))

        linha_tema = tk.Frame(bloco_aparencia, bg=COR['branco'])
        linha_tema.pack(fill='x', padx=20, pady=(0, 4))
        tk.Label(linha_tema, text=T('tema') + ':', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9)).pack(side='left')
        tema_var = tk.StringVar(value=conf_atual.get('tema') or 'claro')
        ttk.Radiobutton(linha_tema, text=T('tema_claro'), value='claro', variable=tema_var,
                        command=lambda: self._trocar_tema(tema_var.get())).pack(side='left', padx=(14, 0))
        ttk.Radiobutton(linha_tema, text=T('tema_escuro'), value='escuro', variable=tema_var,
                        command=lambda: self._trocar_tema(tema_var.get())).pack(side='left', padx=(10, 0))

        linha_idioma = tk.Frame(bloco_aparencia, bg=COR['branco'])
        linha_idioma.pack(fill='x', padx=20, pady=(10, 4))
        tk.Label(linha_idioma, text=T('idioma') + ':', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9)).pack(side='left')
        idioma_var = tk.StringVar(value=idioma_atual())
        def _trocar_idioma(codigo):
            self._escolher_idioma(codigo)
            idioma_var.set(codigo)
        ttk.Radiobutton(linha_idioma, text='Português', value='pt', variable=idioma_var,
                        command=lambda: _trocar_idioma('pt')).pack(side='left', padx=(14, 0))
        ttk.Radiobutton(linha_idioma, text='English', value='en', variable=idioma_var,
                        command=lambda: _trocar_idioma('en')).pack(side='left', padx=(10, 0))
        tk.Label(bloco_aparencia, text=T('nota_reiniciar'), bg=COR['branco'], fg=COR['cinza'],
                 font=(FONTE, 8), wraplength=560, justify='left').pack(anchor='w', padx=20, pady=(8, 16))

        bloco_vendas = tk.Frame(p, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_vendas.grid(row=4, column=0, sticky='ew', pady=(16, 0))
        tk.Label(bloco_vendas, text='Vendas', bg=COR['branco'], fg=COR['verde2'],
                 font=(FONTE, 13, 'bold')).pack(anchor='w', padx=20, pady=(16, 10))
        permitir_neg_var = tk.BooleanVar(value=bool(g.config('permitir_estoque_negativo', False)))
        def _toggle_estoque_negativo():
            try:
                g.salvar_config('permitir_estoque_negativo', bool(permitir_neg_var.get()))
                self._toast(T('preferencias_salvas'))
            except Exception as exc:
                messagebox.showerror('Erro', str(exc))
        tk.Checkbutton(bloco_vendas, text=T('vender_sem_estoque'), variable=permitir_neg_var,
                       bg=COR['branco'], fg=COR['verde2'], activebackground=COR['branco'],
                       selectcolor=COR['branco'], font=(FONTE, 10),
                       command=_toggle_estoque_negativo).pack(anchor='w', padx=20)
        tk.Label(bloco_vendas, text=T('vender_sem_estoque_dica'), bg=COR['branco'], fg=COR['cinza'],
                 font=(FONTE, 8), wraplength=560, justify='left').pack(anchor='w', padx=20, pady=(2, 16))

        bloco_seguranca = tk.Frame(p, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_seguranca.grid(row=5, column=0, sticky='ew', pady=(16, 0))
        tk.Label(bloco_seguranca, text=T('seguranca'), bg=COR['branco'], fg=COR['verde2'],
                 font=(FONTE, 13, 'bold')).pack(anchor='w', padx=20, pady=(16, 10))
        ttk.Button(bloco_seguranca, text=T('alterar_senha') if self._senha_configurada() else T('definir_senha'),
                   style='Primary.TButton',
                   command=lambda: self._definir_senha(alterar=self._senha_configurada())).pack(anchor='w', padx=20, pady=(0, 8))
        tk.Label(bloco_seguranca, text=(T('dica_com_senha') if self._senha_configurada() else T('dica_sem_senha')),
                 bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8), wraplength=560,
                 justify='left').pack(anchor='w', padx=20, pady=(0, 18))

    def _trocar_tema(self, tema):
        salvar_config({'tema': tema})
        self._aplicar_tema(tema)
        self._aba_atualizada()
        self._toast(T('preferencias_salvas'))

    def _carregar_vouchers_config(self):
        for w in self.frame_vouchers.winfo_children():
            w.destroy()
        vouchers = self._config_taxas()['vouchers']
        if not vouchers:
            tk.Label(self.frame_vouchers, text=T('nenhum_voucher'), bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 10)).pack(anchor='w')
            return
        for i, v in enumerate(vouchers):
            linha = tk.Frame(self.frame_vouchers, bg=COR['zebra'] if i % 2 else COR['branco'])
            linha.pack(fill='x', pady=2)
            tk.Label(linha, text=v['nome'], bg=linha['bg'], fg=COR['verde2'], font=(FONTE, 10, 'bold')).pack(side='left', padx=10, pady=6)
            tk.Label(linha, text=f"{v['taxa']}%", bg=linha['bg'], fg=COR['cinza'], font=('Consolas', 10)).pack(side='left', padx=10)
            ttk.Button(linha, text='Editar', style='Secondary.TButton', command=lambda v=v: self._modal_voucher(v)).pack(side='right', padx=(4, 10))
            ttk.Button(linha, text='Remover', style='Secondary.TButton', command=lambda v=v: self._remover_voucher(v)).pack(side='right')

    def _modal_voucher(self, voucher=None):
        dlg = tk.Toplevel(self)
        dlg.title('Editar voucher' if voucher else 'Novo voucher')
        dlg.geometry('380x300')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())
        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Editar voucher' if voucher else 'Novo voucher', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 14, 'bold')).pack(anchor='w', padx=22, pady=(14, 10))
        tk.Label(dlg, text='NOME (ex.: Alelo, Sodexo, VR)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=22)
        ent_nome = tk.Entry(dlg, font=(FONTE, 11), relief='solid', bd=1)
        ent_nome.pack(fill='x', padx=22, ipady=5)
        _uppercase_ao_digitar(ent_nome)
        tk.Label(dlg, text='TAXA (%)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=22, pady=(12, 3))
        ent_taxa = tk.Entry(dlg, font=(FONTE, 11), relief='solid', bd=1)
        ent_taxa.pack(fill='x', padx=22, ipady=5)
        _uppercase_ao_digitar(ent_taxa)
        if voucher:
            ent_nome.insert(0, voucher['nome'])
            ent_taxa.insert(0, str(voucher['taxa']))

        def salvar():
            nome = ent_nome.get().strip()
            if not nome:
                messagebox.showerror('Erro', 'Informe o nome do voucher.', parent=dlg)
                return
            taxa = self._para_float(ent_taxa.get(), 0)
            vouchers = self._config_taxas()['vouchers']
            if voucher:
                vouchers = [v for v in vouchers if v['nome'] != voucher['nome']]
            vouchers = [v for v in vouchers if v['nome'].lower() != nome.lower()]
            vouchers.append({'nome': nome, 'taxa': taxa})
            salvar_config({'vouchers': vouchers})
            dlg.destroy()
            self._carregar_vouchers_config()
            self._toast('Voucher salvo')
        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=22, pady=20, side='bottom')
        ttk.Button(botoes, text='Salvar', style='Primary.TButton', command=salvar).pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))

    def _remover_voucher(self, voucher):
        if not messagebox.askyesno('Remover voucher', f'Remover "{voucher["nome"]}" da lista?'):
            return
        vouchers = [v for v in self._config_taxas()['vouchers'] if v['nome'] != voucher['nome']]
        salvar_config({'vouchers': vouchers})
        self._carregar_vouchers_config()

    def _montar_caixa(self):
        p = self.tab_caixa
        # Venda atual (coluna 0, à esquerda) domina a tela — é o que o cliente precisa ver
        # bem: produto, quantidade, subtotal e total. Busca/bipar (coluna 1, à direita) fica
        # bem mais estreita, cortada praticamente pela metade, só com espaço pro código de
        # barras e a lista de resultados da busca.
        p.columnconfigure(0, weight=8)
        p.columnconfigure(1, weight=2)
        p.rowconfigure(1, weight=1)

        cab = tk.Frame(p, bg=COR['papel'])
        cab.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 10))
        cab.columnconfigure(0, weight=1)
        self.label_caixa = tk.Label(cab, text=T('caixa_titulo'), bg=COR['papel'], fg=COR['verde2'], font=(FONTE, 20, 'bold'))
        self.label_caixa.grid(row=0, column=0, sticky='w')
        self.label_alerta = tk.Label(cab, text='', bg=COR['papel'], fg=COR['vermelho'], font=(FONTE, 10, 'bold'))
        self.label_alerta.grid(row=0, column=1, sticky='e')
        ttk.Button(cab, text='🖥 ' + T('tela_do_cliente'), style='Secondary.TButton', command=self._abrir_visor_cliente).grid(row=0, column=2, sticky='e', padx=(10, 0))

        esq = tk.Frame(p, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        esq.grid(row=1, column=1, sticky='nsew', padx=(10, 0))
        esq.rowconfigure(2, weight=1)
        esq.columnconfigure(0, weight=1)
        tk.Label(esq, text=T('buscar_bipar'), bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9, 'bold')).grid(row=0, column=0, sticky='w', padx=16, pady=(16, 5))
        self.entrada = tk.Entry(esq, font=(FONTE, 15), relief='solid', bd=1,
                                 highlightthickness=2, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        self.entrada.grid(row=1, column=0, sticky='ew', padx=16, pady=(0, 12), ipady=8)
        self.entrada.bind('<KeyRelease>', self._busca_tecla)
        self.entrada.bind('<Return>', self._enter_busca)
        self.entrada.bind('<Down>', self._seta)
        self.entrada.bind('<Up>', self._seta)
        _uppercase_ao_digitar(self.entrada)

        tv = tk.Frame(esq, bg=COR['branco'])
        tv.grid(row=2, column=0, sticky='nsew', padx=16, pady=(0, 16))
        tv.rowconfigure(0, weight=1)
        tv.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(tv, columns=('nome', 'estoque', 'preco'), show='headings')
        self.tree.heading('nome', text='Produto')
        self.tree.heading('estoque', text='Estoque')
        self.tree.heading('preco', text='Preço')
        self.tree.column('nome', width=150)
        self.tree.column('estoque', width=65, anchor='center')
        self.tree.column('preco', width=65, anchor='e')
        self.tree.grid(row=0, column=0, sticky='nsew')
        self.tree.tag_configure('zero', foreground=COR['vermelho'], background=COR['vermelhoclaro'])
        self.tree.tag_configure('baixo', foreground=COR['ambar'], background=COR['amareloclaro'])
        self.tree.tag_configure('par', background=COR['branco'])
        self.tree.tag_configure('impar', background=COR['zebra'])
        self.tree.bind('<Double-1>', lambda e: self._adicionar_selecionado())
        sc = ttk.Scrollbar(tv, orient='vertical', command=self.tree.yview)
        sc.grid(row=0, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=sc.set)

        # Painel "VENDA ATUAL" sem rolagem: o carrinho ocupa o espaço elástico (linha com
        # weight=1) e tudo o resto (pagamento, total, botão de finalizar) fica fixo e
        # sempre visível na tela, sem precisar descer para terminar a venda.
        direita = tk.Frame(p, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        direita.grid(row=1, column=0, sticky='nsew')
        direita.columnconfigure(0, weight=1)
        direita.rowconfigure(2, weight=1)

        cab_dir = tk.Frame(direita, bg=COR['branco'])
        cab_dir.grid(row=0, column=0, sticky='ew', padx=16, pady=(16, 8))
        tk.Label(cab_dir, text='VENDA ATUAL', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 13, 'bold')).pack(side='left')
        ttk.Separator(direita).grid(row=1, column=0, sticky='ew', padx=16)

        painel_car = tk.Frame(direita, bg=COR['branco'])
        painel_car.grid(row=2, column=0, sticky='nsew', padx=16, pady=6)
        painel_car.rowconfigure(0, weight=1)
        painel_car.columnconfigure(0, weight=1)
        self.tree_car = ttk.Treeview(painel_car, columns=('nome', 'qtd', 'sub'), show='headings', height=12, style='Carrinho.Treeview')
        self.tree_car.heading('nome', text='Produto')
        self.tree_car.heading('qtd', text='Qtd')
        self.tree_car.heading('sub', text='Subtotal')
        self.tree_car.column('nome', width=340)
        self.tree_car.column('qtd', width=100, anchor='center')
        self.tree_car.column('sub', width=140, anchor='e')
        self.tree_car.tag_configure('par', background=COR['branco'])
        self.tree_car.tag_configure('impar', background=COR['zebra'])
        self.tree_car.grid(row=0, column=0, sticky='nsew')
        sc_car = ttk.Scrollbar(painel_car, orient='vertical', command=self.tree_car.yview)
        sc_car.grid(row=0, column=1, sticky='ns')
        self.tree_car.configure(yscrollcommand=sc_car.set)

        b = tk.Frame(direita, bg=COR['branco'])
        b.grid(row=3, column=0, sticky='ew', padx=16, pady=2)
        ttk.Button(b, text='−  Qtd', width=8, command=lambda: self._alterar_qtd(-1)).pack(side='left')
        ttk.Button(b, text='+  Qtd', width=8, command=lambda: self._alterar_qtd(1)).pack(side='left', padx=6)
        ttk.Button(b, text='Remover item (Del)', command=self._remover).pack(side='left')

        linha = tk.Frame(direita, bg=COR['branco'])
        linha.grid(row=4, column=0, sticky='ew', padx=16, pady=3)
        tk.Label(linha, text='Cliente (opcional):', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9)).pack(side='left')
        self.label_cliente = tk.Label(linha, text='Nenhum', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 10, 'bold'))
        self.label_cliente.pack(side='left', padx=6)
        ttk.Button(linha, text='Selecionar (F3)', style='Secondary.TButton', command=self._selecionar_cliente).pack(side='right')

        ttk.Separator(direita).grid(row=5, column=0, sticky='ew', padx=16, pady=(2, 4))

        pg = tk.Frame(direita, bg=COR['branco'])
        pg.grid(row=6, column=0, sticky='ew', padx=16, pady=2)
        tk.Label(pg, text='PAGAMENTO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9, 'bold')).pack(side='left', padx=(0, 8))
        for txt, val, tecla in [('Dinheiro', 'dinheiro', 'F5'), ('Crédito', 'cartao_credito', 'F6'), ('Débito', 'cartao_debito', 'F7'), ('Pix', 'pix', 'F8'), ('Voucher', 'voucher', 'F9')]:
            ttk.Radiobutton(pg, text=f'{txt} ({tecla})', value=val, variable=self.forma, command=self._troca_pg).pack(side='left', padx=4)

        linha_extra = tk.Frame(direita, bg=COR['branco'])
        linha_extra.grid(row=7, column=0, sticky='ew', padx=16, pady=(0, 2))
        tk.Label(linha_extra, text='Bandeira do voucher:', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8)).pack(side='left')
        self.combo_voucher = ttk.Combobox(linha_extra, state='readonly', font=(FONTE, 9), width=16)
        self.combo_voucher.pack(side='left', padx=6)
        self.link_fiado = tk.Label(linha_extra, text='venda fiado (cliente cadastrado) (F10)', bg=COR['branco'], fg=COR['cinza'],
                                    font=(FONTE, 8, 'underline'), cursor='hand2')
        self.link_fiado.pack(side='right')
        self.link_fiado.bind('<Button-1>', self._ativar_fiado)
        self._atualizar_visibilidade_pagamento()

        rec = tk.Frame(direita, bg=COR['verdeclaro'])
        rec.grid(row=8, column=0, sticky='ew', padx=16, pady=4)
        tk.Label(rec, text='Recebido', bg=COR['verdeclaro'], fg=COR['verde2'], font=(FONTE, 9, 'bold')).pack(side='left', padx=(10, 4))
        self.recebido = tk.Entry(rec, font=('Consolas', 11), relief='flat', highlightthickness=1, highlightbackground=COR['linha'])
        self.recebido.pack(side='left', fill='x', expand=True, padx=4, pady=4, ipady=2)
        self.troco = tk.Label(rec, text='Troco R$ 0,00', bg=COR['verdeclaro'], fg=COR['verde2'], font=(FONTE, 10, 'bold'))
        self.troco.pack(side='right', padx=10)
        self.recebido.bind('<KeyRelease>', lambda e: self._totais())
        _uppercase_ao_digitar(self.recebido)

        linha_total_btn = tk.Frame(direita, bg=COR['branco'])
        linha_total_btn.grid(row=9, column=0, sticky='ew', padx=16, pady=(4, 2))
        linha_total_btn.columnconfigure(0, weight=1)
        self.total = tk.Label(linha_total_btn, text='R$ 0,00', bg=COR['amarelo'], fg=COR['verde2'], font=('Consolas', 28, 'bold'))
        self.total.grid(row=0, column=0, sticky='ew', ipady=5)
        ttk.Button(linha_total_btn, text=T('finalizar'), style='Primary.TButton', command=self._abrir_finalizar).grid(row=0, column=1, sticky='ns', padx=(8, 0))
        self.lbl_sub = tk.Label(direita, text='Subtotal R$ 0,00', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9))
        self.lbl_sub.grid(row=10, column=0, sticky='e', padx=20, pady=(0, 4))
        ttk.Button(direita, text=T('imprimir_ultimo_cupom'), style='Secondary.TButton', command=self._imprimir_ultimo).grid(row=11, column=0, sticky='ew', padx=16, pady=(0, 8))
        self._totais()

    def _para_float(self, texto, default=0.0):
        try:
            valor = str(texto).replace(',', '.').strip()
            return float(valor) if valor else default
        except (TypeError, ValueError):
            return default

    def _formatq(self, qtd, unidade):
        if unidade == 'KG':
            return f'{qtd:.3f} kg'
        return f'{qtd:.0f}'

    def _moeda(self, valor):
        # Arredonda com ROUND_HALF_UP (igual ao back-end), para a tela nunca
        # mostrar um centavo diferente do que foi gravado.
        try:
            valor = Decimal(str(valor)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception:
            pass
        return f'R$ {valor:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')

    def _busca_tecla(self, event):
        if event.keysym in ('Return', 'Up', 'Down'):
            return
        if hasattr(self, '_deb'):
            self.after_cancel(self._deb)
        self._deb = self.after(150, self._executar_busca)

    def _executar_busca(self):
        termo = self.entrada.get().strip()
        self.tree.delete(*self.tree.get_children())
        self._resultados = []
        if not termo:
            return
        produtos = op.listar_produtos(termo)
        self._resultados = produtos
        for i, p in enumerate(produtos):
            tag = 'zero' if p['quantidade_estoque'] <= 0 else ('baixo' if 0 < p['quantidade_estoque'] < 3 else ('par' if i % 2 == 0 else 'impar'))
            self.tree.insert('', 'end', iid=str(p['id']), tags=(tag,), values=(p['nome'], self._formatq(p['quantidade_estoque'], p['unidade']), self._moeda(p['preco_venda'])))

    def _seta(self, event):
        ids = self.tree.get_children()
        if not ids:
            return 'break'
        atual = self.tree.selection()
        if atual:
            idx = ids.index(atual[0])
        else:
            idx = 0 if event.keysym == 'Down' else len(ids) - 1
        if event.keysym == 'Down':
            idx = min(len(ids) - 1, idx + 1)
        else:
            idx = max(0, idx - 1)
        self.tree.selection_set(ids[idx])
        self.tree.see(ids[idx])
        return 'break'

    def _enter_busca(self, event):
        termo = self.entrada.get().strip()
        m = re.match(r'^\s*(\d+(?:[\.,]\d+)?)\s*[xX]\s*(\S+)\s*$', termo)
        if m:
            qtd = self._para_float(m.group(1))
            produto = op.buscar_por_codigo(m.group(2))
            if produto:
                self._adicionar(produto, qtd)
                self._limpar_busca()
            return
        m = re.match(r'^\s*(\d+(?:[\.,]\d+)?)\s*[xX]\s*$', termo)
        if m:
            self.quantidade_pendente = self._para_float(m.group(1))
            self._limpar_busca()
            self._toast(f'Quantidade preparada: {self.quantidade_pendente:g}x')
            return

        sel = self.tree.selection()
        if sel:
            produto = next((p for p in self._resultados if p['id'] == int(sel[0])), None)
            if produto:
                self._adicionar(produto, self.quantidade_pendente)
                self.quantidade_pendente = None
                self._limpar_busca()
                return
        produto = op.buscar_por_codigo(termo)
        if produto:
            self._adicionar(produto, self.quantidade_pendente)
            self.quantidade_pendente = None
            self._limpar_busca()
            return
        self._executar_busca()
        if len(self._resultados) == 1:
            self._adicionar(self._resultados[0], self.quantidade_pendente)
            self.quantidade_pendente = None
            self._limpar_busca()

    def _adicionar_selecionado(self):
        sel = self.tree.selection()
        if not sel:
            return
        produto = next((p for p in self._resultados if p['id'] == int(sel[0])), None)
        if produto:
            self._adicionar(produto, self.quantidade_pendente)
            self.quantidade_pendente = None
            self._limpar_busca()

    def _adicionar(self, produto, qtd=None):
        produto=dict(produto)
        oferta=g.preco_vigente(produto['id'])
        produto['preco_venda']=oferta
        if qtd is None:
            if produto['unidade'] == 'KG':
                peso_balanca = None
                if getattr(self, 'balanca', None) and self.balanca.conectado and self.balanca.leitura_recente(3.0):
                    peso_balanca = self.balanca.peso_atual()
                if peso_balanca and peso_balanca > 0:
                    qtd = peso_balanca
                else:
                    texto = simpledialog.askstring('Peso', 'Peso em kg (ex.: 1,325):', parent=self)
                    if texto is None:
                        return
                    qtd = self._para_float(texto, 0)
            else:
                qtd = 1
        if qtd <= 0:
            messagebox.showwarning('Quantidade', 'Informe uma quantidade maior que zero.')
            return
        qtd = round(float(qtd), 3)
        existente = next((i for i in self.carrinho if i['produto_id'] == produto['id']), None)
        if existente:
            existente['quantidade'] = round(existente['quantidade'] + qtd, 3)
        else:
            self.carrinho.append({
                'produto_id': produto['id'], 'nome': produto['nome'],
                'preco_unitario': produto['preco_venda'], 'quantidade': qtd,
                'unidade': produto['unidade'], 'estoque': produto['quantidade_estoque'], 'desconto': 0
            })

        estoque = float(produto['quantidade_estoque'])
        if estoque <= 0 and produto['id'] not in self.alertados_zero:
            self.alertados_zero.add(produto['id'])
            self._mostrar_alerta_estoque(f'⚠ SEM ESTOQUE: {produto["nome"]} — venda liberada mesmo assim.')
        elif 0 < estoque < 3 and produto['id'] not in self.alertados_baixo:
            self.alertados_baixo.add(produto['id'])
            self._mostrar_alerta_estoque(f'⚠ ESTOQUE ACABANDO: {produto["nome"]} — restam {self._formatq(estoque, produto["unidade"])}.')
        # Já deixa o item recém-adicionado selecionado no carrinho, pra poder
        # usar os botões/teclas de +/- na hora, sem precisar clicar nele de novo.
        self._render_car(selecionar_produto_id=produto['id'])

    def _mostrar_alerta_estoque(self, texto):
        self.label_alerta.config(text=texto)
        if hasattr(self, '_timer_alerta'):
            self.after_cancel(self._timer_alerta)
        self._timer_alerta = self.after(6500, lambda: self.label_alerta.config(text=''))

    def _limpar_busca(self):
        self.entrada.delete(0, 'end')
        self.tree.delete(*self.tree.get_children())
        self.entrada.focus_set()

    def _render_car(self, selecionar_produto_id=_MANTER_SELECAO):
        # Mantém selecionado, depois de redesenhar a lista, o mesmo item que já
        # estava selecionado (ou o que acabou de ser adicionado/alterado) — sem
        # isso, cada clique em +/- desmarcava a linha e era preciso selecionar
        # de novo pra cada unidade a mais. Passar None explicitamente (item
        # removido do carrinho) significa "não selecionar nada".
        if selecionar_produto_id is _MANTER_SELECAO:
            selecionar_produto_id = None
            sel = self.tree_car.selection()
            if sel:
                idx_sel = int(sel[0])
                if idx_sel < len(self.carrinho):
                    selecionar_produto_id = self.carrinho[idx_sel]['produto_id']
        self.tree_car.delete(*self.tree_car.get_children())
        novo_iid = None
        for i, item in enumerate(self.carrinho):
            subtotal = max(0, item['quantidade'] * item['preco_unitario'] - item.get('desconto', 0))
            tag = 'par' if i % 2 == 0 else 'impar'
            self.tree_car.insert('', 'end', iid=str(i), tags=(tag,), values=(item['nome'], self._formatq(item['quantidade'], item['unidade']), self._moeda(subtotal)))
            if selecionar_produto_id is not None and item['produto_id'] == selecionar_produto_id:
                novo_iid = str(i)
        if novo_iid is not None:
            self.tree_car.selection_set(novo_iid)
            self.tree_car.focus(novo_iid)
            self.tree_car.see(novo_iid)
        self._totais()
        self._atualizar_visor_cliente()

    def _totais(self):
        subtotal = max(0, sum(i['quantidade'] * i['preco_unitario'] - i.get('desconto', 0) for i in self.carrinho))
        self.lbl_sub.config(text=f'Subtotal {self._moeda(subtotal)}')
        self.total.config(text=self._moeda(subtotal))
        recebido = self._para_float(self.recebido.get(), 0)
        self.troco.config(text=f'Troco {self._moeda(max(0, recebido - subtotal))}')

    def _alterar_qtd(self, delta):
        sel = self.tree_car.selection()
        if not sel:
            messagebox.showinfo('Selecione um item', 'Clique em um produto na "VENDA ATUAL" primeiro — depois é só usar +/− à vontade.')
            return
        idx = int(sel[0])
        item = self.carrinho[idx]
        produto_id = item['produto_id']
        passo = 0.1 if item['unidade'] == 'KG' else 1
        item['quantidade'] = round(item['quantidade'] + passo * delta, 3)
        if item['quantidade'] <= 0:
            self.carrinho.pop(idx)
            produto_id = None
        # Passa o produto_id explicitamente pra continuar selecionado — permite
        # clicar +/- várias vezes seguidas pro mesmo item sem reselecionar.
        self._render_car(selecionar_produto_id=produto_id)

    def _remover(self):
        sel = self.tree_car.selection()
        if sel:
            self.carrinho.pop(int(sel[0]))
            self._render_car()

    def _troca_pg(self):
        self._atualizar_visibilidade_pagamento()
        self._totais()

    def _atualizar_visibilidade_pagamento(self):
        if self.forma.get() == 'voucher':
            vouchers = self._config_taxas()['vouchers']
            nomes = [v['nome'] for v in vouchers]
            self.combo_voucher['values'] = nomes
            if nomes and self.combo_voucher.get() not in nomes:
                self.combo_voucher.set(nomes[0])
            self.combo_voucher.configure(state='readonly')
        else:
            self.combo_voucher.configure(state='disabled')
        if self.forma.get() == 'fiado':
            self.link_fiado.config(fg=COR['verde'], font=(FONTE, 8, 'underline bold'), text='✓ venda fiado ativada')
        else:
            self.link_fiado.config(fg=COR['cinza'], font=(FONTE, 8, 'underline'), text='venda fiado (cliente cadastrado)')

    def _ativar_fiado(self, event=None):
        self.forma.set('fiado')
        self._atualizar_visibilidade_pagamento()
        if not self.cliente_fiado:
            self._selecionar_cliente()
        self._totais()

    def _taxa_da_forma(self):
        """Retorna (percentual, bandeira_voucher) pra forma de pagamento atual."""
        conf = self._config_taxas()
        forma = self.forma.get()
        if forma == 'cartao_credito':
            return conf['credito'], None
        if forma == 'cartao_debito':
            return conf['debito'], None
        if forma == 'voucher':
            nome = self.combo_voucher.get()
            v = next((x for x in conf['vouchers'] if x['nome'] == nome), None)
            return (v['taxa'] if v else 0), nome or None
        if forma == 'pix':
            return conf['pix'], None
        return 0, None

    def _selecionar_cliente(self):
        clientes = op.listar_clientes()
        dlg = tk.Toplevel(self)
        dlg.title('Selecionar cliente')
        dlg.geometry('520x520')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())
        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Selecionar cliente', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 14, 'bold')).pack(anchor='w', padx=20, pady=(14, 8))
        ent = tk.Entry(dlg, font=(FONTE, 11), relief='solid', bd=1)
        ent.pack(fill='x', padx=20, ipady=5)
        _uppercase_ao_digitar(ent)
        tv = ttk.Treeview(dlg, columns=('nome', 'saldo'), show='headings')
        tv.heading('nome', text='Nome')
        tv.heading('saldo', text='Dívida')
        tv.column('saldo', width=100, anchor='e')
        tv.pack(fill='both', expand=True, padx=20, pady=10)

        def carregar(*_):
            busca = ent.get().lower()
            tv.delete(*tv.get_children())
            for i, c in enumerate(clientes):
                if busca in c['nome'].lower() or busca in (c['telefone'] or '').lower():
                    tag = 'par' if i % 2 == 0 else 'impar'
                    tv.insert('', 'end', iid=str(c['id']), tags=(tag,), values=(c['nome'], self._moeda(c['saldo_fiado'])))
            tv.tag_configure('par', background=COR['branco'])
            tv.tag_configure('impar', background=COR['zebra'])

        ent.bind('<KeyRelease>', carregar)
        carregar()

        def escolher():
            sel = tv.selection()
            if not sel:
                return
            self.cliente_fiado = op.obter_cliente(int(sel[0]))
            self.label_cliente.config(text=self.cliente_fiado['nome'])
            dlg.destroy()

        def cadastrar_novo():
            nome = ent.get().strip()
            if not nome:
                messagebox.showwarning('Nome', 'Digite o nome no campo de busca antes de cadastrar.', parent=dlg)
                return
            try:
                novo_id = op.criar_cliente(nome)
                self.cliente_fiado = op.obter_cliente(novo_id)
                self.label_cliente.config(text=self.cliente_fiado['nome'])
                dlg.destroy()
                self._carrega_clientes()
            except Exception as exc:
                messagebox.showerror('Erro', str(exc), parent=dlg)

        tv.bind('<Double-1>', lambda e: escolher())
        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=20, pady=(0, 16))
        ttk.Button(botoes, text='Selecionar', style='Primary.TButton', command=escolher).pack(side='right')
        ttk.Button(botoes, text='+ Cadastrar novo', style='Secondary.TButton', command=cadastrar_novo).pack(side='right', padx=(0, 8))
        ttk.Button(botoes, text='Remover cliente da venda', style='Secondary.TButton',
                   command=lambda: (self._limpar_cliente(), dlg.destroy())).pack(side='left')

    def _limpar_cliente(self):
        self.cliente_fiado = None
        self.label_cliente.config(text='Nenhum')

    def _abrir_finalizar(self):
        if not self.carrinho:
            return
        dlg = tk.Toplevel(self)
        dlg.title('Finalizar compra')
        dlg.geometry('640x790')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Finalizar compra', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 17, 'bold')).pack(anchor='w', padx=24, pady=(16, 10))

        tk.Label(dlg, text='ITENS — duplo clique para dar desconto num item específico', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24)
        tv = ttk.Treeview(dlg, columns=('nome', 'qtd', 'preco', 'desc', 'sub'), show='headings', height=6)
        for c, t, w, anc in [('nome', 'Produto', 170, 'w'), ('qtd', 'Qtd', 55, 'center'), ('preco', 'Preço', 75, 'e'), ('desc', 'Desconto', 80, 'e'), ('sub', 'Subtotal', 85, 'e')]:
            tv.heading(c, text=t)
            tv.column(c, width=w, anchor=anc)
        tv.tag_configure('par', background=COR['branco'])
        tv.tag_configure('impar', background=COR['zebra'])
        tv.pack(fill='x', padx=24, pady=(4, 12))

        def preencher_itens():
            tv.delete(*tv.get_children())
            for i, item in enumerate(self.carrinho):
                bruto = item['quantidade'] * item['preco_unitario']
                desc = item.get('desconto', 0)
                sub = max(0, bruto - desc)
                tag = 'par' if i % 2 == 0 else 'impar'
                tv.insert('', 'end', iid=str(i), tags=(tag,), values=(
                    item['nome'], self._formatq(item['quantidade'], item['unidade']),
                    self._moeda(item['preco_unitario']), self._moeda(desc) if desc else '—', self._moeda(sub)))

        def desconto_item(event):
            sel = tv.selection()
            if not sel:
                return
            idx = int(sel[0])
            item = self.carrinho[idx]
            bruto = item['quantidade'] * item['preco_unitario']
            valor = simpledialog.askfloat('Desconto no item', f'Desconto em R$ para "{item["nome"]}" (máx {self._moeda(bruto)}):',
                                           minvalue=0, maxvalue=bruto, initialvalue=item.get('desconto', 0), parent=dlg)
            if valor is not None:
                item['desconto'] = round(valor, 2)
                preencher_itens()
                atualizar_total()
        tv.bind('<Double-1>', desconto_item)
        preencher_itens()

        tk.Label(dlg, text='NOME DO CLIENTE (opcional)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(6, 3))
        frame_cli = tk.Frame(dlg, bg=COR['branco'])
        frame_cli.pack(fill='x', padx=24)
        label_cli_modal = tk.Label(frame_cli, text=self.cliente_fiado['nome'] if self.cliente_fiado else 'Nenhum', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 11, 'bold'))
        label_cli_modal.pack(side='left')

        def escolher_cliente_no_modal():
            self._selecionar_cliente()
            label_cli_modal.config(text=self.cliente_fiado['nome'] if self.cliente_fiado else 'Nenhum')
            dlg.lift()
            _grab_set_safe(dlg)
        ttk.Button(frame_cli, text='Selecionar / novo', style='Secondary.TButton', command=escolher_cliente_no_modal).pack(side='right')

        tk.Label(dlg, text='DESCONTO NO TOTAL', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(14, 3))
        frame_desc = tk.Frame(dlg, bg=COR['branco'])
        frame_desc.pack(fill='x', padx=24)
        modo = tk.StringVar(value='rs')
        ttk.Radiobutton(frame_desc, text='R$', value='rs', variable=modo, command=lambda: atualizar_total()).pack(side='left')
        ttk.Radiobutton(frame_desc, text='%', value='pct', variable=modo, command=lambda: atualizar_total()).pack(side='left', padx=(10, 10))
        entrada_desc = tk.Entry(frame_desc, font=(FONTE, 11), width=10, relief='solid', bd=1)
        entrada_desc.insert(0, '0')
        entrada_desc.pack(side='left', ipady=4)
        entrada_desc.bind('<KeyRelease>', lambda e: atualizar_total())
        _uppercase_ao_digitar(entrada_desc)

        ttk.Separator(dlg).pack(fill='x', padx=24, pady=(14, 8))
        lbl_subtotal = tk.Label(dlg, text='Subtotal: R$ 0,00', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 10))
        lbl_subtotal.pack(anchor='e', padx=24)
        lbl_descontos = tk.Label(dlg, text='Descontos: R$ 0,00', bg=COR['branco'], fg=COR['vermelho'], font=(FONTE, 10))
        lbl_descontos.pack(anchor='e', padx=24)
        lbl_total = tk.Label(dlg, text='R$ 0,00', bg=COR['amarelo'], fg=COR['verde2'], font=('Consolas', 28, 'bold'))
        lbl_total.pack(fill='x', padx=24, pady=(8, 10), ipady=10)

        def calcular():
            # Tudo em centavos inteiros, arredondando item a item — a MESMA
            # regra de gestao.registrar_venda, para não dar divergência de
            # arredondamento (ex.: 0,185 kg × R$ 45,00 = 8,325 → 8,33).
            bruto_c = g.centavos_itens(self.carrinho)
            desc_itens_c = sum(g.centavos(i.get('desconto', 0)) for i in self.carrinho)
            liquido_c = max(0, bruto_c - desc_itens_c)
            valor_campo = self._para_float(entrada_desc.get(), 0)
            if modo.get() == 'pct':
                desc_total_c = g.centavos(Decimal(liquido_c) * Decimal(str(valor_campo)) / Decimal(10000))
            else:
                desc_total_c = g.centavos(valor_campo)
            desc_total_c = max(0, min(desc_total_c, liquido_c))
            final_c = max(0, liquido_c - desc_total_c)
            taxa_pct, _bandeira = self._taxa_da_forma()
            taxa_c = g.centavos(Decimal(final_c) * Decimal(str(taxa_pct)) / Decimal(10000))
            liquido_final_c = final_c - taxa_c
            return (bruto_c / 100, (desc_itens_c + desc_total_c) / 100,
                    final_c / 100, taxa_c / 100, liquido_final_c / 100)

        # Valor recebido em dinheiro + troco (só aparece quando a forma é dinheiro).
        frame_recebido = tk.Frame(dlg, bg=COR['branco'])
        tk.Label(frame_recebido, text='Recebido (R$):', bg=COR['branco'], fg=COR['cinza'],
                 font=(FONTE, 8, 'bold')).pack(side='left')
        ent_recebido = tk.Entry(frame_recebido, font=('Consolas', 12), width=12, relief='solid', bd=1)
        ent_recebido.pack(side='left', padx=(4, 14), ipady=4)
        if self.recebido.get().strip():
            ent_recebido.insert(0, self.recebido.get().strip())
        lbl_troco = tk.Label(frame_recebido, text='Troco R$ 0,00', bg=COR['verdeclaro'], fg=COR['verde2'],
                             font=(FONTE, 11, 'bold'))
        lbl_troco.pack(side='left', padx=4, ipady=4)

        def atualizar_troco():
            if self.forma.get() == 'dinheiro':
                frame_recebido.pack(fill='x', padx=24, pady=(6, 2))
                _, _, final, _, _ = calcular()
                receb = self._para_float(ent_recebido.get(), 0)
                lbl_troco.config(text=f'Troco {self._moeda(max(0, receb - final))}')
            else:
                frame_recebido.pack_forget()
        ent_recebido.bind('<KeyRelease>', lambda e: atualizar_troco())

        lbl_taxa = tk.Label(dlg, text='', bg=COR['branco'], fg=COR['ambar'], font=(FONTE, 9, 'bold'))

        def atualizar_total():
            bruto, descontos, final, taxa_valor, liquido_final = calcular()
            lbl_subtotal.config(text=f'Subtotal: {self._moeda(bruto)}')
            lbl_descontos.config(text=f'Descontos: {self._moeda(descontos)}')
            lbl_total.config(text=self._moeda(final))
            if taxa_valor > 0:
                lbl_taxa.config(text=f'Taxa da maquininha: −{self._moeda(taxa_valor)}   →   recebe {self._moeda(liquido_final)}')
                lbl_taxa.pack(anchor='e', padx=24, pady=(2, 0))
            else:
                lbl_taxa.pack_forget()
            atualizar_troco()
        atualizar_total()

        pg = tk.Frame(dlg, bg=COR['branco'])
        pg.pack(fill='x', padx=24, pady=(2, 4))
        tk.Label(pg, text='PAGAMENTO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(side='left', padx=(0, 8))
        for txt, val, tecla in [('Dinheiro', 'dinheiro', 'F5'), ('Crédito', 'cartao_credito', 'F6'), ('Débito', 'cartao_debito', 'F7'), ('Pix', 'pix', 'F8'), ('Voucher', 'voucher', 'F9')]:
            ttk.Radiobutton(pg, text=f'{txt} ({tecla})', value=val, variable=self.forma, command=atualizar_total).pack(side='left', padx=4)

        linha_extra_modal = tk.Frame(dlg, bg=COR['branco'])
        linha_extra_modal.pack(fill='x', padx=24, pady=(0, 4))
        tk.Label(linha_extra_modal, text='Bandeira do voucher:', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8)).pack(side='left')
        combo_voucher_modal = ttk.Combobox(linha_extra_modal, state='readonly', font=(FONTE, 9), width=16,
                                            values=[v['nome'] for v in self._config_taxas()['vouchers']])
        combo_voucher_modal.pack(side='left', padx=6)
        if self.combo_voucher.get():
            combo_voucher_modal.set(self.combo_voucher.get())
        combo_voucher_modal.bind('<<ComboboxSelected>>', lambda e: (self.combo_voucher.set(combo_voucher_modal.get()), atualizar_total()))
        link_fiado_modal = tk.Label(linha_extra_modal, text='venda fiado (cliente cadastrado)', bg=COR['branco'], fg=COR['cinza'],
                                     font=(FONTE, 8, 'underline'), cursor='hand2')
        link_fiado_modal.pack(side='right')

        def ativar_fiado_modal(event=None):
            self._ativar_fiado()
            link_fiado_modal.config(fg=COR['verde'], text='✓ venda fiado ativada')
            atualizar_total()
        link_fiado_modal.bind('<Button-1>', ativar_fiado_modal)

        chave_venda=uuid.uuid4().hex
        def confirmar():
            if self.forma.get() == 'fiado' and not self.cliente_fiado:
                messagebox.showwarning('Cliente', 'Selecione um cliente para venda fiada.', parent=dlg)
                return
            _, descontos, final, taxa_valor, liquido_final = calcular()
            if self.forma.get() == 'dinheiro':
                receb = self._para_float(ent_recebido.get(), 0)
                if receb and receb + 0.005 < final:
                    messagebox.showwarning('Valor recebido',
                                           f'O valor recebido ({self._moeda(receb)}) é menor que o total '
                                           f'da venda ({self._moeda(final)}).', parent=dlg)
                    return
            _pct, bandeira = self._taxa_da_forma()
            try:
                venda = op.registrar_venda(
                    [{'produto_id': x['produto_id'], 'quantidade': x['quantidade']} for x in self.carrinho],
                    self.forma.get(), round(descontos, 2),
                    self.cliente_fiado['id'] if self.cliente_fiado else None,
                    taxa_paga=taxa_valor, voucher_marca=bandeira if self.forma.get() == 'voucher' else None, chave_operacao=chave_venda, total_esperado=round(final,2)
                )
                self._ultimo_venda = venda['id']
                dlg.destroy()
                msg = f'Venda #{venda["id"]} finalizada — {self._moeda(final)}'
                if taxa_valor > 0:
                    msg += f' (líquido {self._moeda(liquido_final)})'
                self._toast(msg)
                if carregar_config().get('auto_imprimir', True):
                    try:
                        self._imprimir_venda(venda['id'])
                    except Exception as exc:
                        self._toast(f'Não foi possível imprimir: {exc}')
                self._mostrar_agradecimento_visor(final)
                self.carrinho = []
                self.cliente_fiado = None
                self.label_cliente.config(text='Nenhum')
                self.forma.set('dinheiro')
                self.recebido.delete(0, 'end')
                self.alertados_zero.clear()
                self.alertados_baixo.clear()
                self._render_car()
                self._atualizar_visibilidade_pagamento()
                self._aba_atualizada()
            except (op.ErroOperacao, g.ErroGestao) as exc:
                messagebox.showerror('Erro', str(exc), parent=dlg)

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=(10, 20), side='bottom')
        ttk.Button(botoes, text='CONFIRMAR VENDA', style='Primary.TButton', command=confirmar).pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))

    def _cupom(self, venda_id):
        venda = op.detalhar_venda(venda_id)
        conf = carregar_config()
        larg = largura_papel(conf.get('papel_largura', '80'))
        linhac = '=' * larg
        tragos = '-' * larg

        _FORMA_TXT = {
            'dinheiro': 'DINHEIRO',
            'cartao_credito': 'CARTÃO DE CRÉDITO',
            'cartao_debito': 'CARTÃO DE DÉBITO',
            'pix': 'PIX',
            'voucher': 'VOUCHER',
            'fiado': 'FIADO',
            'misto': 'PAGAMENTO DIVIDIDO',
        }

        def pontilhado(rotulo, valor):
            pontos = max(1, larg - len(rotulo) - len(valor))
            return f'{rotulo}{"." * pontos}{valor}'

        l = []
        l.append(('g', (conf.get('nome_mercado') or 'MERCADINHO').strip().upper()))
        if conf.get('endereco_mercado'):
            l.append(('c', conf['endereco_mercado'].strip()))
        if conf.get('telefone_mercado'):
            l.append(('c', f"FONE: {conf['telefone_mercado'].strip()}"))
        if conf.get('cnpj_mercado'):
            l.append(('c', f"CNPJ: {conf['cnpj_mercado'].strip()}"))
        l.append(('d', linhac))
        l.append(('cb', 'CUPOM NÃO FISCAL'))
        l.append(('c', 'COMPROVANTE DE VENDA'))
        l.append(('c', tragos))

        try:
            data_txt = datetime.strptime(str(venda['data_hora']).replace('T', ' ')[:19], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y %H:%M')
        except (TypeError, ValueError):
            data_txt = str(venda.get('data_hora', ''))
        l.append(('n', f'Data: {data_txt}'))
        l.append(('n', f'Venda N.: {venda["id"]:05d}'))
        l.append(('d', tragos))

        for item in venda['itens']:
            nome_txt = item['nome'].strip()
            if len(nome_txt) > larg - 1:
                nome_txt = nome_txt[:larg - 2] + '..'
            l.append(('b', nome_txt.upper()))
            qtd_txt = self._formatq(item['quantidade'], item['unidade'])
            preco_txt = self._moeda(item['preco_unitario'])
            sub_txt = self._moeda(item['quantidade'] * item['preco_unitario'])
            desc = f'{qtd_txt} x {preco_txt}'
            pontos = larg - len(desc) - len(sub_txt)
            if pontos < 1:
                desc = desc[:larg - len(sub_txt) - 1]
                pontos = 1
            l.append(('n', f'{desc}{"." * pontos}{sub_txt}'))

        l.append(('d', tragos))
        subtotal = g.centavos_itens(venda['itens']) / 100
        l.append(('n', pontilhado('Subtotal', self._moeda(subtotal))))
        if venda.get('desconto'):
            l.append(('n', pontilhado('Descontos', '-' + self._moeda(venda['desconto']))))
        if venda.get('taxa_paga'):
            l.append(('n', pontilhado('Taxa paga', self._moeda(venda['taxa_paga']))))
            l.append(('b', pontilhado('Líquido', self._moeda(max(0, subtotal - venda['desconto'] - venda['taxa_paga'])))))
        l.append(('b', pontilhado('TOTAL', self._moeda(venda['valor_total']) + (' CANCELADA' if venda.get('cancelada') else ''))))
        l.append(('d', tragos))

        forma_txt = _FORMA_TXT.get(venda['forma_pagamento'], venda['forma_pagamento'].upper())
        l.append(('b', pontilhado('Pagamento', forma_txt)))
        # Pagamento dividido: detalha cada forma e o valor de cada parte.
        for pg in venda.get('pagamentos') or []:
            if len(venda['pagamentos']) > 1:
                rotulo = _FORMA_TXT.get(pg['forma'], pg['forma'].upper())
                l.append(('n', pontilhado(rotulo, self._moeda(pg['valor']))))
        if venda.get('voucher_marca'):
            l.append(('n', pontilhado('Bandeira', venda['voucher_marca'])))
        if venda.get('cliente_nome'):
            l.append(('n', pontilhado('Cliente', venda['cliente_nome'])))
            if venda['forma_pagamento'] == 'fiado' and venda.get('cliente_id'):
                l.append(('n', pontilhado('Saldo fiado', self._moeda(op.saldo_fiado(venda['cliente_id'])))))
        l.append(('c', tragos))
        rodape = (conf.get('rodape_mercado') or 'Obrigado pela preferência! Volte sempre.').strip()
        l.append(('cb', rodape))
        l.append(('c', 'Este comprovante não possui valor fiscal.'))
        return l

    def _imprimir_venda(self, venda_id):
        conf = carregar_config()
        imprimir_cupom(self._cupom(venda_id),
                       vias=max(1, int(conf.get('vias_impressao', 1) or 1)),
                       papel=str(conf.get('papel_largura', '80')))

    def _imprimir_ultimo(self):
        if self._ultimo_venda:
            try:
                self._imprimir_venda(self._ultimo_venda)
            except Exception as exc:
                messagebox.showerror('Impressão', str(exc))

    def _config_impressora(self):
        impressoras = impressoras_windows()
        conf = carregar_config()
        dlg = tk.Toplevel(self)
        dlg.title('Configurar impressora térmica')
        dlg.geometry('640x720')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Impressora térmica', bg=COR['branco'], fg=COR['verde2'],
                 font=(FONTE, 17, 'bold')).pack(anchor='w', padx=24, pady=(14, 2))
        if impressoras:
            tk.Label(dlg, text=f'{len(impressoras)} impressora(s) encontrada(s) no Windows',
                     bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8)).pack(anchor='w', padx=24)
        else:
            tk.Label(dlg, text='Nenhuma impressora Windows encontrada. Instale a dependência (pip install pywin32) e conecte a impressora.',
                     bg=COR['branco'], fg=COR['vermelho'], font=(FONTE, 8)).pack(anchor='w', padx=24)

        var_print = tk.StringVar(value=conf.get('impressora', ''))
        var_papel = tk.StringVar(value=str(conf.get('papel_largura', '80')))
        var_auto = tk.BooleanVar(value=bool(conf.get('auto_imprimir', True)))
        var_vias = tk.IntVar(value=max(1, int(conf.get('vias_impressao', 1) or 1)))

        bloco = tk.Frame(dlg, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco.pack(fill='x', padx=24, pady=(12, 8))

        def atualizar_lista():
            lista = impressoras_windows()
            cb.config(values=lista)
            if var_print.get() not in lista and lista:
                var_print.set(lista[0])

        linha_print = tk.Frame(bloco, bg=COR['branco'])
        linha_print.pack(fill='x', padx=18, pady=(14, 4))
        tk.Label(linha_print, text='IMPRESSORA', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(side='left')
        ttk.Button(linha_print, text='Atualizar lista', style='Secondary.TButton', command=atualizar_lista).pack(side='right')
        cb = ttk.Combobox(bloco, textvariable=var_print, values=impressoras, state='readonly', font=(FONTE, 10))
        cb.pack(fill='x', padx=18)

        linha_papel = tk.Frame(bloco, bg=COR['branco'])
        linha_papel.pack(fill='x', padx=18, pady=(14, 4))
        tk.Label(linha_papel, text='LARGURA DO PAPEL', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(side='left')
        ttk.Radiobutton(linha_papel, text='80 mm (padrão)', value='80', variable=var_papel).pack(side='left', padx=(14, 0))
        ttk.Radiobutton(linha_papel, text='58 mm', value='58', variable=var_papel).pack(side='left', padx=(10, 0))

        linha_auto = tk.Frame(bloco, bg=COR['branco'])
        linha_auto.pack(fill='x', padx=18, pady=(14, 4))
        ttk.Checkbutton(linha_auto, text='Imprimir cupom automaticamente ao finalizar a venda',
                        variable=var_auto).pack(side='left')
        tk.Label(linha_auto, text='Vias:', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9)).pack(side='left', padx=(24, 4))
        tk.Spinbox(linha_auto, from_=1, to=5, width=3, textvariable=var_vias).pack(side='left', ipady=2)

        bloco2 = tk.Frame(dlg, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco2.pack(fill='x', padx=24, pady=(8, 12))
        tk.Label(bloco2, text='DADOS QUE APARECEM NO CUPOM', bg=COR['branco'], fg=COR['cinza'],
                 font=(FONTE, 8, 'bold')).pack(anchor='w', padx=18, pady=(14, 8))

        var_nome = tk.StringVar(value=conf.get('nome_mercado', ''))
        var_cnpj = tk.StringVar(value=conf.get('cnpj_mercado', ''))
        var_end = tk.StringVar(value=conf.get('endereco_mercado', ''))
        var_fone = tk.StringVar(value=conf.get('telefone_mercado', ''))
        var_rodape = tk.StringVar(value=conf.get('rodape_mercado', ''))

        grid = tk.Frame(bloco2, bg=COR['branco'])
        grid.pack(fill='x', padx=18, pady=(0, 16))
        for i, (rot, var, dica) in enumerate([
                ('Nome do mercado', var_nome, 'ex.: MERCADINHO DO SEU ZÉ'),
                ('CNPJ', var_cnpj, 'ex.: 12.345.678/0001-90'),
                ('Endereço', var_end, 'ex.: Av. Brasil, 123 - Centro'),
                ('Telefone', var_fone, 'ex.: (11) 98765-4321'),
                ('Mensagem final', var_rodape, 'ex.: Obrigado pela preferência!')]):
            tk.Label(grid, text=rot, bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9)).grid(
                row=i, column=0, sticky='w', padx=(0, 10), pady=3)
            ent = tk.Entry(grid, textvariable=var, font=(FONTE, 11), relief='solid', bd=1)
            ent.insert(0, var.get() if var.get() else dica)
            if var.get():
                ent.delete(0, 'end')

            def on_focus(e, v=var, d=dica):
                if not v.get():
                    e.widget.delete(0, 'end')
                    e.widget.config(fg='black')

            def on_blur(e, v=var, d=dica):
                if not v.get():
                    e.widget.insert(0, d)
                    e.widget.config(fg=COR['cinza'])

            ent.bind('<FocusIn>', on_focus)
            ent.bind('<FocusOut>', on_blur)
            ent.grid(row=i, column=1, sticky='ew', pady=3, ipady=4)
        grid.columnconfigure(1, weight=1)

        def salvar():
            dados = {
                'impressora': var_print.get(),
                'papel_largura': var_papel.get(),
                'auto_imprimir': bool(var_auto.get()),
                'vias_impressao': max(1, int(var_vias.get() or 1)),
                'nome_mercado': var_nome.get().strip(),
                'cnpj_mercado': var_cnpj.get().strip(),
                'endereco_mercado': var_end.get().strip(),
                'telefone_mercado': var_fone.get().strip(),
                'rodape_mercado': var_rodape.get().strip(),
            }
            if not dados['nome_mercado']:
                dados['nome_mercado'] = 'MERCADINHO'
            salvar_config(dados)
            dlg.destroy()
            self._toast('Configuração da impressora salva')

        def testar():
            try:
                testar_impressao(var_print.get() or None, papel=var_papel.get())
                self._toast('Página de teste enviada à impressora!')
            except Exception as exc:
                messagebox.showerror('Impressão', str(exc), parent=dlg)

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=(6, 20), side='bottom')
        ttk.Button(botoes, text='SALVAR', style='Primary.TButton', command=salvar).pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))
        ttk.Button(botoes, text='Imprimir página de teste', style='Secondary.TButton', command=testar).pack(side='left')

    def _backup_manual(self):
        try:
            caminho, novo = backup_diario(False)
            messagebox.showinfo('Backup', f'Backup salvo em:\n{caminho}' if novo else f'O backup de hoje já existe em:\n{caminho}')
        except Exception as exc:
            messagebox.showerror('Backup', str(exc))

    def _montar_produtos(self):
        p = self.tab_prod
        p.rowconfigure(2, weight=1)
        p.columnconfigure(0, weight=1)
        topo = tk.Frame(p, bg=COR['papel'])
        topo.grid(row=0, column=0, sticky='ew', pady=(0, 4))
        tk.Label(topo, text='Produtos / Estoque', bg=COR['papel'], fg=COR['verde2'], font=(FONTE, 20, 'bold')).pack(side='left')
        ttk.Button(topo, text='+ Novo produto', style='Primary.TButton', command=lambda: self._modal_produto()).pack(side='right')
        ttk.Button(topo, text='Ajustar estoque', style='Secondary.TButton', command=self._ajustar).pack(side='right', padx=6)
        ttk.Button(topo, text='Importar planilha', style='Secondary.TButton', command=self._importar).pack(side='right', padx=6)
        ttk.Button(topo, text='Validades', style='Secondary.TButton', command=self._abrir_validades_geral).pack(side='right', padx=6)
        ttk.Button(topo, text='Excluir produto', style='Secondary.TButton', command=self._abrir_excluir_produto).pack(side='right', padx=6)
        self.busca_prod = tk.Entry(p, font=(FONTE, 11), relief='solid', bd=1,
                                    highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        self.busca_prod.grid(row=1, column=0, sticky='ew', pady=10, ipady=5)
        self.busca_prod.bind('<KeyRelease>', lambda e: self._carrega_produtos())
        _uppercase_ao_digitar(self.busca_prod)
        tabela = tk.Frame(p, highlightbackground=COR['linha'], highlightthickness=1)
        tabela.grid(row=2, column=0, sticky='nsew')
        tabela.rowconfigure(0, weight=1)
        tabela.columnconfigure(0, weight=1)
        self.tvprod = ttk.Treeview(tabela, columns=('nome', 'cat', 'un', 'codigo', 'custo', 'venda', 'estoque'), show='headings')
        self.tvprod.grid(row=0, column=0, sticky='nsew')
        larguras = {'nome': 260, 'cat': 130, 'un': 50, 'codigo': 130, 'custo': 90, 'venda': 90, 'estoque': 100}
        for c, t in [('nome', 'Produto'), ('cat', 'Categoria'), ('un', 'Un.'), ('codigo', 'Código'), ('custo', 'Custo'), ('venda', 'Venda'), ('estoque', 'Estoque')]:
            ancora = 'center' if c == 'un' else ('e' if c in ('custo', 'venda', 'estoque') else 'w')
            self.tvprod.heading(c, text=t)
            self.tvprod.column(c, width=larguras[c], anchor=ancora)
        self.tvprod.tag_configure('par', background=COR['branco'])
        self.tvprod.tag_configure('impar', background=COR['zebra'])
        self.tvprod.tag_configure('zero', foreground=COR['vermelho'], background=COR['vermelhoclaro'])
        self.tvprod.tag_configure('baixo', foreground=COR['ambar'], background=COR['amareloclaro'])
        self.tvprod.bind('<Double-1>', lambda e: self._editar_produto())
        scp = ttk.Scrollbar(tabela, orient='vertical', command=self.tvprod.yview)
        scp.grid(row=0, column=1, sticky='ns')
        self.tvprod.configure(yscrollcommand=scp.set)
        self._carrega_produtos()

    def _carrega_produtos(self):
        ps = op.listar_produtos(self.busca_prod.get())
        self.produtos_cache = {x['id']: x for x in ps}
        self.tvprod.delete(*self.tvprod.get_children())
        for i, p in enumerate(ps):
            if p['quantidade_estoque'] <= 0:
                tag = 'zero'
            elif p['quantidade_estoque'] < p['estoque_minimo']:
                tag = 'baixo'
            else:
                tag = 'par' if i % 2 == 0 else 'impar'
            self.tvprod.insert('', 'end', iid=str(p['id']), tags=(tag,), values=(
                p['nome'], p['categoria'] or '—', p['unidade'], p['codigo_barras'] or p.get('sku','—'),
                self._moeda(p['preco_custo']), self._moeda(p['preco_venda']), self._formatq(p['quantidade_estoque'], p['unidade'])))

    def _editar_produto(self):
        sel = self.tvprod.selection()
        if sel:
            self._modal_produto(self.produtos_cache[int(sel[0])])

    def _modal_produto(self, produto=None):
        dlg = tk.Toplevel(self)
        dlg.title('Editar produto' if produto else 'Novo produto')
        dlg.geometry('460x680')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.resizable(False, False)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Editar produto' if produto else 'Novo produto', bg=COR['branco'], fg=COR['verde2'],
                 font=(FONTE, 15, 'bold')).pack(anchor='w', padx=24, pady=(16, 4))

        campos = {}
        vcmd_nome = (self.register(self._validar_nome), '%P')
        vcmd_codigo = (self.register(self._validar_codigo), '%P')

        def campo(chave, rotulo, vcmd=None):
            tk.Label(dlg, text=rotulo.upper(), bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
            entrada = tk.Entry(dlg, font=(FONTE, 11), relief='solid', bd=1,
                                highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
            if vcmd:
                entrada.configure(validate='key', validatecommand=vcmd)
            entrada.pack(fill='x', padx=24, ipady=5)
            campos[chave] = entrada
            _uppercase_ao_digitar(entrada)

        campo('nome', 'Nome', vcmd_nome)
        campo('codigo', 'Código de barras (número)', vcmd_codigo)
        campo('categoria', 'Categoria')

        tk.Label(dlg, text='UNIDADE', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        unidade = ttk.Combobox(dlg, values=['UN', 'KG'], state='readonly', font=(FONTE, 10))
        unidade.pack(fill='x', padx=24)
        unidade.set(produto['unidade'] if produto else 'UN')

        linha_precos = tk.Frame(dlg, bg=COR['branco'])
        linha_precos.pack(fill='x', padx=24, pady=(12, 0))
        linha_precos.columnconfigure((0, 1, 2), weight=1)
        for col, (chave, rotulo) in enumerate([('custo', 'Preço de custo'), ('venda', 'Preço de venda'), ('margem', 'Margem de lucro %')]):
            tk.Label(linha_precos, text=rotulo.upper(), bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).grid(row=0, column=col, sticky='w', padx=(0 if col == 0 else 10, 0))
            e = tk.Entry(linha_precos, font=(FONTE, 11), relief='solid', bd=1)
            e.grid(row=1, column=col, sticky='ew', padx=(0 if col == 0 else 10, 0), ipady=5, pady=(3, 0))
            campos[chave] = e
            _uppercase_ao_digitar(e)
        tk.Label(dlg, text='Preencha custo e venda (a margem calcula sozinha), ou custo e a margem desejada (o preço de venda calcula sozinho).',
                 bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8), wraplength=410, justify='left').pack(anchor='w', padx=24, pady=(4, 0))

        linha_estoque = tk.Frame(dlg, bg=COR['branco'])
        linha_estoque.pack(fill='x', padx=24, pady=(12, 0))
        linha_estoque.columnconfigure((0, 1), weight=1)
        pares = [('estoque', 'Estoque inicial')] if not produto else []
        pares.append(('minimo', 'Estoque mínimo'))
        for col, (chave, rotulo) in enumerate(pares):
            tk.Label(linha_estoque, text=rotulo.upper(), bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).grid(row=0, column=col, sticky='w', padx=(0 if col == 0 else 10, 0))
            e = tk.Entry(linha_estoque, font=(FONTE, 11), relief='solid', bd=1)
            e.grid(row=1, column=col, sticky='ew', padx=(0 if col == 0 else 10, 0), ipady=5, pady=(3, 0))
            campos[chave] = e
            _uppercase_ao_digitar(e)
        if produto:
            tk.Label(dlg, text=f"Estoque atual: {self._formatq(produto['quantidade_estoque'], produto['unidade'])} — use \"Ajustar estoque\" na lista para mudar",
                     bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8), wraplength=410, justify='left').pack(anchor='w', padx=24, pady=(6, 0))

        if produto:
            custo_inicial = produto['preco_custo']
            venda_inicial = produto['preco_venda']
            margem_inicial = round(((venda_inicial - custo_inicial) / custo_inicial) * 100, 2) if custo_inicial > 0 else 0
            valores = {
                'nome': produto['nome'], 'codigo': produto['codigo_barras'] or '', 'categoria': produto['categoria'] or '',
                'custo': custo_inicial, 'venda': venda_inicial, 'margem': margem_inicial, 'minimo': produto['estoque_minimo']
            }
            for chave, valor in valores.items():
                campos[chave].insert(0, str(valor))
        else:
            campos['minimo'].insert(0, '3')
            campos['estoque'].insert(0, '0')
            campos['margem'].insert(0, '0')

        # Margem de lucro e preço de venda ficam ligados: mudar o custo ou o preço de
        # venda recalcula a margem; mudar a margem recalcula o preço de venda.
        _recalculando = {'ativo': False}

        def _recalcular_precos(origem):
            if _recalculando['ativo']:
                return
            _recalculando['ativo'] = True
            try:
                custo_val = self._para_float(campos['custo'].get(), 0)
                if origem == 'margem':
                    margem_val = self._para_float(campos['margem'].get(), 0)
                    venda_val = round(custo_val * (1 + margem_val / 100), 2)
                    campos['venda'].delete(0, 'end')
                    campos['venda'].insert(0, f'{venda_val:.2f}')
                else:
                    venda_val = self._para_float(campos['venda'].get(), 0)
                    margem_val = round(((venda_val - custo_val) / custo_val) * 100, 2) if custo_val > 0 else 0
                    campos['margem'].delete(0, 'end')
                    campos['margem'].insert(0, f'{margem_val:.2f}')
            finally:
                _recalculando['ativo'] = False

        campos['custo'].bind('<KeyRelease>', lambda e: _recalcular_precos('venda'), add='+')
        campos['venda'].bind('<KeyRelease>', lambda e: _recalcular_precos('venda'), add='+')
        campos['margem'].bind('<KeyRelease>', lambda e: _recalcular_precos('margem'), add='+')

        def salvar():
            nome_val = campos['nome'].get().strip()
            codigo_val = campos['codigo'].get().strip()
            if not nome_val or not re.fullmatch(r'[A-Za-zÀ-ÿ0-9 ]+', nome_val):
                messagebox.showerror('Nome inválido', 'O nome só pode ter letras, números e espaços.', parent=dlg)
                return
            if codigo_val and not codigo_val.isdigit():
                messagebox.showerror('Código inválido', 'O código de barras só pode ter números.', parent=dlg)
                return
            try:
                if produto:
                    op.atualizar_produto(produto['id'], nome_val, codigo_val or None, campos['categoria'].get(), unidade.get(), self._para_float(campos['custo'].get()), self._para_float(campos['venda'].get()), self._para_float(campos['minimo'].get()))
                else:
                    op.criar_produto(nome_val, codigo_val or None, campos['categoria'].get(), unidade.get(), self._para_float(campos['custo'].get()), self._para_float(campos['venda'].get()), self._para_float(campos['estoque'].get()), self._para_float(campos['minimo'].get()))
                dlg.destroy()
                self._carrega_produtos()
            except Exception as exc:
                messagebox.showerror('Erro', str(exc), parent=dlg)

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=22, side='bottom')
        ttk.Button(botoes, text='Salvar', style='Primary.TButton', command=salvar).pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))
        campos['nome'].focus_set()

    def _ajustar(self):
        sel = self.tvprod.selection()
        if not sel:
            return
        produto = self.produtos_cache[int(sel[0])]
        texto = simpledialog.askstring('Estoque', f"Novo total de {produto['nome']} ({produto['unidade']}):", initialvalue=str(produto['quantidade_estoque']), parent=self)
        if texto is None:
            return
        try:
            op.ajustar_estoque(produto['id'], self._para_float(texto), tipo='ajuste', observacao='Contagem de estoque')
            self._carrega_produtos()
        except Exception as exc:
            messagebox.showerror('Erro', str(exc))

    def _importar(self):
        caminho = filedialog.askopenfilename(filetypes=[('Excel', '*.xlsx')])
        if not caminho:
            return
        try:
            plano = iplan.pre_visualizar(caminho)
        except Exception as exc:
            messagebox.showerror('Erro ao ler a planilha', str(exc))
            return
        resumo = (f"{plano['inseridos_previstos']} produto(s) novo(s) e "
                  f"{plano['atualizados_previstos']} a atualizar. "
                  f"{len(plano['ignorados'])} linha(s) serão ignoradas.")
        if not messagebox.askyesno('Importar planilha', resumo + '\n\nNada foi gravado ainda. Confirmar?'):
            return
        try:
            r = iplan.aplicar(caminho, plano)
            msg = f"{r['inseridos']} novos, {r['atualizados']} atualizados"
            if r['ignorados']:
                msg += f", {len(r['ignorados'])} ignorados"
            messagebox.showinfo('Importação', msg)
            self._carrega_produtos()
        except Exception as exc:
            messagebox.showerror('Erro', str(exc))

    def _abrir_excluir_produto(self):
        sel = self.tvprod.selection()
        if not sel:
            messagebox.showinfo('Selecione um produto', 'Clique em um produto na lista primeiro.')
            return
        produto = self.produtos_cache[int(sel[0])]
        pode, motivo = op.pode_excluir_produto_definitivamente(produto['id'])

        dlg = tk.Toplevel(self)
        dlg.title(f'Excluir produto — {produto["nome"]}')
        dlg.geometry('460x340')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.resizable(False, False)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['vermelho'], height=6).pack(fill='x')
        tk.Label(dlg, text=f'Excluir "{produto["nome"]}" de vez', bg=COR['branco'], fg=COR['verde2'],
                 font=(FONTE, 15, 'bold')).pack(anchor='w', padx=24, pady=(16, 4))

        if not pode:
            tk.Label(dlg, text=motivo, bg=COR['branco'], fg=COR['vermelho'], font=(FONTE, 10),
                     wraplength=400, justify='left').pack(anchor='w', padx=24, pady=(6, 4))
            tk.Label(dlg,
                     text='Pra não perder o histórico, esse produto só pode ser desativado '
                          '(some das listas e do caixa, mas os dados continuam preservados).',
                     bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9), wraplength=400, justify='left').pack(anchor='w', padx=24, pady=(0, 16))

            def desativar():
                op.desativar_produto(produto['id'])
                dlg.destroy()
                self._carrega_produtos()
                self._toast(f'{produto["nome"]} foi desativado.')

            botoes = tk.Frame(dlg, bg=COR['branco'])
            botoes.pack(fill='x', padx=24, pady=22, side='bottom')
            ttk.Button(botoes, text='Desativar em vez disso', style='Primary.TButton', command=desativar).pack(side='right')
            ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))
            return

        tk.Label(dlg,
                 text='Esse produto nunca apareceu numa venda, consumo interno ou receita — dá pra '
                      'apagar de vez (diferente de "desativar"). Isso não pode ser desfeito.',
                 bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9), wraplength=400, justify='left').pack(anchor='w', padx=24, pady=(6, 14))
        tk.Label(dlg, text=f'PRA CONFIRMAR, DIGITE O NOME EXATO: "{produto["nome"]}"', bg=COR['branco'], fg=COR['cinza'],
                 font=(FONTE, 8, 'bold'), wraplength=400, justify='left').pack(anchor='w', padx=24)
        var_nome = tk.StringVar()
        ent_nome = tk.Entry(dlg, textvariable=var_nome, font=(FONTE, 11), relief='solid', bd=1,
                             highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['vermelho'])
        ent_nome.pack(fill='x', padx=24, pady=(4, 4), ipady=6)

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=22, side='bottom')
        btn_excluir = ttk.Button(botoes, text='EXCLUIR DEFINITIVAMENTE', style='Secondary.TButton', state='disabled')
        btn_excluir.pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))

        def confirmar():
            try:
                nome = op.excluir_produto_definitivo(produto['id'], var_nome.get())
                dlg.destroy()
                self._carrega_produtos()
                self._toast(f'{nome} foi excluído do sistema.')
            except Exception as exc:
                messagebox.showerror('Erro', str(exc), parent=dlg)

        def checar_nome(*_a):
            bate = var_nome.get().strip().lower() == produto['nome'].strip().lower()
            btn_excluir.config(state='normal' if bate else 'disabled', command=confirmar if bate else None)

        var_nome.trace_add('write', checar_nome)
        ent_nome.focus_set()

    def _abrir_validades_geral(self):
        dlg = tk.Toplevel(self)
        dlg.title('Controle de validade')
        dlg.geometry('760x600')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        cab = tk.Frame(dlg, bg=COR['branco'])
        cab.pack(fill='x', padx=24, pady=(16, 4))
        tk.Label(cab, text='Validades por lote', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 15, 'bold')).pack(side='left')
        ttk.Button(cab, text='+ Adicionar lote', style='Primary.TButton', command=lambda: self._abrir_novo_lote(dlg, recarregar)).pack(side='right')
        tk.Label(dlg, text='Cada linha é um lote — o mesmo produto pode aparecer mais de uma vez, com validades diferentes.',
                 bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9)).pack(anchor='w', padx=24, pady=(0, 10))

        tv = ttk.Treeview(dlg, columns=('produto', 'qtd', 'validade', 'situacao', 'obs'), show='headings', height=18)
        tv.heading('produto', text='Produto')
        tv.heading('qtd', text='Quantidade')
        tv.heading('validade', text='Validade')
        tv.heading('situacao', text='Situação')
        tv.heading('obs', text='Observação')
        tv.column('produto', width=250)
        tv.column('qtd', width=90, anchor='center')
        tv.column('validade', width=90, anchor='center')
        tv.column('situacao', width=110, anchor='center')
        tv.column('obs', width=160)
        tv.tag_configure('vencido', foreground=COR['vermelho'], background=COR['vermelhoclaro'])
        tv.tag_configure('proximo', foreground=COR['ambar'], background=COR['amareloclaro'])
        tv.tag_configure('ok', background=COR['branco'])
        tv.pack(fill='both', expand=True, padx=24, pady=(0, 10))
        sc = ttk.Scrollbar(dlg, orient='vertical', command=tv.yview)
        tv.configure(yscrollcommand=sc.set)

        lotes_cache = {}

        def recarregar():
            tv.delete(*tv.get_children())
            lotes_cache.clear()
            for lote in val.todos_lotes_com_produto():
                lotes_cache[lote['lote_id']] = lote
                if not lote['data_validade']:
                    tag, situacao = 'ok', '—'
                else:
                    dias = (date.fromisoformat(lote['data_validade']) - date.today()).days
                    if dias < 0:
                        tag, situacao = 'vencido', f'Vencido há {abs(dias)}d'
                    elif dias <= 7:
                        tag, situacao = 'proximo', f'Vence em {dias}d'
                    else:
                        tag, situacao = 'ok', f'Vence em {dias}d'
                validade_br = datetime.strptime(lote['data_validade'], '%Y-%m-%d').strftime('%d/%m/%Y') if lote['data_validade'] else '—'
                tv.insert('', 'end', iid=str(lote['lote_id']), tags=(tag,), values=(
                    lote['nome'], self._formatq(lote['quantidade'], lote['unidade']), validade_br, situacao, lote['observacao'] or ''))

        def remover_selecionado():
            sel = tv.selection()
            if not sel:
                return
            lote = lotes_cache.get(int(sel[0]))
            if lote and messagebox.askyesno('Remover lote', f'Remover o lote de {lote["nome"]} ({self._formatq(lote["quantidade"], lote["unidade"])})?', parent=dlg):
                self._executar_gestao(lambda: val.excluir_lote(lote['lote_id']))
                recarregar()

        def registrar_como_perda():
            sel = tv.selection()
            if not sel:
                messagebox.showinfo('Selecione um lote', 'Clique num lote da lista primeiro.', parent=dlg)
                return
            lote = lotes_cache.get(int(sel[0]))
            if not lote:
                return
            if not messagebox.askyesno(
                    'Registrar como perda',
                    f'Jogar fora {self._formatq(lote["quantidade"], lote["unidade"])} de {lote["nome"]} '
                    f'e registrar como perda (validade vencida)?', parent=dlg):
                return
            try:
                obs = f'Lote vencido em {lote["data_validade"]}' if lote['data_validade'] else 'Lote sem validade definida'
                op.registrar_perda([{'produto_id': lote['produto_id'], 'quantidade': lote['quantidade'], 'lote_id': lote['lote_id']}],
                                    'Validade vencida', obs)
                recarregar()
                self._carrega_produtos()
                self._carrega_resumo_perda()
                self._carrega_historico_perda()
                self._toast(f'{lote["nome"]} registrado como perda.')
            except Exception as exc:
                messagebox.showerror('Erro', str(exc), parent=dlg)

        botoes_baixo = tk.Frame(dlg, bg=COR['branco'])
        botoes_baixo.pack(fill='x', padx=24, pady=(0, 18))
        ttk.Button(botoes_baixo, text='Registrar como perda', style='Primary.TButton', command=registrar_como_perda).pack(side='left')
        ttk.Button(botoes_baixo, text='Remover lote selecionado', style='Secondary.TButton', command=remover_selecionado).pack(side='left', padx=(8, 0))
        ttk.Button(botoes_baixo, text='Fechar', style='Secondary.TButton', command=dlg.destroy).pack(side='right')

        recarregar()

    def _abrir_novo_lote(self, dlg_pai, callback_recarregar):
        sel = self.tvprod.selection()
        produto_inicial = self.produtos_cache[int(sel[0])] if sel else None

        dlg = tk.Toplevel(dlg_pai)
        dlg.title('Adicionar lote de validade')
        dlg.geometry('420x420')
        dlg.configure(bg=COR['branco'])
        dlg.transient(dlg_pai)
        _grab_set_safe(dlg)
        dlg.resizable(False, False)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Adicionar lote de validade', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 14, 'bold')).pack(anchor='w', padx=24, pady=(16, 12))

        tk.Label(dlg, text='PRODUTO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24)
        ent_produto = tk.Entry(dlg, font=(FONTE, 10), relief='solid', bd=1,
                                highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_produto.pack(fill='x', padx=24, ipady=5)
        _uppercase_ao_digitar(ent_produto)
        lista_sugestoes = tk.Listbox(dlg, height=4, font=(FONTE, 9))
        produto_escolhido = {'id': produto_inicial['id'] if produto_inicial else None}
        if produto_inicial:
            ent_produto.insert(0, produto_inicial['nome'])

        def buscar(event=None):
            termo = ent_produto.get().strip()
            lista_sugestoes.delete(0, 'end')
            if len(termo) < 2:
                lista_sugestoes.pack_forget()
                return
            achados = op.listar_produtos(termo)[:8]
            if not achados:
                lista_sugestoes.pack_forget()
                return
            for p in achados:
                lista_sugestoes.insert('end', p['nome'])
            lista_sugestoes._achados = achados
            lista_sugestoes.pack(fill='x', padx=24, pady=(2, 0))

        def escolher(event=None):
            sel = lista_sugestoes.curselection()
            if sel:
                p = lista_sugestoes._achados[sel[0]]
                ent_produto.delete(0, 'end')
                ent_produto.insert(0, p['nome'])
                produto_escolhido['id'] = p['id']
                lista_sugestoes.pack_forget()

        ent_produto.bind('<KeyRelease>', buscar)
        lista_sugestoes.bind('<<ListboxSelect>>', escolher)

        tk.Label(dlg, text='QUANTIDADE', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        ent_qtd = tk.Entry(dlg, font=('Consolas', 12), relief='solid', bd=1,
                            highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_qtd.pack(fill='x', padx=24, ipady=5)

        tk.Label(dlg, text='VALIDADE (DD/MM/AAAA)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        ent_data = tk.Entry(dlg, font=('Consolas', 12), relief='solid', bd=1,
                             highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_data.pack(fill='x', padx=24, ipady=5)

        tk.Label(dlg, text='OBSERVAÇÃO (OPCIONAL)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        ent_obs = tk.Entry(dlg, font=(FONTE, 10), relief='solid', bd=1,
                            highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_obs.pack(fill='x', padx=24, ipady=5)
        _uppercase_ao_digitar(ent_obs)

        def salvar():
            if not produto_escolhido['id']:
                messagebox.showerror('Produto', 'Escolha um produto da lista.', parent=dlg)
                return
            data_iso = None
            texto_data = ent_data.get().strip()
            if texto_data:
                try:
                    data_iso = datetime.strptime(texto_data, '%d/%m/%Y').strftime('%Y-%m-%d')
                except ValueError:
                    messagebox.showerror('Data', 'Data inválida. Use DD/MM/AAAA.', parent=dlg)
                    return
            try:
                val.registrar_lote(produto_escolhido['id'], self._para_float(ent_qtd.get(), 0), data_iso, ent_obs.get())
                dlg.destroy()
                callback_recarregar()
            except Exception as exc:
                messagebox.showerror('Erro', str(exc), parent=dlg)

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=22, side='bottom')
        ttk.Button(botoes, text='Salvar', style='Primary.TButton', command=salvar).pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))
        ent_qtd.focus_set()

    def _montar_clientes(self):
        p = self.tab_cli
        p.rowconfigure(2, weight=1)
        p.columnconfigure(0, weight=1)
        topo = tk.Frame(p, bg=COR['papel'])
        topo.grid(row=0, column=0, sticky='ew', pady=(0, 4))
        tk.Label(topo, text='Clientes', bg=COR['papel'], fg=COR['verde2'], font=(FONTE, 20, 'bold')).pack(side='left')
        ttk.Button(topo, text='+ Cliente', style='Primary.TButton', command=lambda: self._modal_cliente()).pack(side='right')
        ttk.Button(topo, text='Ajustar saldo', style='Secondary.TButton', command=self._abrir_ajustar_saldo).pack(side='right', padx=6)
        ttk.Button(topo, text='Cascos', style='Secondary.TButton', command=self._abrir_cascos_cliente).pack(side='right', padx=6)
        ttk.Button(topo, text='Ver detalhes', style='Secondary.TButton', command=self._detalhes_cliente).pack(side='right', padx=6)
        ttk.Button(topo, text='Editar', style='Secondary.TButton', command=self._editar_cliente).pack(side='right')
        ttk.Button(topo, text='Excluir cliente', style='Secondary.TButton', command=self._abrir_excluir_cliente).pack(side='right', padx=6)
        linha_busca = tk.Frame(p, bg=COR['papel'])
        linha_busca.grid(row=1, column=0, sticky='ew', pady=10)
        linha_busca.columnconfigure(0, weight=1)
        self.busca_cli = tk.Entry(linha_busca, font=(FONTE, 11), relief='solid', bd=1,
                                   highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        self.busca_cli.grid(row=0, column=0, sticky='ew', ipady=5)
        self.busca_cli.bind('<KeyRelease>', lambda e: self._carrega_clientes())
        _uppercase_ao_digitar(self.busca_cli)
        tk.Label(linha_busca, text='receber pagamento', bg=COR['papel'], fg=COR['cinza'], font=(FONTE, 8, 'underline'),
                 cursor='hand2').grid(row=0, column=1, padx=(10, 0))
        linha_busca.grid_slaves(row=0, column=1)[0].bind('<Button-1>', lambda e: self._receber_fiado())
        tabela = tk.Frame(p, highlightbackground=COR['linha'], highlightthickness=1)
        tabela.grid(row=2, column=0, sticky='nsew')
        tabela.rowconfigure(0, weight=1)
        tabela.columnconfigure(0, weight=1)
        self.tvcli = ttk.Treeview(tabela, columns=('nome', 'telefone', 'saldo', 'casco'), displaycolumns=('nome','telefone','saldo'), show='headings')
        self.tvcli.grid(row=0, column=0, sticky='nsew')
        self.tvcli.heading('nome', text='Cliente')
        self.tvcli.heading('telefone', text='Telefone')
        self.tvcli.heading('saldo', text='Pendência')
        self.tvcli.heading('casco', text='Casco')
        self.tvcli.column('nome', width=260)
        self.tvcli.column('telefone', width=140)
        self.tvcli.column('saldo', width=130, anchor='e')
        self.tvcli.column('casco', width=120, anchor='e')
        self.tvcli.tag_configure('par', background=COR['branco'])
        self.tvcli.tag_configure('impar', background=COR['zebra'])
        self.tvcli.tag_configure('devendo', foreground=COR['vermelho'], background=COR['vermelhoclaro'])
        self.tvcli.tag_configure('credito', foreground=COR['verde2'], background=COR['verdeclaro'])
        self.tvcli.bind('<Double-1>', lambda e: self._detalhes_cliente())
        scc = ttk.Scrollbar(tabela, orient='vertical', command=self.tvcli.yview)
        scc.grid(row=0, column=1, sticky='ns')
        self.tvcli.configure(yscrollcommand=scc.set)
        self._carrega_clientes()

    def _texto_saldo(self, saldo):
        """Deve (positivo) / crédito (negativo, pagou ou deixou a mais) / em dia (zero)."""
        if saldo > 0.004:
            return f'Deve {self._moeda(saldo)}'
        if saldo < -0.004:
            return f'Crédito de {self._moeda(abs(saldo))}'
        return 'Em dia'

    def _carrega_clientes(self):
        clientes = op.listar_clientes(self.busca_cli.get())
        ordem=getattr(self,'ordem_clientes',None)
        if ordem and ordem.get()=='Saldo em aberto': clientes.sort(key=lambda c:c['saldo_fiado'],reverse=True)
        elif ordem and ordem.get()=='Última compra':
            datas={r['cliente_id']:r['ultima'] for r in g.consultar('SELECT cliente_id,MAX(data_hora) ultima FROM vendas GROUP BY cliente_id')}
            clientes.sort(key=lambda c:datas.get(c['id'],'') or '',reverse=True)
        else: clientes.sort(key=lambda c:g.normalizar(c['nome']))
        self._clientes_cache = {c['id']: c for c in clientes}
        self.tvcli.delete(*self.tvcli.get_children())
        for i, c in enumerate(clientes):
            saldo = c['saldo_fiado']
            if saldo > 0.004: tag = 'devendo'
            elif saldo < -0.004: tag = 'credito'
            else: tag = 'par' if i % 2 == 0 else 'impar'
            saldo_casco_total = cascos.saldo_casco(c['id'])
            texto_casco = cascos.texto_saldo(saldo_casco_total) if saldo_casco_total != 0 else '—'
            self.tvcli.insert('', 'end', iid=str(c['id']), tags=(tag,), values=(c['nome'], c['telefone'], '⚠ Pendência' if saldo>0.004 else '—', texto_casco))

    def _modal_cliente(self, cliente=None):
        dlg = tk.Toplevel(self)
        dlg.title('Editar cliente' if cliente else 'Novo cliente')
        dlg.geometry('460x600')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.resizable(False, False)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Editar cliente' if cliente else 'Novo cliente', bg=COR['branco'], fg=COR['verde2'],
                 font=(FONTE, 15, 'bold')).pack(anchor='w', padx=24, pady=(16, 4))

        campos = {}
        for chave, rotulo in [('nome', 'Nome'), ('telefone', 'Telefone')]:
            tk.Label(dlg, text=rotulo.upper(), bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
            ent = tk.Entry(dlg, font=(FONTE, 11), relief='solid', bd=1,
                            highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
            ent.pack(fill='x', padx=24, ipady=5)
            campos[chave] = ent
            _uppercase_ao_digitar(ent)

        tk.Label(dlg, text='DOCUMENTO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        linha_doc = tk.Frame(dlg, bg=COR['branco'])
        linha_doc.pack(fill='x', padx=24)
        combo_doc_tipo = ttk.Combobox(linha_doc, state='readonly', font=(FONTE, 10), width=10,
                                       values=['', 'CPF', 'CNPJ', 'RG', 'Outro'])
        combo_doc_tipo.pack(side='left', ipady=4)
        combo_doc_tipo.set('')
        ent_doc = tk.Entry(linha_doc, font=(FONTE, 11), relief='solid', bd=1,
                            highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_doc.pack(side='left', fill='x', expand=True, padx=(8, 0), ipady=5)
        campos['documento_tipo'] = combo_doc_tipo
        campos['documento'] = ent_doc

        tk.Label(dlg, text='ENDEREÇO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        ent_end = tk.Entry(dlg, font=(FONTE, 11), relief='solid', bd=1,
                            highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_end.pack(fill='x', padx=24, ipady=5)
        campos['endereco'] = ent_end
        _uppercase_ao_digitar(ent_end)

        tk.Label(dlg, text='OBSERVAÇÃO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        ent_obs = tk.Entry(dlg, font=(FONTE, 11), relief='solid', bd=1,
                            highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_obs.pack(fill='x', padx=24, ipady=5)
        campos['obs'] = ent_obs
        _uppercase_ao_digitar(ent_obs)

        if cliente:
            campos['nome'].insert(0, cliente['nome'])
            campos['telefone'].insert(0, cliente['telefone'])
            campos['documento_tipo'].set(cliente.get('documento_tipo') or '')
            campos['documento'].insert(0, cliente.get('documento') or '')
            campos['endereco'].insert(0, cliente.get('endereco') or '')
            campos['obs'].insert(0, cliente['observacao'])

        def salvar():
            try:
                dados = dict(
                    nome=campos['nome'].get(), telefone=campos['telefone'].get(),
                    documento_tipo=campos['documento_tipo'].get(), documento=campos['documento'].get(),
                    endereco=campos['endereco'].get(), observacao=campos['obs'].get(),
                )
                if cliente:
                    op.atualizar_cliente(cliente['id'], **dados)
                else:
                    op.criar_cliente(**dados)
                dlg.destroy()
                self._carrega_clientes()
            except Exception as exc:
                messagebox.showerror('Erro', str(exc), parent=dlg)

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=22, side='bottom')
        ttk.Button(botoes, text='Salvar', style='Primary.TButton', command=salvar).pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))
        campos['nome'].focus_set()

    def _ver_consumo_cliente(self):
        sel = self.tvcli.selection()
        if not sel:
            messagebox.showinfo('Selecione um cliente', 'Clique em um cliente na lista primeiro.')
            return
        cliente = self._clientes_cache[int(sel[0])]
        dados = op.consumo_cliente(cliente['id'])
        extrato = op.extrato_cliente(cliente['id'])
        saldo = cliente['saldo_fiado']

        dlg = tk.Toplevel(self)
        dlg.title(f'Cliente — {cliente["nome"]}')
        dlg.geometry('640x680')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        cab = tk.Frame(dlg, bg=COR['branco'])
        cab.pack(fill='x', padx=24, pady=(16, 0))
        tk.Label(cab, text=cliente['nome'], bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 16, 'bold')).pack(side='left')
        if abs(saldo) > 0.004:
            bg_saldo = COR['vermelhoclaro'] if saldo > 0 else COR['verdeclaro']
            fg_saldo = COR['vermelho'] if saldo > 0 else COR['verde2']
            tk.Label(cab, text=self._texto_saldo(saldo), bg=bg_saldo, fg=fg_saldo,
                     font=(FONTE, 10, 'bold')).pack(side='right', ipadx=8, ipady=3)

        partes_info = []
        if cliente.get('telefone'):
            partes_info.append(cliente['telefone'])
        if cliente.get('documento'):
            partes_info.append(f"{cliente.get('documento_tipo') or 'Doc.'}: {cliente['documento']}")
        if cliente.get('endereco'):
            partes_info.append(cliente['endereco'])
        if partes_info:
            tk.Label(dlg, text='  ·  '.join(partes_info), bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9)).pack(anchor='w', padx=24, pady=(2, 0))

        nb_cli = ttk.Notebook(dlg)
        nb_cli.pack(fill='both', expand=True, padx=24, pady=(12, 12))
        aba_resumo = tk.Frame(nb_cli, bg=COR['branco'])
        aba_extrato = tk.Frame(nb_cli, bg=COR['branco'])
        nb_cli.add(aba_resumo, text=' Resumo ')
        nb_cli.add(aba_extrato, text=' Extrato (por data) ')

        # ---- Aba Resumo: o que mais consome + total por mês ----
        tk.Label(aba_resumo, text='PRODUTOS (do mais ao menos comprado)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', pady=(10, 4))
        tv = ttk.Treeview(aba_resumo, columns=('nome', 'qtd', 'total'), show='headings', height=9)
        tv.heading('nome', text='Produto')
        tv.heading('qtd', text='Quantidade')
        tv.heading('total', text='Total gasto')
        tv.column('nome', width=280)
        tv.column('qtd', width=100, anchor='center')
        tv.column('total', width=110, anchor='e')
        tv.tag_configure('par', background=COR['branco'])
        tv.tag_configure('impar', background=COR['zebra'])
        tv.pack(fill='both', expand=True, pady=(0, 12))
        if dados['produtos']:
            for i, item in enumerate(dados['produtos']):
                tag = 'par' if i % 2 == 0 else 'impar'
                tv.insert('', 'end', tags=(tag,), values=(item['nome'], self._formatq(item['qtd'], item['unidade']), self._moeda(item['total'])))
        else:
            tv.insert('', 'end', values=('Nenhuma compra registrada ainda', '', ''))

        tk.Label(aba_resumo, text='TOTAL GASTO POR MÊS', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w')
        tv2 = ttk.Treeview(aba_resumo, columns=('mes', 'n', 'total'), show='headings', height=6)
        tv2.heading('mes', text='Mês')
        tv2.heading('n', text='Compras')
        tv2.heading('total', text='Total gasto')
        tv2.column('mes', width=280)
        tv2.column('n', width=100, anchor='center')
        tv2.column('total', width=110, anchor='e')
        tv2.tag_configure('par', background=COR['branco'])
        tv2.tag_configure('impar', background=COR['zebra'])
        tv2.pack(fill='both', expand=True, pady=(4, 4))
        for i, m in enumerate(dados['meses']):
            tag = 'par' if i % 2 == 0 else 'impar'
            tv2.insert('', 'end', tags=(tag,), values=(m['mes'], m['n'], self._moeda(m['total'])))

        # ---- Aba Extrato: cada compra com os itens, e cada pagamento, por data ----
        tk.Label(aba_extrato, text='TUDO O QUE COMPROU E PAGOU, DO MAIS RECENTE AO MAIS ANTIGO', bg=COR['branco'],
                 fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', pady=(10, 4))
        tve = ttk.Treeview(aba_extrato, columns=('valor',), show='tree headings', height=18)
        tve.heading('#0', text='Data / produto')
        tve.heading('valor', text='Valor')
        tve.column('#0', width=380)
        tve.column('valor', width=100, anchor='e')
        tve.tag_configure('compra', foreground=COR['verde2'], font=(FONTE, 10, 'bold'))
        tve.tag_configure('fiado', foreground=COR['ambar'])
        tve.tag_configure('pagamento', foreground=COR['verde'], font=(FONTE, 10, 'bold'))
        tve.tag_configure('item', foreground=COR['cinza'])
        scroll_ext = ttk.Scrollbar(aba_extrato, orient='vertical', command=tve.yview)
        tve.configure(yscrollcommand=scroll_ext.set)
        tve.pack(side='left', fill='both', expand=True, pady=(0, 8))
        scroll_ext.pack(side='right', fill='y', pady=(0, 8))

        if extrato:
            for i, ev in enumerate(extrato):
                try:
                    quando = datetime.strptime(ev['data_hora'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y %H:%M')
                except ValueError:
                    quando = ev['data_hora']
                if ev['tipo'] == 'compra':
                    forma = 'fiado' if ev['forma_pagamento'] == 'fiado' else ev['forma_pagamento']
                    tag = 'fiado' if ev['forma_pagamento'] == 'fiado' else 'compra'
                    rotulo = f"🛒 {quando} — {forma}"
                    pai = tve.insert('', 'end', text=rotulo, tags=(tag,), values=(self._moeda(ev['valor']),), open=(i < 5))
                    for item in ev['itens']:
                        texto_item = f"   {item['nome']} ({self._formatq(item['quantidade'], item['unidade'])})"
                        subtotal = item['quantidade'] * item['preco_unitario']
                        tve.insert(pai, 'end', text=texto_item, tags=('item',), values=(self._moeda(subtotal),))
                else:
                    sinal = '+' if ev['valor'] >= 0 else '−'
                    verbo = ('pagou' if ev.get('forma_pagamento') else 'saldo adicionado') if ev['valor'] >= 0 else 'saldo debitado'
                    forma_txt = f" no {ev['forma_pagamento']}" if ev.get('forma_pagamento') else ''
                    rotulo = (f"💰 {quando} — {verbo}{forma_txt} "
                              f"({sinal}{self._moeda(abs(ev['valor']))}) — não é uma compra") + \
                             (f" · {ev['observacao']}" if ev['observacao'] else '')
                    tve.insert('', 'end', text=rotulo, tags=('pagamento',), values=(self._moeda(ev['valor']),))
        else:
            tve.insert('', 'end', text='Nenhuma compra ou pagamento registrado ainda', values=('',))

        ttk.Button(dlg, text='Fechar', style='Secondary.TButton', command=dlg.destroy).pack(pady=(0, 18))

    def _abrir_excluir_cliente(self):
        sel = self.tvcli.selection()
        if not sel:
            messagebox.showinfo('Selecione um cliente', 'Clique em um cliente na lista primeiro.')
            return
        cliente = self._clientes_cache[int(sel[0])]
        pode, motivo, n_vendas, n_pag = op.pode_excluir_definitivamente(cliente['id'])

        dlg = tk.Toplevel(self)
        dlg.title(f'Excluir cliente — {cliente["nome"]}')
        dlg.geometry('460x360')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.resizable(False, False)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['vermelho'], height=6).pack(fill='x')
        tk.Label(dlg, text=f'Excluir "{cliente["nome"]}" de vez', bg=COR['branco'], fg=COR['verde2'],
                 font=(FONTE, 15, 'bold')).pack(anchor='w', padx=24, pady=(16, 4))

        if not pode:
            tk.Label(dlg, text=motivo, bg=COR['branco'], fg=COR['vermelho'], font=(FONTE, 10),
                     wraplength=400, justify='left').pack(anchor='w', padx=24, pady=(6, 4))
            tk.Label(dlg,
                     text='Pra não perder o histórico de vendas/fiado, esse cliente só pode ser '
                          'desativado (some das listas, mas os dados continuam preservados) — não excluído de vez.',
                     bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9), wraplength=400, justify='left').pack(anchor='w', padx=24, pady=(0, 16))

            def desativar():
                op.desativar_cliente(cliente['id'])
                dlg.destroy()
                self._carrega_clientes()
                self._toast(f'{cliente["nome"]} foi desativado.')

            botoes = tk.Frame(dlg, bg=COR['branco'])
            botoes.pack(fill='x', padx=24, pady=22, side='bottom')
            ttk.Button(botoes, text='Desativar em vez disso', style='Primary.TButton', command=desativar).pack(side='right')
            ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))
            return

        tk.Label(dlg,
                 text='Esse cliente nunca teve nenhuma venda nem pagamento registrado — dá pra apagar '
                      'de vez do sistema (diferente de "desativar", que só esconde). Isso não pode ser desfeito.',
                 bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9), wraplength=400, justify='left').pack(anchor='w', padx=24, pady=(6, 14))

        tk.Label(dlg, text=f'PRA CONFIRMAR, DIGITE O NOME EXATO: "{cliente["nome"]}"', bg=COR['branco'], fg=COR['cinza'],
                 font=(FONTE, 8, 'bold'), wraplength=400, justify='left').pack(anchor='w', padx=24)
        var_nome = tk.StringVar()
        ent_nome = tk.Entry(dlg, textvariable=var_nome, font=(FONTE, 11), relief='solid', bd=1,
                             highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['vermelho'])
        ent_nome.pack(fill='x', padx=24, pady=(4, 4), ipady=6)

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=22, side='bottom')
        btn_excluir = ttk.Button(botoes, text='EXCLUIR DEFINITIVAMENTE', style='Secondary.TButton', state='disabled')
        btn_excluir.pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))

        def confirmar():
            try:
                nome = op.excluir_cliente_definitivo(cliente['id'], var_nome.get())
                dlg.destroy()
                self._carrega_clientes()
                self._toast(f'{nome} foi excluído do sistema.')
            except Exception as exc:
                messagebox.showerror('Erro', str(exc), parent=dlg)

        def checar_nome(*_a):
            bate = var_nome.get().strip().lower() == cliente['nome'].strip().lower()
            btn_excluir.config(state='normal' if bate else 'disabled', command=confirmar if bate else None)

        var_nome.trace_add('write', checar_nome)
        ent_nome.focus_set()

    def _editar_cliente(self):
        sel = self.tvcli.selection()
        if sel:
            self._modal_cliente(self._clientes_cache[int(sel[0])])

    def _receber_fiado_legado(self):
        sel = self.tvcli.selection()
        if not sel:
            messagebox.showinfo('Selecione um cliente', 'Clique em um cliente na lista primeiro.')
            return
        cliente = self._clientes_cache[int(sel[0])]
        if cliente['saldo_fiado'] <= 0.004:
            messagebox.showinfo('Sem dívida', f"{cliente['nome']} não está devendo.")
            return

        dlg = tk.Toplevel(self)
        dlg.title(f'Receber fiado — {cliente["nome"]}')
        dlg.geometry('420x420')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.resizable(False, False)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text=cliente['nome'], bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 15, 'bold')).pack(anchor='w', padx=24, pady=(16, 0))
        tk.Label(dlg, text=self._texto_saldo(cliente['saldo_fiado']), bg=COR['branco'], fg=COR['vermelho'], font=(FONTE, 11, 'bold')).pack(anchor='w', padx=24, pady=(0, 12))

        tk.Label(dlg, text='QUANTO ELE(A) PAGOU AGORA (R$)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24)
        tk.Label(dlg, text='pode ser menor que a dívida — o resto continua em aberto', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8)).pack(anchor='w', padx=24, pady=(0, 3))
        ent_valor = tk.Entry(dlg, font=('Consolas', 14), relief='solid', bd=1,
                              highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_valor.pack(fill='x', padx=24, ipady=6)
        ent_valor.insert(0, f"{cliente['saldo_fiado']:.2f}".replace('.', ','))

        tk.Label(dlg, text='FORMA DE PAGAMENTO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        combo_forma = ttk.Combobox(dlg, state='readonly', font=(FONTE, 10), values=op.FORMAS_PAGAMENTO_FIADO)
        combo_forma.set(op.FORMAS_PAGAMENTO_FIADO[0])
        combo_forma.pack(fill='x', padx=24, ipady=4)

        tk.Label(dlg, text='OBSERVAÇÃO (OPCIONAL)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        ent_obs = tk.Entry(dlg, font=(FONTE, 10), relief='solid', bd=1,
                            highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_obs.pack(fill='x', padx=24, ipady=5)
        _uppercase_ao_digitar(ent_obs)

        def confirmar():
            valor = self._para_float(ent_valor.get(), 0)
            if valor <= 0:
                messagebox.showerror('Valor', 'Informe um valor maior que zero.', parent=dlg)
                return
            try:
                op.registrar_pagamento_fiado(cliente['id'], valor, ent_obs.get(), combo_forma.get())
                dlg.destroy()
                self._carrega_clientes()
                self._toast(f"Pagamento de {self._moeda(valor)} ({combo_forma.get()}) registrado pra {cliente['nome']}.")
            except Exception as exc:
                messagebox.showerror('Erro', str(exc), parent=dlg)

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=22, side='bottom')
        ttk.Button(botoes, text='Confirmar pagamento', style='Primary.TButton', command=confirmar).pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))
        ent_valor.focus_set()
        ent_valor.selection_range(0, 'end')

    def _abrir_ajustar_saldo(self):
        sel = self.tvcli.selection()
        if not sel:
            messagebox.showinfo('Selecione um cliente', 'Clique em um cliente na lista primeiro.')
            return
        cliente = self._clientes_cache[int(sel[0])]

        dlg = tk.Toplevel(self)
        dlg.title(f'Ajustar saldo — {cliente["nome"]}')
        dlg.geometry('440x480')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.resizable(False, False)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text=cliente['nome'], bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 15, 'bold')).pack(anchor='w', padx=24, pady=(16, 0))
        tk.Label(dlg, text=self._texto_saldo(cliente['saldo_fiado']), bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 10)).pack(anchor='w', padx=24, pady=(0, 12))

        tk.Label(dlg, text='O QUE ACONTECEU?', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24)
        direcao = tk.StringVar(value='credita')
        opcoes = tk.Frame(dlg, bg=COR['branco'])
        opcoes.pack(fill='x', padx=24, pady=(4, 12))
        tk.Radiobutton(opcoes, text='Cliente pagou / deixou a mais  →  diminui a dívida (ou vira crédito)',
                       value='credita', variable=direcao, bg=COR['branco'], font=(FONTE, 9), wraplength=380, justify='left', anchor='w').pack(fill='x', pady=2)
        tk.Radiobutton(opcoes, text='Cliente levou a mais / ficou devendo  →  aumenta a dívida (ou usa o crédito)',
                       value='debita', variable=direcao, bg=COR['branco'], font=(FONTE, 9), wraplength=380, justify='left', anchor='w').pack(fill='x', pady=2)

        tk.Label(dlg, text='VALOR (R$)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(4, 3))
        ent_valor = tk.Entry(dlg, font=('Consolas', 13), relief='solid', bd=1,
                              highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_valor.pack(fill='x', padx=24, ipady=6)

        tk.Label(dlg, text='FORMA DE PAGAMENTO (SE FOR UM PAGAMENTO RECEBIDO)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        combo_forma = ttk.Combobox(dlg, state='readonly', font=(FONTE, 10), values=[''] + op.FORMAS_PAGAMENTO_FIADO)
        combo_forma.set('')
        combo_forma.pack(fill='x', padx=24, ipady=4)

        tk.Label(dlg, text='OBSERVAÇÃO (OPCIONAL)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        ent_obs = tk.Entry(dlg, font=(FONTE, 10), relief='solid', bd=1,
                            highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_obs.pack(fill='x', padx=24, ipady=5)
        _uppercase_ao_digitar(ent_obs)

        def confirmar():
            valor = self._para_float(ent_valor.get(), 0)
            if valor <= 0:
                messagebox.showerror('Valor', 'Informe um valor maior que zero.', parent=dlg)
                return
            if direcao.get() == 'debita':
                valor = -valor
            try:
                op.ajustar_saldo_cliente(cliente['id'], valor, ent_obs.get(), combo_forma.get())
                dlg.destroy()
                self._carrega_clientes()
            except Exception as exc:
                messagebox.showerror('Erro', str(exc), parent=dlg)

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=22, side='bottom')
        ttk.Button(botoes, text='Confirmar', style='Primary.TButton', command=confirmar).pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))
        ent_valor.focus_set()

    def _abrir_cascos_cliente(self):
        sel = self.tvcli.selection()
        if not sel:
            messagebox.showinfo('Selecione um cliente', 'Clique em um cliente na lista primeiro.')
            return
        cliente = self._clientes_cache[int(sel[0])]

        dlg = tk.Toplevel(self)
        dlg.title(f'Cascos — {cliente["nome"]}')
        dlg.geometry('480x620')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text=cliente['nome'], bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 15, 'bold')).pack(anchor='w', padx=24, pady=(16, 0))
        label_saldo_total = tk.Label(dlg, text='', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 10, 'bold'))
        label_saldo_total.pack(anchor='w', padx=24, pady=(0, 4))
        frame_tipos = tk.Frame(dlg, bg=COR['branco'])
        frame_tipos.pack(anchor='w', padx=24, pady=(0, 12), fill='x')

        def atualizar_saldos():
            label_saldo_total.config(text=cascos.texto_saldo(cascos.saldo_casco(cliente['id'])) + ' (todos os tipos)')
            for w in frame_tipos.winfo_children():
                w.destroy()
            detalhado = cascos.saldos_por_tipo(cliente['id'])
            if detalhado:
                for d in detalhado:
                    tk.Label(frame_tipos, text=f"{d['tipo_casco']}: {cascos.texto_saldo(d['saldo'])}",
                             bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9)).pack(anchor='w')

        tk.Label(dlg, text='TIPO DE CASCO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24)
        combo_tipo = ttk.Combobox(dlg, values=cascos.TIPOS_PADRAO, font=(FONTE, 10))
        combo_tipo.set('Coca')
        combo_tipo.pack(fill='x', padx=24, pady=(4, 12))

        tk.Label(dlg, text='O QUE ACONTECEU?', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24)
        direcao = tk.StringVar(value='pegou')
        opcoes = tk.Frame(dlg, bg=COR['branco'])
        opcoes.pack(fill='x', padx=24, pady=(4, 12))
        tk.Radiobutton(opcoes, text='Pegou casco(s) emprestado(s)  →  aumenta o quanto deve',
                       value='pegou', variable=direcao, bg=COR['branco'], font=(FONTE, 9), wraplength=400, justify='left', anchor='w').pack(fill='x', pady=2)
        tk.Radiobutton(opcoes, text='Devolveu / deixou casco(s)  →  diminui a dívida (ou vira crédito)',
                       value='devolveu', variable=direcao, bg=COR['branco'], font=(FONTE, 9), wraplength=400, justify='left', anchor='w').pack(fill='x', pady=2)

        tk.Label(dlg, text='QUANTIDADE', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(4, 3))
        ent_qtd = tk.Entry(dlg, font=('Consolas', 13), relief='solid', bd=1,
                            highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_qtd.pack(fill='x', padx=24, ipady=6)

        tk.Label(dlg, text='OBSERVAÇÃO (OPCIONAL)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        ent_obs = tk.Entry(dlg, font=(FONTE, 10), relief='solid', bd=1,
                            highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_obs.pack(fill='x', padx=24, ipady=5)
        _uppercase_ao_digitar(ent_obs)

        def confirmar():
            try:
                cascos.registrar_movimento(cliente['id'], combo_tipo.get(), self._para_float(ent_qtd.get(), 0), direcao.get(), ent_obs.get())
                ent_qtd.delete(0, 'end')
                ent_obs.delete(0, 'end')
                atualizar_saldos()
                self._carrega_clientes()
                self._toast('Movimento de casco registrado.')
            except Exception as exc:
                messagebox.showerror('Erro', str(exc), parent=dlg)

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=(6, 12))
        ttk.Button(botoes, text='Registrar', style='Primary.TButton', command=confirmar).pack(side='right')

        tk.Label(dlg, text='HISTÓRICO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(8, 4))
        tv_hist = ttk.Treeview(dlg, columns=('quando', 'tipo', 'qtd', 'obs'), show='headings', height=8)
        tv_hist.heading('quando', text='Quando')
        tv_hist.heading('tipo', text='Tipo')
        tv_hist.heading('qtd', text='Qtd')
        tv_hist.heading('obs', text='Observação')
        tv_hist.column('quando', width=110)
        tv_hist.column('tipo', width=80)
        tv_hist.column('qtd', width=60, anchor='center')
        tv_hist.column('obs', width=150)
        tv_hist.pack(fill='both', expand=True, padx=24, pady=(0, 12))

        def recarregar_historico():
            tv_hist.delete(*tv_hist.get_children())
            for h in cascos.historico_casco(cliente['id']):
                try:
                    quando = datetime.strptime(h['data_hora'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m %H:%M')
                except ValueError:
                    quando = h['data_hora']
                sinal = '+' if h['quantidade'] > 0 else ''
                tv_hist.insert('', 'end', values=(quando, h['tipo_casco'], f"{sinal}{h['quantidade']}", h['observacao']))

        atualizar_saldos()
        recarregar_historico()
        ent_qtd.bind('<Return>', lambda e: (confirmar(), recarregar_historico()))
        ttk.Button(dlg, text='Fechar', style='Secondary.TButton', command=dlg.destroy).pack(pady=(0, 18))
        ent_qtd.focus_set()

        # garante que o histórico atualize junto com o registro
        botoes.winfo_children()[0].config(command=lambda: (confirmar(), recarregar_historico()))

    # --- Consumo interno: o que a própria casa/família tira do estoque do mercadinho.
    # Dá baixa a preço de CUSTO (não é venda), separado do que é vendido pro cliente, com
    # motivo (produção/consumo pessoal) e mostra quanto em R$ foi consumido.

    def _montar_consumo(self):
        p = self.tab_consumo
        p.columnconfigure(0, weight=1)
        p.rowconfigure(3, weight=2)
        p.rowconfigure(5, weight=1)

        cab = tk.Frame(p, bg=COR['papel'])
        cab.grid(row=0, column=0, sticky='ew', pady=(0, 4))
        tk.Label(cab, text='Consumo interno', bg=COR['papel'], fg=COR['verde2'], font=(FONTE, 20, 'bold')).pack(side='left')
        ttk.Button(cab, text='Ver gasto por motivo', style='Secondary.TButton', command=self._abrir_gasto_por_motivo).pack(side='right')
        tk.Label(p, text='Para o que a casa/família tira do estoque do mercadinho (uso na cozinha, produção de bolo, ou consumo pessoal) — não é venda, sai pelo preço de custo.',
                 bg=COR['papel'], fg=COR['cinza'], font=(FONTE, 9), wraplength=1100, justify='left').grid(row=1, column=0, sticky='w', pady=(0, 10))

        cards = tk.Frame(p, bg=COR['papel'])
        cards.grid(row=2, column=0, sticky='ew', pady=(0, 12))
        cards.columnconfigure((0, 1, 2), weight=1)
        self.cards_consumo = {}
        for i, (chave, titulo) in enumerate([('dia', 'CONSUMIDO HOJE'), ('semana', 'ESTA SEMANA'), ('mes', 'ESTE MÊS')]):
            f = tk.Frame(cards, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
            f.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else 6, 0))
            tk.Label(f, text=titulo, bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9, 'bold')).pack(anchor='w', padx=14, pady=(12, 3))
            lbl = tk.Label(f, text='R$ 0,00', bg=COR['branco'], fg=COR['verde2'], font=('Consolas', 18, 'bold'))
            lbl.pack(anchor='w', padx=14)
            lbl_n = tk.Label(f, text='0 registro(s)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8))
            lbl_n.pack(anchor='w', padx=14, pady=(0, 12))
            self.cards_consumo[chave] = {'valor': lbl, 'n': lbl_n}

        meio = tk.Frame(p, bg=COR['papel'])
        meio.grid(row=3, column=0, sticky='nsew', pady=(0, 12))
        meio.columnconfigure(0, weight=7)
        meio.columnconfigure(1, weight=3)
        meio.rowconfigure(0, weight=1)

        esquerda = tk.Frame(meio, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        esquerda.grid(row=0, column=0, sticky='nsew')
        esquerda.columnconfigure(0, weight=1)
        esquerda.rowconfigure(0, weight=1)

        tk.Label(esquerda, text='ITENS DESTE CONSUMO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9, 'bold')).grid(row=0, column=0, sticky='w', padx=16, pady=(14, 6))
        painel_car = tk.Frame(esquerda, bg=COR['branco'])
        painel_car.grid(row=1, column=0, sticky='nsew', padx=16, pady=(0, 8))
        painel_car.rowconfigure(0, weight=1)
        painel_car.columnconfigure(0, weight=1)
        self.tree_consumo = ttk.Treeview(painel_car, columns=('nome', 'qtd', 'sub'), show='headings', height=8, style='Carrinho.Treeview')
        self.tree_consumo.heading('nome', text='Produto')
        self.tree_consumo.heading('qtd', text='Qtd')
        self.tree_consumo.heading('sub', text='Custo')
        self.tree_consumo.column('nome', width=320)
        self.tree_consumo.column('qtd', width=90, anchor='center')
        self.tree_consumo.column('sub', width=110, anchor='e')
        self.tree_consumo.tag_configure('par', background=COR['branco'])
        self.tree_consumo.tag_configure('impar', background=COR['zebra'])
        self.tree_consumo.grid(row=0, column=0, sticky='nsew')
        sc_con = ttk.Scrollbar(painel_car, orient='vertical', command=self.tree_consumo.yview)
        sc_con.grid(row=0, column=1, sticky='ns')
        self.tree_consumo.configure(yscrollcommand=sc_con.set)
        self.tree_consumo.bind('<Delete>', lambda e: self._remover_consumo_item())

        botoes_c = tk.Frame(esquerda, bg=COR['branco'])
        botoes_c.grid(row=2, column=0, sticky='ew', padx=16, pady=(0, 6))
        ttk.Button(botoes_c, text='−  Qtd', width=8, command=lambda: self._alterar_qtd_consumo(-1)).pack(side='left')
        ttk.Button(botoes_c, text='+  Qtd', width=8, command=lambda: self._alterar_qtd_consumo(1)).pack(side='left', padx=6)
        ttk.Button(botoes_c, text='Remover item (Del)', command=self._remover_consumo_item).pack(side='left')

        tk.Label(esquerda, text='MOTIVO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).grid(row=3, column=0, sticky='w', padx=16, pady=(4, 2))
        self.combo_motivo_consumo = ttk.Combobox(esquerda, values=op.MOTIVOS_CONSUMO, font=(FONTE, 9))
        self.combo_motivo_consumo.set(op.MOTIVOS_CONSUMO[0])
        self.combo_motivo_consumo.grid(row=4, column=0, sticky='ew', padx=16, pady=(0, 6))
        _uppercase_ao_digitar(self.combo_motivo_consumo)

        tk.Label(esquerda, text='OBSERVAÇÃO (OPCIONAL)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).grid(row=5, column=0, sticky='w', padx=16, pady=(4, 2))
        self.entrada_obs_consumo = tk.Entry(esquerda, font=(FONTE, 10), relief='solid', bd=1,
                                             highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        self.entrada_obs_consumo.grid(row=6, column=0, sticky='ew', padx=16, pady=(0, 8), ipady=4)
        _uppercase_ao_digitar(self.entrada_obs_consumo)

        rodape_c = tk.Frame(esquerda, bg=COR['amarelo'])
        rodape_c.grid(row=7, column=0, sticky='ew', padx=16, pady=(0, 6))
        tk.Label(rodape_c, text='Total (a preço de custo):', bg=COR['amarelo'], fg=COR['verde2'], font=(FONTE, 9, 'bold')).pack(side='left', padx=10, pady=8)
        self.lbl_total_consumo = tk.Label(rodape_c, text='R$ 0,00', bg=COR['amarelo'], fg=COR['verde2'], font=('Consolas', 14, 'bold'))
        self.lbl_total_consumo.pack(side='right', padx=10)

        ttk.Button(esquerda, text='REGISTRAR CONSUMO', style='Primary.TButton', command=self._confirmar_consumo).grid(row=8, column=0, sticky='ew', padx=16, pady=(0, 14))

        direita = tk.Frame(meio, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        direita.grid(row=0, column=1, sticky='nsew', padx=(10, 0))
        direita.columnconfigure(0, weight=1)
        direita.rowconfigure(3, weight=1)
        tk.Label(direita, text='BUSCAR PRODUTO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9, 'bold')).grid(row=0, column=0, sticky='w', padx=16, pady=(14, 5))
        self.entrada_consumo = tk.Entry(direita, font=(FONTE, 13), relief='solid', bd=1,
                                         highlightthickness=2, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        self.entrada_consumo.grid(row=1, column=0, sticky='ew', padx=16, pady=(0, 6), ipady=6)
        self.entrada_consumo.bind('<KeyRelease>', self._busca_tecla_consumo)
        self.entrada_consumo.bind('<Return>', self._enter_busca_consumo)
        self.entrada_consumo.bind('<Down>', self._seta_consumo)
        self.entrada_consumo.bind('<Up>', self._seta_consumo)
        _uppercase_ao_digitar(self.entrada_consumo)

        add_frame_c = tk.Frame(direita, bg=COR['branco'])
        add_frame_c.grid(row=2, column=0, sticky='ew', padx=16, pady=(0, 8))
        tk.Label(add_frame_c, text='QTD', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(side='left')
        self.qtd_consumo = tk.Entry(add_frame_c, font=('Consolas', 12), width=6, relief='solid', bd=1, justify='center')
        self.qtd_consumo.insert(0, '1')
        self.qtd_consumo.pack(side='left', padx=(4, 6), ipady=2)
        self.qtd_consumo.bind('<Return>', lambda e: self._adicionar_selecionado_consumo())
        ttk.Button(add_frame_c, text='Adicionar', style='Primary.TButton', command=self._adicionar_selecionado_consumo).pack(side='left', padx=(0, 8))
        for txt, val in [('+1', '1'), ('+5', '5'), ('+10', '10')]:
            ttk.Button(add_frame_c, text=txt, width=4,
                       command=lambda v=val: (self.qtd_consumo.delete(0, 'end'), self.qtd_consumo.insert(0, v))).pack(side='left', padx=2)

        tvb = tk.Frame(direita, bg=COR['branco'])
        tvb.grid(row=3, column=0, sticky='nsew', padx=16, pady=(0, 14))
        tvb.rowconfigure(0, weight=1)
        tvb.columnconfigure(0, weight=1)
        self.tree_busca_consumo = ttk.Treeview(tvb, columns=('nome', 'estoque', 'custo'), show='headings')
        self.tree_busca_consumo.heading('nome', text='Produto')
        self.tree_busca_consumo.heading('estoque', text='Estoque')
        self.tree_busca_consumo.heading('custo', text='Custo')
        self.tree_busca_consumo.column('nome', width=150)
        self.tree_busca_consumo.column('estoque', width=65, anchor='center')
        self.tree_busca_consumo.column('custo', width=65, anchor='e')
        self.tree_busca_consumo.tag_configure('par', background=COR['branco'])
        self.tree_busca_consumo.tag_configure('impar', background=COR['zebra'])
        self.tree_busca_consumo.bind('<Double-1>', lambda e: self._adicionar_selecionado_consumo())
        self.tree_busca_consumo.grid(row=0, column=0, sticky='nsew')
        scb = ttk.Scrollbar(tvb, orient='vertical', command=self.tree_busca_consumo.yview)
        scb.grid(row=0, column=1, sticky='ns')
        self.tree_busca_consumo.configure(yscrollcommand=scb.set)

        tk.Label(p, text='HISTÓRICO DE CONSUMO', bg=COR['papel'], fg=COR['cinza'], font=(FONTE, 9, 'bold')).grid(row=4, column=0, sticky='w', pady=(0, 4))
        bloco_hist = tk.Frame(p, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_hist.grid(row=5, column=0, sticky='nsew')
        bloco_hist.rowconfigure(0, weight=1)
        bloco_hist.columnconfigure(0, weight=1)
        self.tree_hist_consumo = ttk.Treeview(bloco_hist, columns=('data', 'motivo', 'valor'), show='headings', height=6)
        self.tree_hist_consumo.heading('data', text='Data/hora')
        self.tree_hist_consumo.heading('motivo', text='Motivo')
        self.tree_hist_consumo.heading('valor', text='Valor (custo)')
        self.tree_hist_consumo.column('data', width=160)
        self.tree_hist_consumo.column('motivo', width=300)
        self.tree_hist_consumo.column('valor', width=120, anchor='e')
        self.tree_hist_consumo.tag_configure('par', background=COR['branco'])
        self.tree_hist_consumo.tag_configure('impar', background=COR['zebra'])
        self.tree_hist_consumo.bind('<Double-1>', lambda e: self._ver_detalhe_consumo())
        self.tree_hist_consumo.grid(row=0, column=0, sticky='nsew')
        sch = ttk.Scrollbar(bloco_hist, orient='vertical', command=self.tree_hist_consumo.yview)
        sch.grid(row=0, column=1, sticky='ns')
        self.tree_hist_consumo.configure(yscrollcommand=sch.set)

        self._carrega_resumo_consumo()
        self._carrega_historico_consumo()

    def _carrega_resumo_consumo(self):
        dados = op.resumo_consumo_interno()
        for chave, cartao in self.cards_consumo.items():
            d = dados[chave]
            cartao['valor'].config(text=self._moeda(d['valor_total']))
            plural = '' if d['numero'] == 1 else 's'
            cartao['n'].config(text=f"{d['numero']} registro{plural}")

    def _abrir_gasto_por_motivo(self):
        dlg = tk.Toplevel(self)
        dlg.title('Gasto por motivo')
        dlg.geometry('520x460')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Gasto por motivo', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 15, 'bold')).pack(anchor='w', padx=24, pady=(16, 4))
        tk.Label(dlg, text='Separa o que foi embalagem/insumo operacional do que foi produção ou consumo pessoal — tudo sai do estoque pelo preço de custo, mas o motivo importa pra saber onde o dinheiro está indo.',
                 bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9), wraplength=460, justify='left').pack(anchor='w', padx=24, pady=(0, 12))

        periodo = tk.StringVar(value='mes')
        sel = tk.Frame(dlg, bg=COR['branco'])
        sel.pack(anchor='w', padx=24, pady=(0, 10))
        for texto, valor in [('7 dias', '7dias'), ('30 dias', '30dias'), ('Este mês', 'mes'), ('Tudo', 'tudo')]:
            ttk.Radiobutton(sel, text=texto, value=valor, variable=periodo, command=lambda: atualizar()).pack(side='left', padx=(0, 10))

        tv = ttk.Treeview(dlg, columns=('motivo', 'n', 'total'), show='headings', height=8)
        tv.heading('motivo', text='Motivo')
        tv.heading('n', text='Registros')
        tv.heading('total', text='Total (custo)')
        tv.column('motivo', width=280)
        tv.column('n', width=80, anchor='center')
        tv.column('total', width=110, anchor='e')
        tv.tag_configure('par', background=COR['branco'])
        tv.tag_configure('impar', background=COR['zebra'])
        tv.pack(fill='both', expand=True, padx=24, pady=(0, 8))
        label_total = tk.Label(dlg, text='', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 11, 'bold'))
        label_total.pack(anchor='e', padx=24, pady=(0, 16))

        def atualizar():
            inicio, fim = an.periodo_preset(periodo.get())
            dados = op.resumo_consumo_por_motivo(inicio, fim)
            tv.delete(*tv.get_children())
            for i, d in enumerate(dados):
                tag = 'par' if i % 2 == 0 else 'impar'
                tv.insert('', 'end', tags=(tag,), values=(d['motivo'], d['n'], self._moeda(d['total'])))
            label_total.config(text=f"Total: {self._moeda(sum(d['total'] for d in dados))}")

        atualizar()
        ttk.Button(dlg, text='Fechar', style='Secondary.TButton', command=dlg.destroy).pack(pady=(0, 18))

    def _carrega_historico_consumo(self):
        self._consumo_hist_cache = {}
        self.tree_hist_consumo.delete(*self.tree_hist_consumo.get_children())
        for i, c in enumerate(op.listar_consumo_interno()):
            self._consumo_hist_cache[c['id']] = c
            tag = 'par' if i % 2 == 0 else 'impar'
            self.tree_hist_consumo.insert('', 'end', iid=str(c['id']), tags=(tag,),
                                           values=(c['data_hora'], c['motivo'] or '—', self._moeda(c['valor_total'])))

    def _ver_detalhe_consumo(self):
        sel = self.tree_hist_consumo.selection()
        if not sel:
            return
        dados = op.detalhar_consumo_interno(int(sel[0]))
        if not dados:
            return

        dlg = tk.Toplevel(self)
        dlg.title(f'Consumo #{dados["id"]}')
        dlg.geometry('480x480')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text=dados['data_hora'], bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 14, 'bold')).pack(anchor='w', padx=24, pady=(16, 0))
        tk.Label(dlg, text=dados['motivo'] or 'Sem motivo informado', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 10)).pack(anchor='w', padx=24, pady=(0, 4))
        if dados['observacao']:
            tk.Label(dlg, text=dados['observacao'], bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9), wraplength=420, justify='left').pack(anchor='w', padx=24, pady=(0, 10))

        tv = ttk.Treeview(dlg, columns=('nome', 'qtd', 'sub'), show='headings', height=10)
        tv.heading('nome', text='Produto')
        tv.heading('qtd', text='Qtd')
        tv.heading('sub', text='Custo')
        tv.column('nome', width=230)
        tv.column('qtd', width=90, anchor='center')
        tv.column('sub', width=100, anchor='e')
        tv.tag_configure('par', background=COR['branco'])
        tv.tag_configure('impar', background=COR['zebra'])
        tv.pack(fill='both', expand=True, padx=24, pady=(0, 12))
        for i, item in enumerate(dados['itens']):
            tag = 'par' if i % 2 == 0 else 'impar'
            tv.insert('', 'end', tags=(tag,), values=(item['nome'], self._formatq(item['quantidade'], item['unidade']), self._moeda(item['subtotal'])))

        tk.Label(dlg, text=f"Total: {self._moeda(dados['valor_total'])}", bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 12, 'bold')).pack(anchor='e', padx=24, pady=(0, 10))
        ttk.Button(dlg, text='Fechar', style='Secondary.TButton', command=dlg.destroy).pack(pady=(0, 18))

    def _busca_tecla_consumo(self, event):
        if event.keysym in ('Return', 'Up', 'Down'):
            return
        if hasattr(self, '_deb_consumo'):
            self.after_cancel(self._deb_consumo)
        self._deb_consumo = self.after(150, self._executar_busca_consumo)

    def _executar_busca_consumo(self):
        termo = self.entrada_consumo.get().strip()
        self.tree_busca_consumo.delete(*self.tree_busca_consumo.get_children())
        self._resultados_consumo = []
        if not termo:
            return
        produtos = op.listar_produtos(termo)
        self._resultados_consumo = produtos
        for i, pr in enumerate(produtos):
            tag = 'par' if i % 2 == 0 else 'impar'
            self.tree_busca_consumo.insert('', 'end', iid=str(pr['id']), tags=(tag,),
                                            values=(pr['nome'], self._formatq(pr['quantidade_estoque'], pr['unidade']), self._moeda(pr['preco_custo'])))
        if self._resultados_consumo:
            self.tree_busca_consumo.selection_set(str(self._resultados_consumo[0]['id']))
            self.tree_busca_consumo.focus(str(self._resultados_consumo[0]['id']))

    def _seta_consumo(self, event):
        ids = self.tree_busca_consumo.get_children()
        if not ids:
            return 'break'
        atual = self.tree_busca_consumo.selection()
        idx = ids.index(atual[0]) if atual else (0 if event.keysym == 'Down' else len(ids) - 1)
        idx = min(len(ids) - 1, idx + 1) if event.keysym == 'Down' else max(0, idx - 1)
        self.tree_busca_consumo.selection_set(ids[idx])
        self.tree_busca_consumo.see(ids[idx])
        return 'break'

    def _enter_busca_consumo(self, event):
        termo = self.entrada_consumo.get().strip()
        sel = self.tree_busca_consumo.selection()
        if sel:
            produto = next((pr for pr in self._resultados_consumo if pr['id'] == int(sel[0])), None)
            if produto:
                qtd = self._para_float(self.qtd_consumo.get(), 0)
                self._adicionar_consumo(produto, qtd if qtd > 0 else None)
                self._limpar_busca_consumo()
                self.qtd_consumo.delete(0, 'end')
                self.qtd_consumo.insert(0, '1')
                return
        produto = op.buscar_por_codigo(termo)
        if produto:
            qtd = self._para_float(self.qtd_consumo.get(), 0)
            self._adicionar_consumo(produto, qtd if qtd > 0 else None)
            self._limpar_busca_consumo()
            self.qtd_consumo.delete(0, 'end')
            self.qtd_consumo.insert(0, '1')
            return
        self._executar_busca_consumo()
        if len(self._resultados_consumo) == 1:
            qtd = self._para_float(self.qtd_consumo.get(), 0)
            self._adicionar_consumo(self._resultados_consumo[0], qtd if qtd > 0 else None)
            self._limpar_busca_consumo()
            self.qtd_consumo.delete(0, 'end')
            self.qtd_consumo.insert(0, '1')

    def _adicionar_selecionado_consumo(self):
        sel = self.tree_busca_consumo.selection()
        if not sel:
            messagebox.showinfo('Selecione um produto', 'Clique num produto da lista de busca primeiro.', parent=self)
            return
        produto = next((pr for pr in self._resultados_consumo if pr['id'] == int(sel[0])), None)
        if produto:
            qtd = self._para_float(self.qtd_consumo.get(), 0)
            self._adicionar_consumo(produto, qtd if qtd > 0 else None)
            self._limpar_busca_consumo()
            self.qtd_consumo.delete(0, 'end')
            self.qtd_consumo.insert(0, '1')

    def _adicionar_consumo(self, produto, qtd=None):
        if qtd is None:
            if produto['unidade'] == 'KG':
                texto = simpledialog.askstring('Peso', 'Peso em kg (ex.: 1,325):', parent=self)
                if texto is None:
                    return
                qtd = self._para_float(texto, 0)
            else:
                qtd = 1
        if qtd <= 0:
            messagebox.showwarning('Quantidade', 'Informe uma quantidade maior que zero.')
            return
        qtd = round(float(qtd), 3)
        existente = next((i for i in self.carrinho_consumo if i['produto_id'] == produto['id']), None)
        ja_no_carrinho = existente['quantidade'] if existente else 0
        disponivel = float(produto['quantidade_estoque']) - ja_no_carrinho
        if qtd > disponivel + 0.001:
            if not messagebox.askyesno('Estoque insuficiente',
                    f'Estoque atual de {produto["nome"]}: {self._formatq(produto["quantidade_estoque"], produto["unidade"])}\n'
                    f'Já no carrinho deste consumo: {self._formatq(ja_no_carrinho, produto["unidade"])}\n\n'
                    f'Deseja adicionar mesmo assim?'):
                return
        if existente:
            existente['quantidade'] = round(existente['quantidade'] + qtd, 3)
        else:
            self.carrinho_consumo.append({
                'produto_id': produto['id'], 'nome': produto['nome'],
                'preco_custo': produto['preco_custo'], 'quantidade': qtd, 'unidade': produto['unidade'],
            })
        self._render_carrinho_consumo()

    def _limpar_busca_consumo(self):
        self.entrada_consumo.delete(0, 'end')
        self.tree_busca_consumo.delete(*self.tree_busca_consumo.get_children())
        self.entrada_consumo.focus_set()

    def _render_carrinho_consumo(self, selecionar_idx=None):
        if selecionar_idx is None:
            sel = self.tree_consumo.selection()
            if sel:
                idx_sel = int(sel[0])
                if idx_sel < len(self.carrinho_consumo):
                    selecionar_idx = idx_sel
        self.tree_consumo.delete(*self.tree_consumo.get_children())
        for i, item in enumerate(self.carrinho_consumo):
            subtotal = item['quantidade'] * item['preco_custo']
            tag = 'par' if i % 2 == 0 else 'impar'
            self.tree_consumo.insert('', 'end', iid=str(i), tags=(tag,),
                                      values=(item['nome'], self._formatq(item['quantidade'], item['unidade']), self._moeda(subtotal)))
        if selecionar_idx is not None and selecionar_idx < len(self.carrinho_consumo):
            self.tree_consumo.selection_set(str(selecionar_idx))
            self.tree_consumo.focus(str(selecionar_idx))
            self.tree_consumo.see(str(selecionar_idx))
        total = sum(i['quantidade'] * i['preco_custo'] for i in self.carrinho_consumo)
        self.lbl_total_consumo.config(text=self._moeda(total))

    def _alterar_qtd_consumo(self, delta):
        sel = self.tree_consumo.selection()
        if not sel:
            return
        idx = int(sel[0])
        item = self.carrinho_consumo[idx]
        passo = 0.1 if item['unidade'] == 'KG' else 1
        item['quantidade'] = round(item['quantidade'] + passo * delta, 3)
        if item['quantidade'] <= 0:
            self.carrinho_consumo.pop(idx)
            idx = min(idx, len(self.carrinho_consumo) - 1) if self.carrinho_consumo else None
        self._render_carrinho_consumo(selecionar_idx=idx)

    def _remover_consumo_item(self):
        sel = self.tree_consumo.selection()
        if sel:
            self.carrinho_consumo.pop(int(sel[0]))
            self._render_carrinho_consumo()

    def _confirmar_consumo(self):
        if not self.carrinho_consumo:
            messagebox.showinfo('Consumo', 'Adicione ao menos um item na lista usando a busca à direita.')
            return
        motivo = self.combo_motivo_consumo.get().strip()
        observacao = self.entrada_obs_consumo.get().strip()
        total = sum(i['quantidade'] * i['preco_custo'] for i in self.carrinho_consumo)
        itens_txt = '\n'.join(f"  {item['nome']}  x{item['quantidade']:.3g}  =  {self._moeda(item['quantidade'] * item['preco_custo'])}" for item in self.carrinho_consumo)
        if not messagebox.askyesno('Confirmar consumo interno',
                f"Itens ({len(self.carrinho_consumo)}):\n{itens_txt}\n\n"
                f"Total (custo): {self._moeda(total)}\n"
                f"Motivo: {motivo or 'Não informado'}\n\n"
                f"Baixar do estoque?"):
            return
        itens = [{'produto_id': i['produto_id'], 'quantidade': i['quantidade']} for i in self.carrinho_consumo]
        try:
            r = op.registrar_consumo_interno(itens, motivo, observacao)
            self.carrinho_consumo = []
            self._render_carrinho_consumo()
            self.entrada_obs_consumo.delete(0, 'end')
            self._carrega_resumo_consumo()
            self._carrega_historico_consumo()
            self._carrega_produtos()
            self._toast(f"Consumo de {self._moeda(r['valor_total'])} registrado com sucesso.")
        except Exception as exc:
            messagebox.showerror('Erro', str(exc))

    def _montar_perdas(self):
        p = self.tab_perdas
        p.columnconfigure(0, weight=1)
        p.rowconfigure(3, weight=2)
        p.rowconfigure(5, weight=1)

        cab = tk.Frame(p, bg=COR['papel'])
        cab.grid(row=0, column=0, sticky='ew', pady=(0, 4))
        tk.Label(cab, text='Perdas', bg=COR['papel'], fg=COR['verde2'], font=(FONTE, 20, 'bold')).pack(side='left')
        tk.Label(p, text='Para o que teve que ser jogado fora — venceu, estragou, quebrou. Diferente do consumo interno: aqui ninguém aproveitou nada, é prejuízo puro. Sai do estoque pelo preço de custo.',
                 bg=COR['papel'], fg=COR['cinza'], font=(FONTE, 9), wraplength=1100, justify='left').grid(row=1, column=0, sticky='w', pady=(0, 10))

        cards = tk.Frame(p, bg=COR['papel'])
        cards.grid(row=2, column=0, sticky='ew', pady=(0, 12))
        cards.columnconfigure((0, 1, 2), weight=1)
        self.cards_perda = {}
        for i, (chave, titulo) in enumerate([('dia', 'PERDIDO HOJE'), ('semana', 'ESTA SEMANA'), ('mes', 'ESTE MÊS')]):
            f = tk.Frame(cards, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
            f.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else 6, 0))
            tk.Label(f, text=titulo, bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9, 'bold')).pack(anchor='w', padx=14, pady=(12, 3))
            lbl = tk.Label(f, text='R$ 0,00', bg=COR['branco'], fg=COR['verde2'], font=('Consolas', 18, 'bold'))
            lbl.pack(anchor='w', padx=14)
            lbl_n = tk.Label(f, text='0 registro(s)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8))
            lbl_n.pack(anchor='w', padx=14, pady=(0, 12))
            self.cards_perda[chave] = {'valor': lbl, 'n': lbl_n}

        meio = tk.Frame(p, bg=COR['papel'])
        meio.grid(row=3, column=0, sticky='nsew', pady=(0, 12))
        meio.columnconfigure(0, weight=7)
        meio.columnconfigure(1, weight=3)
        meio.rowconfigure(0, weight=1)

        esquerda = tk.Frame(meio, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        esquerda.grid(row=0, column=0, sticky='nsew')
        esquerda.columnconfigure(0, weight=1)
        esquerda.rowconfigure(0, weight=1)

        tk.Label(esquerda, text='ITENS DESTA PERDA', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9, 'bold')).grid(row=0, column=0, sticky='w', padx=16, pady=(14, 6))
        painel_perda_car = tk.Frame(esquerda, bg=COR['branco'])
        painel_perda_car.grid(row=1, column=0, sticky='nsew', padx=16, pady=(0, 8))
        painel_perda_car.rowconfigure(0, weight=1)
        painel_perda_car.columnconfigure(0, weight=1)
        self.tree_perda = ttk.Treeview(painel_perda_car, columns=('nome', 'qtd', 'sub'), show='headings', height=8, style='Carrinho.Treeview')
        self.tree_perda.heading('nome', text='Produto')
        self.tree_perda.heading('qtd', text='Qtd')
        self.tree_perda.heading('sub', text='Custo')
        self.tree_perda.column('nome', width=320)
        self.tree_perda.column('qtd', width=90, anchor='center')
        self.tree_perda.column('sub', width=110, anchor='e')
        self.tree_perda.tag_configure('par', background=COR['branco'])
        self.tree_perda.tag_configure('impar', background=COR['zebra'])
        self.tree_perda.grid(row=0, column=0, sticky='nsew')
        sc_perda = ttk.Scrollbar(painel_perda_car, orient='vertical', command=self.tree_perda.yview)
        sc_perda.grid(row=0, column=1, sticky='ns')
        self.tree_perda.configure(yscrollcommand=sc_perda.set)
        self.tree_perda.bind('<Delete>', lambda e: self._remover_perda_item())

        botoes_c = tk.Frame(esquerda, bg=COR['branco'])
        botoes_c.grid(row=2, column=0, sticky='ew', padx=16, pady=(0, 6))
        ttk.Button(botoes_c, text='−  Qtd', width=8, command=lambda: self._alterar_qtd_perda(-1)).pack(side='left')
        ttk.Button(botoes_c, text='+  Qtd', width=8, command=lambda: self._alterar_qtd_perda(1)).pack(side='left', padx=6)
        ttk.Button(botoes_c, text='Remover item (Del)', command=self._remover_perda_item).pack(side='left')

        tk.Label(esquerda, text='MOTIVO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).grid(row=3, column=0, sticky='w', padx=16, pady=(4, 2))
        self.combo_motivo_perda = ttk.Combobox(esquerda, values=op.MOTIVOS_PERDA, font=(FONTE, 9))
        self.combo_motivo_perda.set(op.MOTIVOS_PERDA[0])
        self.combo_motivo_perda.grid(row=4, column=0, sticky='ew', padx=16, pady=(0, 6))
        _uppercase_ao_digitar(self.combo_motivo_perda)

        tk.Label(esquerda, text='OBSERVAÇÃO (OPCIONAL)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).grid(row=5, column=0, sticky='w', padx=16, pady=(4, 2))
        self.entrada_obs_perda = tk.Entry(esquerda, font=(FONTE, 10), relief='solid', bd=1,
                                             highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        self.entrada_obs_perda.grid(row=6, column=0, sticky='ew', padx=16, pady=(0, 8), ipady=4)
        _uppercase_ao_digitar(self.entrada_obs_perda)

        rodape_perda = tk.Frame(esquerda, bg=COR['amarelo'])
        rodape_perda.grid(row=7, column=0, sticky='ew', padx=16, pady=(0, 6))
        tk.Label(rodape_perda, text='Total (a preço de custo):', bg=COR['amarelo'], fg=COR['verde2'], font=(FONTE, 9, 'bold')).pack(side='left', padx=10, pady=8)
        self.lbl_total_perda = tk.Label(rodape_perda, text='R$ 0,00', bg=COR['amarelo'], fg=COR['verde2'], font=('Consolas', 14, 'bold'))
        self.lbl_total_perda.pack(side='right', padx=10)

        ttk.Button(esquerda, text='REGISTRAR PERDA', style='Primary.TButton', command=self._confirmar_perda).grid(row=8, column=0, sticky='ew', padx=16, pady=(0, 14))

        direita = tk.Frame(meio, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        direita.grid(row=0, column=1, sticky='nsew', padx=(10, 0))
        direita.columnconfigure(0, weight=1)
        direita.rowconfigure(3, weight=1)
        tk.Label(direita, text='BUSCAR PRODUTO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9, 'bold')).grid(row=0, column=0, sticky='w', padx=16, pady=(14, 5))
        self.entrada_perda = tk.Entry(direita, font=(FONTE, 13), relief='solid', bd=1,
                                         highlightthickness=2, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        self.entrada_perda.grid(row=1, column=0, sticky='ew', padx=16, pady=(0, 6), ipady=6)
        self.entrada_perda.bind('<KeyRelease>', self._busca_tecla_perda)
        self.entrada_perda.bind('<Return>', self._enter_busca_perda)
        self.entrada_perda.bind('<Down>', self._seta_perda)
        self.entrada_perda.bind('<Up>', self._seta_perda)
        _uppercase_ao_digitar(self.entrada_perda)

        add_frame_p = tk.Frame(direita, bg=COR['branco'])
        add_frame_p.grid(row=2, column=0, sticky='ew', padx=16, pady=(0, 8))
        tk.Label(add_frame_p, text='QTD', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(side='left')
        self.qtd_perda = tk.Entry(add_frame_p, font=('Consolas', 12), width=6, relief='solid', bd=1, justify='center')
        self.qtd_perda.insert(0, '1')
        self.qtd_perda.pack(side='left', padx=(4, 6), ipady=2)
        self.qtd_perda.bind('<Return>', lambda e: self._adicionar_selecionado_perda())
        ttk.Button(add_frame_p, text='Adicionar', style='Primary.TButton', command=self._adicionar_selecionado_perda).pack(side='left', padx=(0, 8))
        for txt, val in [('+1', '1'), ('+5', '5'), ('+10', '10')]:
            ttk.Button(add_frame_p, text=txt, width=4,
                       command=lambda v=val: (self.qtd_perda.delete(0, 'end'), self.qtd_perda.insert(0, v))).pack(side='left', padx=2)

        tvb = tk.Frame(direita, bg=COR['branco'])
        tvb.grid(row=3, column=0, sticky='nsew', padx=16, pady=(0, 14))
        tvb.rowconfigure(0, weight=1)
        tvb.columnconfigure(0, weight=1)
        self.tree_busca_perda = ttk.Treeview(tvb, columns=('nome', 'estoque', 'custo'), show='headings')
        self.tree_busca_perda.heading('nome', text='Produto')
        self.tree_busca_perda.heading('estoque', text='Estoque')
        self.tree_busca_perda.heading('custo', text='Custo')
        self.tree_busca_perda.column('nome', width=150)
        self.tree_busca_perda.column('estoque', width=65, anchor='center')
        self.tree_busca_perda.column('custo', width=65, anchor='e')
        self.tree_busca_perda.tag_configure('par', background=COR['branco'])
        self.tree_busca_perda.tag_configure('impar', background=COR['zebra'])
        self.tree_busca_perda.bind('<Double-1>', lambda e: self._adicionar_selecionado_perda())
        self.tree_busca_perda.grid(row=0, column=0, sticky='nsew')
        scb_perda = ttk.Scrollbar(tvb, orient='vertical', command=self.tree_busca_perda.yview)
        scb_perda.grid(row=0, column=1, sticky='ns')
        self.tree_busca_perda.configure(yscrollcommand=scb_perda.set)

        tk.Label(p, text='HISTÓRICO DE PERDAS', bg=COR['papel'], fg=COR['cinza'], font=(FONTE, 9, 'bold')).grid(row=4, column=0, sticky='w', pady=(0, 4))
        bloco_hist_perda = tk.Frame(p, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_hist_perda.grid(row=5, column=0, sticky='nsew')
        bloco_hist_perda.rowconfigure(0, weight=1)
        bloco_hist_perda.columnconfigure(0, weight=1)
        self.tree_hist_perda = ttk.Treeview(bloco_hist_perda, columns=('data', 'motivo', 'valor'), show='headings', height=6)
        self.tree_hist_perda.heading('data', text='Data/hora')
        self.tree_hist_perda.heading('motivo', text='Motivo')
        self.tree_hist_perda.heading('valor', text='Valor (custo)')
        self.tree_hist_perda.column('data', width=160)
        self.tree_hist_perda.column('motivo', width=300)
        self.tree_hist_perda.column('valor', width=120, anchor='e')
        self.tree_hist_perda.tag_configure('par', background=COR['branco'])
        self.tree_hist_perda.tag_configure('impar', background=COR['zebra'])
        self.tree_hist_perda.bind('<Double-1>', lambda e: self._ver_detalhe_perda())
        self.tree_hist_perda.grid(row=0, column=0, sticky='nsew')
        sch_perda = ttk.Scrollbar(bloco_hist_perda, orient='vertical', command=self.tree_hist_perda.yview)
        sch_perda.grid(row=0, column=1, sticky='ns')
        self.tree_hist_perda.configure(yscrollcommand=sch_perda.set)

        self._carrega_resumo_perda()
        self._carrega_historico_perda()

    def _carrega_resumo_perda(self):
        dados = op.resumo_perdas()
        for chave, cartao in self.cards_perda.items():
            d = dados[chave]
            cartao['valor'].config(text=self._moeda(d['valor_total']))
            plural = '' if d['numero'] == 1 else 's'
            cartao['n'].config(text=f"{d['numero']} registro{plural}")

    def _carrega_historico_perda(self):
        self._perda_hist_cache = {}
        self.tree_hist_perda.delete(*self.tree_hist_perda.get_children())
        for i, c in enumerate(op.listar_perdas()):
            self._perda_hist_cache[c['id']] = c
            tag = 'par' if i % 2 == 0 else 'impar'
            self.tree_hist_perda.insert('', 'end', iid=str(c['id']), tags=(tag,),
                                           values=(c['data_hora'], c['motivo'] or '—', self._moeda(c['valor_total'])))

    def _ver_detalhe_perda(self):
        sel = self.tree_hist_perda.selection()
        if not sel:
            return
        dados = op.detalhar_perda(int(sel[0]))
        if not dados:
            return

        dlg = tk.Toplevel(self)
        dlg.title(f'Perda #{dados["id"]}')
        dlg.geometry('480x480')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text=dados['data_hora'], bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 14, 'bold')).pack(anchor='w', padx=24, pady=(16, 0))
        tk.Label(dlg, text=dados['motivo'] or 'Sem motivo informado', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 10)).pack(anchor='w', padx=24, pady=(0, 4))
        if dados['observacao']:
            tk.Label(dlg, text=dados['observacao'], bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9), wraplength=420, justify='left').pack(anchor='w', padx=24, pady=(0, 10))

        tv = ttk.Treeview(dlg, columns=('nome', 'qtd', 'sub'), show='headings', height=10)
        tv.heading('nome', text='Produto')
        tv.heading('qtd', text='Qtd')
        tv.heading('sub', text='Custo')
        tv.column('nome', width=230)
        tv.column('qtd', width=90, anchor='center')
        tv.column('sub', width=100, anchor='e')
        tv.tag_configure('par', background=COR['branco'])
        tv.tag_configure('impar', background=COR['zebra'])
        tv.pack(fill='both', expand=True, padx=24, pady=(0, 12))
        for i, item in enumerate(dados['itens']):
            tag = 'par' if i % 2 == 0 else 'impar'
            tv.insert('', 'end', tags=(tag,), values=(item['nome'], self._formatq(item['quantidade'], item['unidade']), self._moeda(item['subtotal'])))

        tk.Label(dlg, text=f"Total: {self._moeda(dados['valor_total'])}", bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 12, 'bold')).pack(anchor='e', padx=24, pady=(0, 10))
        ttk.Button(dlg, text='Fechar', style='Secondary.TButton', command=dlg.destroy).pack(pady=(0, 18))

    def _busca_tecla_perda(self, event):
        if event.keysym in ('Return', 'Up', 'Down'):
            return
        if hasattr(self, '_deb_perda'):
            self.after_cancel(self._deb_perda)
        self._deb_perda = self.after(150, self._executar_busca_perda)

    def _executar_busca_perda(self):
        termo = self.entrada_perda.get().strip()
        self.tree_busca_perda.delete(*self.tree_busca_perda.get_children())
        self._resultados_perda = []
        if not termo:
            return
        produtos = op.listar_produtos(termo)
        self._resultados_perda = produtos
        for i, pr in enumerate(produtos):
            tag = 'par' if i % 2 == 0 else 'impar'
            self.tree_busca_perda.insert('', 'end', iid=str(pr['id']), tags=(tag,),
                                            values=(pr['nome'], self._formatq(pr['quantidade_estoque'], pr['unidade']), self._moeda(pr['preco_custo'])))
        if self._resultados_perda:
            self.tree_busca_perda.selection_set(str(self._resultados_perda[0]['id']))
            self.tree_busca_perda.focus(str(self._resultados_perda[0]['id']))

    def _seta_perda(self, event):
        ids = self.tree_busca_perda.get_children()
        if not ids:
            return 'break'
        atual = self.tree_busca_perda.selection()
        idx = ids.index(atual[0]) if atual else (0 if event.keysym == 'Down' else len(ids) - 1)
        idx = min(len(ids) - 1, idx + 1) if event.keysym == 'Down' else max(0, idx - 1)
        self.tree_busca_perda.selection_set(ids[idx])
        self.tree_busca_perda.see(ids[idx])
        return 'break'

    def _enter_busca_perda(self, event):
        termo = self.entrada_perda.get().strip()
        sel = self.tree_busca_perda.selection()
        if sel:
            produto = next((pr for pr in self._resultados_perda if pr['id'] == int(sel[0])), None)
            if produto:
                qtd = self._para_float(self.qtd_perda.get(), 0)
                self._adicionar_perda(produto, qtd if qtd > 0 else None)
                self._limpar_busca_perda()
                self.qtd_perda.delete(0, 'end')
                self.qtd_perda.insert(0, '1')
                return
        produto = op.buscar_por_codigo(termo)
        if produto:
            qtd = self._para_float(self.qtd_perda.get(), 0)
            self._adicionar_perda(produto, qtd if qtd > 0 else None)
            self._limpar_busca_perda()
            self.qtd_perda.delete(0, 'end')
            self.qtd_perda.insert(0, '1')
            return
        self._executar_busca_perda()
        if len(self._resultados_perda) == 1:
            qtd = self._para_float(self.qtd_perda.get(), 0)
            self._adicionar_perda(self._resultados_perda[0], qtd if qtd > 0 else None)
            self._limpar_busca_perda()
            self.qtd_perda.delete(0, 'end')
            self.qtd_perda.insert(0, '1')

    def _adicionar_selecionado_perda(self):
        sel = self.tree_busca_perda.selection()
        if not sel:
            messagebox.showinfo('Selecione um produto', 'Clique num produto da lista de busca primeiro.', parent=self)
            return
        produto = next((pr for pr in self._resultados_perda if pr['id'] == int(sel[0])), None)
        if produto:
            qtd = self._para_float(self.qtd_perda.get(), 0)
            self._adicionar_perda(produto, qtd if qtd > 0 else None)
            self._limpar_busca_perda()
            self.qtd_perda.delete(0, 'end')
            self.qtd_perda.insert(0, '1')

    def _adicionar_perda(self, produto, qtd=None):
        if qtd is None:
            if produto['unidade'] == 'KG':
                texto = simpledialog.askstring('Peso', 'Peso em kg (ex.: 1,325):', parent=self)
                if texto is None:
                    return
                qtd = self._para_float(texto, 0)
            else:
                qtd = 1
        if qtd <= 0:
            messagebox.showwarning('Quantidade', 'Informe uma quantidade maior que zero.')
            return
        qtd = round(float(qtd), 3)
        existente = next((i for i in self.carrinho_perda if i['produto_id'] == produto['id']), None)
        ja_no_carrinho = existente['quantidade'] if existente else 0
        disponivel = float(produto['quantidade_estoque']) - ja_no_carrinho
        if qtd > disponivel + 0.001:
            if not messagebox.askyesno('Estoque insuficiente',
                    f'Estoque atual de {produto["nome"]}: {self._formatq(produto["quantidade_estoque"], produto["unidade"])}\n'
                    f'Já no carrinho desta perda: {self._formatq(ja_no_carrinho, produto["unidade"])}\n\n'
                    f'Deseja registrar a perda mesmo assim?'):
                return
        if existente:
            existente['quantidade'] = round(existente['quantidade'] + qtd, 3)
        else:
            self.carrinho_perda.append({
                'produto_id': produto['id'], 'nome': produto['nome'],
                'preco_custo': produto['preco_custo'], 'quantidade': qtd, 'unidade': produto['unidade'],
            })
        self._render_carrinho_perda()

    def _limpar_busca_perda(self):
        self.entrada_perda.delete(0, 'end')
        self.tree_busca_perda.delete(*self.tree_busca_perda.get_children())
        self.entrada_perda.focus_set()

    def _render_carrinho_perda(self, selecionar_idx=None):
        if selecionar_idx is None:
            sel = self.tree_perda.selection()
            if sel:
                idx_sel = int(sel[0])
                if idx_sel < len(self.carrinho_perda):
                    selecionar_idx = idx_sel
        self.tree_perda.delete(*self.tree_perda.get_children())
        for i, item in enumerate(self.carrinho_perda):
            subtotal = item['quantidade'] * item['preco_custo']
            tag = 'par' if i % 2 == 0 else 'impar'
            self.tree_perda.insert('', 'end', iid=str(i), tags=(tag,),
                                      values=(item['nome'], self._formatq(item['quantidade'], item['unidade']), self._moeda(subtotal)))
        if selecionar_idx is not None and selecionar_idx < len(self.carrinho_perda):
            self.tree_perda.selection_set(str(selecionar_idx))
            self.tree_perda.focus(str(selecionar_idx))
            self.tree_perda.see(str(selecionar_idx))
        total = sum(i['quantidade'] * i['preco_custo'] for i in self.carrinho_perda)
        self.lbl_total_perda.config(text=self._moeda(total))

    def _alterar_qtd_perda(self, delta):
        sel = self.tree_perda.selection()
        if not sel:
            return
        idx = int(sel[0])
        item = self.carrinho_perda[idx]
        passo = 0.1 if item['unidade'] == 'KG' else 1
        item['quantidade'] = round(item['quantidade'] + passo * delta, 3)
        if item['quantidade'] <= 0:
            self.carrinho_perda.pop(idx)
            idx = min(idx, len(self.carrinho_perda) - 1) if self.carrinho_perda else None
        self._render_carrinho_perda(selecionar_idx=idx)

    def _remover_perda_item(self):
        sel = self.tree_perda.selection()
        if sel:
            self.carrinho_perda.pop(int(sel[0]))
            self._render_carrinho_perda()

    def _confirmar_perda(self):
        if not self.carrinho_perda:
            messagebox.showinfo('Perda', 'Adicione ao menos um item na lista usando a busca à direita.')
            return
        motivo = self.combo_motivo_perda.get().strip()
        observacao = self.entrada_obs_perda.get().strip()
        total = sum(i['quantidade'] * i['preco_custo'] for i in self.carrinho_perda)
        itens_txt = '\n'.join(f"  {item['nome']}  x{item['quantidade']:.3g}  =  {self._moeda(item['quantidade'] * item['preco_custo'])}" for item in self.carrinho_perda)
        if not messagebox.askyesno('Confirmar perda',
                f"Itens ({len(self.carrinho_perda)}):\n{itens_txt}\n\n"
                f"Total (prejuízo): {self._moeda(total)}\n"
                f"Motivo: {motivo or 'Não informado'}\n\n"
                f"Baixar do estoque e registrar como perda?"):
            return
        itens = [{'produto_id': i['produto_id'], 'quantidade': i['quantidade']} for i in self.carrinho_perda]
        try:
            r = op.registrar_perda(itens, motivo, observacao)
            self.carrinho_perda = []
            self._render_carrinho_perda()
            self.entrada_obs_perda.delete(0, 'end')
            self._carrega_resumo_perda()
            self._carrega_historico_perda()
            self._carrega_produtos()
            self._toast(f"Perda de {self._moeda(r['valor_total'])} registrada com sucesso.")
        except Exception as exc:
            messagebox.showerror('Erro', str(exc))


    def _montar_producao(self):
        p = self.tab_producao
        p.rowconfigure(2, weight=1)
        p.rowconfigure(4, weight=1)
        p.columnconfigure(0, weight=1)

        topo = tk.Frame(p, bg=COR['papel'])
        topo.grid(row=0, column=0, sticky='ew', pady=(0, 4))
        tk.Label(topo, text='Produção própria', bg=COR['papel'], fg=COR['verde2'], font=(FONTE, 20, 'bold')).pack(side='left')
        ttk.Button(topo, text='+ Nova receita', style='Secondary.TButton', command=self._modal_nova_receita).pack(side='right')
        ttk.Button(topo, text='📅 Relatório diário (fez x vendeu)', style='Secondary.TButton', command=self._abrir_relatorio_diario_producao).pack(side='right', padx=6)
        ttk.Button(topo, text='Registrar produção', style='Primary.TButton', command=self._abrir_registrar_producao).pack(side='right', padx=6)
        tk.Label(p, text='Cadastre a receita (quanto de cada insumo o produto final leva) uma vez só. Depois, '
                         'toda vez que produzir, é só dizer quantas vezes fez a receita — o sistema desconta os '
                         'insumos e dá entrada no produto final, já com o custo calculado.',
                 bg=COR['papel'], fg=COR['cinza'], font=(FONTE, 9), wraplength=1100, justify='left').grid(row=1, column=0, sticky='w', pady=(0, 10))

        tk.Label(p, text='RECEITAS CADASTRADAS', bg=COR['papel'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).grid(row=2, column=0, sticky='sw')
        bloco_receitas = tk.Frame(p, highlightbackground=COR['linha'], highlightthickness=1)
        bloco_receitas.grid(row=3, column=0, sticky='nsew', pady=(4, 12))
        bloco_receitas.rowconfigure(0, weight=1)
        bloco_receitas.columnconfigure(0, weight=1)
        self.tv_receitas = ttk.Treeview(bloco_receitas, columns=('produto', 'rendimento', 'insumos'), show='headings', height=6)
        self.tv_receitas.heading('produto', text='Produto final')
        self.tv_receitas.heading('rendimento', text='Rende')
        self.tv_receitas.heading('insumos', text='Insumos')
        self.tv_receitas.column('produto', width=220)
        self.tv_receitas.column('rendimento', width=90, anchor='center')
        self.tv_receitas.column('insumos', width=500)
        self.tv_receitas.tag_configure('par', background=COR['branco'])
        self.tv_receitas.tag_configure('impar', background=COR['zebra'])
        self.tv_receitas.grid(row=0, column=0, sticky='nsew')
        self.tv_receitas.bind('<Double-1>', lambda e: self._modal_nova_receita(self._receita_selecionada()))
        scr = ttk.Scrollbar(bloco_receitas, orient='vertical', command=self.tv_receitas.yview)
        scr.grid(row=0, column=1, sticky='ns')
        self.tv_receitas.configure(yscrollcommand=scr.set)

        tk.Label(p, text='HISTÓRICO DE PRODUÇÕES (clique duas vezes pra ver os insumos usados)', bg=COR['papel'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).grid(row=4, column=0, sticky='sw')
        bloco_hist = tk.Frame(p, highlightbackground=COR['linha'], highlightthickness=1)
        bloco_hist.grid(row=5, column=0, sticky='nsew', pady=(4, 0))
        bloco_hist.rowconfigure(0, weight=1)
        bloco_hist.columnconfigure(0, weight=1)
        self.tv_producoes = ttk.Treeview(bloco_hist, columns=('quando', 'produto', 'qtd', 'custo_total', 'custo_un', 'obs'), show='headings', height=8)
        for c, t, w in [('quando', 'Quando', 120), ('produto', 'Produto', 200), ('qtd', 'Produzido', 90),
                       ('custo_total', 'Custo total', 100), ('custo_un', 'Custo/un.', 90), ('obs', 'Observação', 200)]:
            self.tv_producoes.heading(c, text=t)
            self.tv_producoes.column(c, width=w, anchor=('center' if c == 'qtd' else ('e' if c in ('custo_total', 'custo_un') else 'w')))
        self.tv_producoes.tag_configure('par', background=COR['branco'])
        self.tv_producoes.tag_configure('impar', background=COR['zebra'])
        self.tv_producoes.bind('<Double-1>', lambda e: self._ver_detalhe_producao())
        self.tv_producoes.grid(row=0, column=0, sticky='nsew')
        sch = ttk.Scrollbar(bloco_hist, orient='vertical', command=self.tv_producoes.yview)
        sch.grid(row=0, column=1, sticky='ns')
        self.tv_producoes.configure(yscrollcommand=sch.set)

        self._carrega_producao()

    def _receita_selecionada(self):
        sel = self.tv_receitas.selection()
        if not sel:
            return None
        return self._receitas_cache.get(int(sel[0]))

    def _carrega_producao(self):
        receitas = prod.listar_receitas()
        self._receitas_cache = {r['id']: r for r in receitas}
        self.tv_receitas.delete(*self.tv_receitas.get_children())
        for i, r in enumerate(receitas):
            resumo_insumos = ', '.join(f"{self._formatq(item['quantidade'], item['unidade'])} {item['nome']}" for item in r['itens'])
            tag = 'par' if i % 2 == 0 else 'impar'
            self.tv_receitas.insert('', 'end', iid=str(r['id']), tags=(tag,), values=(
                r['nome'], self._formatq(r['rendimento'], r['unidade']), resumo_insumos))

        producoes = prod.listar_producoes(100)
        self._producoes_cache = {pr['id']: pr for pr in producoes}
        self.tv_producoes.delete(*self.tv_producoes.get_children())
        for i, pr in enumerate(producoes):
            try:
                quando = datetime.strptime(pr['data_hora'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y %H:%M')
            except ValueError:
                quando = pr['data_hora']
            tag = 'par' if i % 2 == 0 else 'impar'
            self.tv_producoes.insert('', 'end', iid=str(pr['id']), tags=(tag,), values=(
                quando, pr['produto_nome'], self._formatq(pr['quantidade_produzida'], pr['unidade']),
                self._moeda(pr['custo_total']), self._moeda(pr['custo_unitario']), pr['observacao'] or ''))

    def _ver_detalhe_producao(self):
        sel = self.tv_producoes.selection()
        if not sel:
            return
        detalhe = prod.detalhar_producao(int(sel[0]))
        if not detalhe:
            return
        linhas = '\n'.join(f"  • {self._formatq(i['quantidade'], i['unidade'])} de {i['nome']}" for i in detalhe['insumos'])
        messagebox.showinfo(
            f"Produção — {detalhe['produto_nome']}",
            f"Produziu {self._formatq(detalhe['quantidade_produzida'], detalhe['unidade'])} de {detalhe['produto_nome']}\n"
            f"Custo total: {self._moeda(detalhe['custo_total'])}  ·  Custo por unidade: {self._moeda(detalhe['custo_unitario'])}\n\n"
            f"Insumos usados nessa produção ({detalhe['multiplicador']:g}x a receita):\n{linhas}")

    def _modal_nova_receita(self, receita=None):
        dlg = tk.Toplevel(self)
        dlg.title('Editar receita' if receita else 'Nova receita')
        dlg.geometry('560x560')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Editar receita' if receita else 'Nova receita', bg=COR['branco'], fg=COR['verde2'],
                 font=(FONTE, 15, 'bold')).pack(anchor='w', padx=24, pady=(16, 12))

        tk.Label(dlg, text='PRODUTO FINAL (o que é produzido)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24)
        ent_produto = tk.Entry(dlg, font=(FONTE, 10), relief='solid', bd=1,
                                highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_produto.pack(fill='x', padx=24, ipady=5)
        _uppercase_ao_digitar(ent_produto)
        lista_sug_produto = tk.Listbox(dlg, height=4, font=(FONTE, 9))
        produto_escolhido = {'id': receita['produto_id'] if receita else None}
        if receita:
            ent_produto.insert(0, receita['nome'])
            ent_produto.config(state='disabled')

        def buscar_produto(event=None):
            termo = ent_produto.get().strip()
            lista_sug_produto.delete(0, 'end')
            if len(termo) < 2:
                lista_sug_produto.pack_forget()
                return
            achados = op.listar_produtos(termo)[:8]
            if not achados:
                lista_sug_produto.pack_forget()
                return
            for p in achados:
                lista_sug_produto.insert('end', p['nome'])
            lista_sug_produto._achados = achados
            lista_sug_produto.pack(fill='x', padx=24, pady=(2, 0))

        def escolher_produto(event=None):
            s = lista_sug_produto.curselection()
            if s:
                p = lista_sug_produto._achados[s[0]]
                ent_produto.delete(0, 'end')
                ent_produto.insert(0, p['nome'])
                produto_escolhido['id'] = p['id']
                lista_sug_produto.pack_forget()

        ent_produto.bind('<KeyRelease>', buscar_produto)
        lista_sug_produto.bind('<<ListboxSelect>>', escolher_produto)

        tk.Label(dlg, text='RENDIMENTO (quantas unidades essa receita rende)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        ent_rendimento = tk.Entry(dlg, font=('Consolas', 12), relief='solid', bd=1,
                                   highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_rendimento.pack(fill='x', padx=24, ipady=5)
        ent_rendimento.insert(0, str(receita['rendimento']) if receita else '1')

        tk.Label(dlg, text='INSUMOS (o que essa receita usa)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 4))
        frame_insumos = tk.Frame(dlg, bg=COR['branco'])
        frame_insumos.pack(fill='both', expand=True, padx=24)
        linhas_insumo = []

        def add_linha_insumo(insumo_inicial=None, quantidade_inicial=''):
            linha = tk.Frame(frame_insumos, bg=COR['branco'])
            linha.pack(fill='x', pady=2)
            ent_insumo = tk.Entry(linha, font=(FONTE, 9), relief='solid', bd=1)
            ent_insumo.pack(side='left', fill='x', expand=True, ipady=4)
            _uppercase_ao_digitar(ent_insumo)
            ent_qtd_insumo = tk.Entry(linha, font=('Consolas', 9), relief='solid', bd=1, width=10)
            ent_qtd_insumo.pack(side='left', padx=(6, 6), ipady=4)
            estado = {'id': insumo_inicial['insumo_id'] if insumo_inicial else None}
            if insumo_inicial:
                ent_insumo.insert(0, insumo_inicial['nome'])
                ent_qtd_insumo.insert(0, str(insumo_inicial['quantidade']))
            elif quantidade_inicial:
                ent_qtd_insumo.insert(0, quantidade_inicial)

            def remover():
                linha.destroy()
                linhas_insumo.remove(registro)

            ttk.Button(linha, text='✕', style='Secondary.TButton', width=3, command=remover).pack(side='left')

            def buscar_insumo(event=None):
                termo = ent_insumo.get().strip()
                if len(termo) < 2:
                    return
                achados = op.listar_produtos(termo)
                if achados:
                    estado['id'] = achados[0]['id']
                    estado['candidatos'] = achados

            ent_insumo.bind('<KeyRelease>', buscar_insumo)
            registro = {'estado': estado, 'ent_insumo': ent_insumo, 'ent_qtd': ent_qtd_insumo}
            linhas_insumo.append(registro)

        if receita:
            for item in receita['itens']:
                add_linha_insumo(item)
        else:
            add_linha_insumo()

        ttk.Button(dlg, text='+ Adicionar insumo', style='Secondary.TButton', command=lambda: add_linha_insumo()).pack(anchor='w', padx=24, pady=(6, 0))

        def salvar():
            if not produto_escolhido['id']:
                messagebox.showerror('Produto', 'Escolha o produto final na lista.', parent=dlg)
                return
            itens = []
            for reg in linhas_insumo:
                nome_digitado = reg['ent_insumo'].get().strip()
                if not nome_digitado:
                    continue
                insumo_id = reg['estado'].get('id')
                if not insumo_id:
                    messagebox.showerror('Insumo', f'Não achei o produto "{nome_digitado}" — confira o nome.', parent=dlg)
                    return
                qtd = self._para_float(reg['ent_qtd'].get(), 0)
                if qtd <= 0:
                    messagebox.showerror('Quantidade', f'Informe a quantidade de "{nome_digitado}".', parent=dlg)
                    return
                itens.append({'insumo_id': insumo_id, 'quantidade': qtd})
            if not itens:
                messagebox.showerror('Insumos', 'Adicione pelo menos um insumo.', parent=dlg)
                return
            rendimento = self._para_float(ent_rendimento.get(), 0)
            try:
                if receita:
                    prod.atualizar_receita(receita['id'], rendimento, itens)
                else:
                    prod.criar_receita(produto_escolhido['id'], rendimento, itens)
                dlg.destroy()
                self._carrega_producao()
                self._toast('Receita salva.')
            except Exception as exc:
                messagebox.showerror('Erro', str(exc), parent=dlg)

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=16, side='bottom')
        ttk.Button(botoes, text='Salvar receita', style='Primary.TButton', command=salvar).pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))

    def _abrir_registrar_producao_legado(self):
        receitas = prod.listar_receitas()
        if not receitas:
            messagebox.showinfo('Sem receitas', 'Cadastre uma receita primeiro, em "+ Nova receita".')
            return

        dlg = tk.Toplevel(self)
        dlg.title('Registrar produção')
        dlg.geometry('440x420')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.resizable(False, False)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Registrar produção', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 15, 'bold')).pack(anchor='w', padx=24, pady=(16, 12))

        tk.Label(dlg, text='RECEITA', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24)
        combo = ttk.Combobox(dlg, state='readonly', font=(FONTE, 10), values=[r['nome'] for r in receitas])
        combo.current(0)
        combo.pack(fill='x', padx=24, pady=(4, 12))

        tk.Label(dlg, text='QUANTAS VEZES FEZ A RECEITA (ex.: 1, 2, 0.5)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24)
        ent_mult = tk.Entry(dlg, font=('Consolas', 14), relief='solid', bd=1,
                             highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_mult.pack(fill='x', padx=24, pady=(4, 4), ipady=6)
        ent_mult.insert(0, '1')

        label_previa = tk.Label(dlg, text='', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9), justify='left', wraplength=380)
        label_previa.pack(anchor='w', padx=24, pady=(6, 12))

        def atualizar_previa(*_a):
            r = receitas[combo.current()]
            mult = self._para_float(ent_mult.get(), 0)
            if mult <= 0:
                label_previa.config(text='')
                return
            produzido = r['rendimento'] * mult
            custo_1x = prod.calcular_custo_receita(r['id'])
            label_previa.config(text=f"Vai produzir {self._formatq(produzido, r['unidade'])} de {r['nome']}, "
                                      f"custo total estimado {self._moeda(custo_1x * mult)} "
                                      f"({self._moeda((custo_1x * mult) / produzido if produzido else 0)}/unidade).")

        combo.bind('<<ComboboxSelected>>', atualizar_previa)
        ent_mult.bind('<KeyRelease>', atualizar_previa)
        atualizar_previa()

        tk.Label(dlg, text='OBSERVAÇÃO (OPCIONAL)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(4, 3))
        ent_obs = tk.Entry(dlg, font=(FONTE, 10), relief='solid', bd=1,
                            highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_obs.pack(fill='x', padx=24, ipady=5)
        _uppercase_ao_digitar(ent_obs)

        def confirmar():
            r = receitas[combo.current()]
            mult = self._para_float(ent_mult.get(), 0)
            if mult <= 0:
                messagebox.showerror('Quantidade', 'Informe quantas vezes a receita foi feita.', parent=dlg)
                return
            try:
                resultado = prod.registrar_producao(r['id'], mult, ent_obs.get())
                dlg.destroy()
                self._carrega_producao()
                self._carrega_produtos()
                self._toast(f"Produção registrada: {self._formatq(resultado['quantidade_produzida'], r['unidade'])} de {resultado['produto_nome']}.")
            except Exception as exc:
                messagebox.showerror('Erro', str(exc), parent=dlg)

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=22, side='bottom')
        ttk.Button(botoes, text='Confirmar produção', style='Primary.TButton', command=confirmar).pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))

    def _abrir_relatorio_diario_producao(self):
        """Dia a dia de um mês: quanto de um produto foi produzido, vendido,
        perdido e consumido internamente — feito pra dar controle do tipo
        'assamos 125 pães, vendemos 120', separado por dia (não só o total do
        mês), pra qualquer produto que a pessoa acompanhe de perto."""
        dlg = tk.Toplevel(self)
        dlg.title('Relatório diário — produzido x vendido')
        dlg.geometry('740x600')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Relatório diário — produzido x vendido', bg=COR['branco'], fg=COR['verde2'],
                 font=(FONTE, 15, 'bold')).pack(anchor='w', padx=24, pady=(16, 4))
        tk.Label(dlg, text='Pra acompanhar de perto (ex.: pão): quanto foi produzido, vendido, perdido e consumido '
                           'internamente em cada dia do mês — e o que sobrou ou faltou (saldo negativo).',
                 bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9), wraplength=680, justify='left').pack(anchor='w', padx=24, pady=(0, 10))

        linha_topo = tk.Frame(dlg, bg=COR['branco'])
        linha_topo.pack(fill='x', padx=24)
        tk.Label(linha_topo, text='PRODUTO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w')
        ent_produto = tk.Entry(linha_topo, font=(FONTE, 10), relief='solid', bd=1,
                                highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_produto.pack(fill='x', ipady=5)
        _uppercase_ao_digitar(ent_produto)
        lista_sug = tk.Listbox(dlg, height=4, font=(FONTE, 9))
        hoje = date.today()
        estado = {'produto_id': None, 'ano': hoje.year, 'mes': hoje.month}

        def buscar_produto(event=None):
            termo = ent_produto.get().strip()
            lista_sug.delete(0, 'end')
            if len(termo) < 2:
                lista_sug.pack_forget()
                return
            achados = op.listar_produtos(termo)[:8]
            if not achados:
                lista_sug.pack_forget()
                return
            for p in achados:
                lista_sug.insert('end', p['nome'])
            lista_sug._achados = achados
            lista_sug.pack(fill='x', padx=24, pady=(2, 0))

        def escolher_produto(event=None):
            s = lista_sug.curselection()
            if s:
                p = lista_sug._achados[s[0]]
                ent_produto.delete(0, 'end')
                ent_produto.insert(0, p['nome'])
                estado['produto_id'] = p['id']
                lista_sug.pack_forget()
                carregar()

        ent_produto.bind('<KeyRelease>', buscar_produto)
        lista_sug.bind('<<ListboxSelect>>', escolher_produto)

        linha_mes = tk.Frame(dlg, bg=COR['branco'])
        linha_mes.pack(fill='x', padx=24, pady=(12, 8))
        label_mes = tk.Label(linha_mes, text='', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 11, 'bold'), width=16, anchor='w')

        def mudar_mes(delta):
            m = estado['mes'] + delta
            a = estado['ano']
            if m == 0:
                m, a = 12, a - 1
            elif m == 13:
                m, a = 1, a + 1
            estado['mes'], estado['ano'] = m, a
            carregar()

        ttk.Button(linha_mes, text='◀ Mês anterior', style='Secondary.TButton', command=lambda: mudar_mes(-1)).pack(side='left')
        label_mes.pack(side='left', padx=10)
        ttk.Button(linha_mes, text='Próximo mês ▶', style='Secondary.TButton', command=lambda: mudar_mes(1)).pack(side='left')

        tabela = tk.Frame(dlg, highlightbackground=COR['linha'], highlightthickness=1)
        tabela.pack(fill='both', expand=True, padx=24)
        tabela.rowconfigure(0, weight=1)
        tabela.columnconfigure(0, weight=1)
        tv = ttk.Treeview(tabela, columns=('dia', 'produzido', 'vendido', 'perdido', 'consumido', 'saldo'), show='headings')
        for c, t, w in [('dia', 'Dia', 110), ('produzido', 'Produzido', 90), ('vendido', 'Vendido', 90),
                        ('perdido', 'Perdido', 90), ('consumido', 'Consumo int.', 100), ('saldo', 'Saldo', 90)]:
            tv.heading(c, text=t)
            tv.column(c, width=w, anchor='center' if c == 'dia' else 'e')
        tv.tag_configure('par', background=COR['branco'])
        tv.tag_configure('impar', background=COR['zebra'])
        tv.tag_configure('falta', foreground=COR['vermelho'])
        tv.grid(row=0, column=0, sticky='nsew')
        scr = ttk.Scrollbar(tabela, orient='vertical', command=tv.yview)
        scr.grid(row=0, column=1, sticky='ns')
        tv.configure(yscrollcommand=scr.set)

        label_total = tk.Label(dlg, text='', bg=COR['branco'], fg=COR['verde2'], font=('Consolas', 10, 'bold'),
                                justify='left', anchor='w', wraplength=680)
        label_total.pack(fill='x', padx=24, pady=(8, 16))

        def carregar():
            label_mes.config(text=f"{an.NOMES_MES[estado['mes']]}/{estado['ano']}")
            tv.delete(*tv.get_children())
            if not estado['produto_id']:
                label_total.config(text='Escolha um produto acima pra ver o relatório do mês.')
                return
            rel = prod.relatorio_diario_produto(estado['produto_id'], estado['ano'], estado['mes'])
            unidade = rel['unidade']
            if not rel['linhas']:
                label_total.config(text=f"Sem produção, venda, perda ou consumo de {rel['produto_nome']} em {an.NOMES_MES[estado['mes']]}/{estado['ano']}.")
                return
            for i, linha in enumerate(rel['linhas']):
                d = datetime.strptime(linha['data'], '%Y-%m-%d').date()
                texto_dia = f"{d.strftime('%d/%m')} ({an.NOMES_DIA_SEMANA_ABREV[(d.weekday() + 1) % 7]})"
                tag = 'falta' if linha['saldo'] < 0 else ('par' if i % 2 == 0 else 'impar')
                tv.insert('', 'end', tags=(tag,), values=(
                    texto_dia, self._formatq(linha['produzido'], unidade), self._formatq(linha['vendido'], unidade),
                    self._formatq(linha['perdido'], unidade), self._formatq(linha['consumido'], unidade),
                    self._formatq(linha['saldo'], unidade)))
            t = rel['totais']
            label_total.config(text=(
                f"TOTAL DE {an.NOMES_MES[estado['mes']].upper()} — {rel['produto_nome']}:  "
                f"produzido {self._formatq(t['produzido'], unidade)}  ·  vendido {self._formatq(t['vendido'], unidade)}  ·  "
                f"perdido {self._formatq(t['perdido'], unidade)}  ·  consumo interno {self._formatq(t['consumido'], unidade)}  ·  "
                f"saldo {self._formatq(t['saldo'], unidade)}"))

        # Se existir um produto com "pão" no nome, já vem pré-selecionado — é o
        # caso de uso mais comum dessa tela, mas serve pra qualquer produto.
        achados_pao = op.listar_produtos('PÃO') or op.listar_produtos('PAO')
        if achados_pao:
            ent_produto.insert(0, achados_pao[0]['nome'])
            estado['produto_id'] = achados_pao[0]['id']
        carregar()

        ttk.Button(dlg, text='Fechar', style='Secondary.TButton', command=dlg.destroy).pack(pady=(0, 18))

    def _montar_painel(self):
        p = self.tab_pain
        p.columnconfigure((0, 1, 2), weight=1)
        p.rowconfigure(2, weight=1)
        cab = tk.Frame(p, bg=COR['papel'])
        cab.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 12))
        tk.Label(cab, text='Painel', bg=COR['papel'], fg=COR['verde2'], font=(FONTE, 20, 'bold')).pack(side='left')
        ttk.Button(cab, text='Atualizar', style='Secondary.TButton', command=self._carrega_painel).pack(side='right')

        self.cards_periodo = {}
        periodos = [('dia', 'HOJE'), ('semana', 'ESTA SEMANA'), ('mes', 'ESTE MÊS')]
        for i, (chave, titulo) in enumerate(periodos):
            f = tk.Frame(p, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
            f.grid(row=1, column=i, sticky='nsew', padx=(0 if i == 0 else 6, 0), pady=(0, 14))

            tk.Label(f, text=titulo, bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 11, 'bold')).pack(anchor='w', padx=14, pady=(14, 6))

            lbl_vendido = tk.Label(f, text='R$ 0,00', bg=COR['branco'], fg=COR['verde2'], font=('Consolas', 19, 'bold'))
            lbl_vendido.pack(anchor='w', padx=14)
            tk.Label(f, text='vendido', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8)).pack(anchor='w', padx=14, pady=(0, 6))

            lbl_vendas = tk.Label(f, text='0 venda(s) · 0 item(ns)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9))
            lbl_vendas.pack(anchor='w', padx=14, pady=(0, 10))

            ttk.Separator(f).pack(fill='x', padx=14, pady=(0, 8))

            tk.Label(f, text='LUCRO ESTIMADO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=14)
            lbl_lucro_estimado = tk.Label(f, text='R$ 0,00', bg=COR['branco'], fg=COR['verde2'], font=('Consolas', 15, 'bold'))
            lbl_lucro_estimado.pack(anchor='w', padx=14)
            tk.Label(f, text='vendas menos o preço de custo, sem tirar taxas', bg=COR['branco'], fg=COR['cinza'],
                     font=(FONTE, 7), wraplength=210, justify='left').pack(anchor='w', padx=14, pady=(0, 10))

            faixa_liquido = tk.Frame(f, bg=COR['amarelo'])
            faixa_liquido.pack(fill='x', side='bottom')
            tk.Label(faixa_liquido, text='LUCRO LÍQUIDO', bg=COR['amarelo'], fg=COR['verde2'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=14, pady=(10, 0))
            lbl_lucro_liquido = tk.Label(faixa_liquido, text='R$ 0,00', bg=COR['amarelo'], fg=COR['verde2'], font=('Consolas', 15, 'bold'))
            lbl_lucro_liquido.pack(anchor='w', padx=14)
            tk.Label(faixa_liquido, text='já descontando taxas de cartão/Pix/voucher', bg=COR['amarelo'], fg=COR['verde2'],
                     font=(FONTE, 7), wraplength=210, justify='left').pack(anchor='w', padx=14, pady=(0, 10))

            self.cards_periodo[chave] = {
                'vendido': lbl_vendido, 'vendas': lbl_vendas,
                'lucro_estimado': lbl_lucro_estimado, 'lucro_liquido': lbl_lucro_liquido,
            }

        colunas = tk.Frame(p, bg=COR['papel'])
        colunas.grid(row=2, column=0, columnspan=3, sticky='nsew')
        colunas.columnconfigure((0, 1, 2), weight=1)
        colunas.rowconfigure(0, weight=1)

        bloco_mv = tk.Frame(colunas, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_mv.grid(row=0, column=0, sticky='nsew', padx=(0, 6))
        bloco_mv.rowconfigure(1, weight=1)
        bloco_mv.columnconfigure(0, weight=1)
        tk.Label(bloco_mv, text='Todos os produtos vendidos hoje (do mais ao menos vendido)', bg=COR['branco'], fg=COR['verde2'],
                 font=(FONTE, 12, 'bold'), wraplength=280, justify='left').grid(row=0, column=0, sticky='w', padx=16, pady=(16, 8))
        canvas_mv = tk.Canvas(bloco_mv, bg=COR['branco'], highlightthickness=0)
        scroll_mv = ttk.Scrollbar(bloco_mv, orient='vertical', command=canvas_mv.yview)
        canvas_mv.configure(yscrollcommand=scroll_mv.set)
        canvas_mv.grid(row=1, column=0, sticky='nsew', padx=(16, 0), pady=(0, 16))
        scroll_mv.grid(row=1, column=1, sticky='ns', pady=(0, 16))
        self.lista_mv = tk.Frame(canvas_mv, bg=COR['branco'])
        janela_mv = canvas_mv.create_window((0, 0), window=self.lista_mv, anchor='nw')
        self.lista_mv.bind('<Configure>', lambda e: canvas_mv.configure(scrollregion=canvas_mv.bbox('all')))
        canvas_mv.bind('<Configure>', lambda e: canvas_mv.itemconfig(janela_mv, width=e.width))
        canvas_mv.bind('<Enter>', lambda e: canvas_mv.bind_all('<MouseWheel>', lambda ev: canvas_mv.yview_scroll(int(-1*(ev.delta/120)), 'units')))
        canvas_mv.bind('<Leave>', lambda e: canvas_mv.unbind_all('<MouseWheel>'))

        bloco_eb = tk.Frame(colunas, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_eb.grid(row=0, column=1, sticky='nsew', padx=6)
        tk.Label(bloco_eb, text='Estoque baixo e zerado', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 12, 'bold')).pack(anchor='w', padx=16, pady=(16, 8))
        self.lista_eb = tk.Frame(bloco_eb, bg=COR['branco'])
        self.lista_eb.pack(fill='both', expand=True, padx=16, pady=(0, 16))

        bloco_val = tk.Frame(colunas, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_val.grid(row=0, column=2, sticky='nsew', padx=(6, 0))
        tk.Label(bloco_val, text='Vencendo em breve (7 dias)', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 12, 'bold')).pack(anchor='w', padx=16, pady=(16, 8))
        self.lista_val_painel = tk.Frame(bloco_val, bg=COR['branco'])
        self.lista_val_painel.pack(fill='both', expand=True, padx=16, pady=(0, 16))

        bloco_pag_painel = tk.Frame(p, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_pag_painel.grid(row=3, column=0, columnspan=3, sticky='ew', pady=(12, 0))
        tk.Label(bloco_pag_painel, text='Recebido por forma de pagamento (hoje)', bg=COR['branco'], fg=COR['verde2'],
                 font=(FONTE, 12, 'bold')).pack(anchor='w', padx=16, pady=(12, 6))
        self.lista_pag_painel = tk.Frame(bloco_pag_painel, bg=COR['branco'])
        self.lista_pag_painel.pack(fill='x', padx=16, pady=(0, 12))

        self._carrega_painel()

    def _carrega_painel(self):
        dados = op.obter_dashboard()
        for chave, cartoes in self.cards_periodo.items():
            d = dados[chave]
            cartoes['vendido'].config(text=self._moeda(d['vendido']))
            itens_txt = f"{d['produtos_vendidos']:.3f}".rstrip('0').rstrip('.') or '0'
            plural_v = '' if d['numero_vendas'] == 1 else 's'
            cartoes['vendas'].config(text=f"{d['numero_vendas']} venda{plural_v} · {itens_txt} item(ns)")
            cartoes['lucro_estimado'].config(text=self._moeda(d['lucro_estimado']))
            cartoes['lucro_liquido'].config(text=self._moeda(d['lucro_liquido']))

        for w in self.lista_mv.winfo_children():
            w.destroy()
        if dados['mais_vendidos']:
            for item in dados['mais_vendidos']:
                linha = tk.Frame(self.lista_mv, bg=COR['verdeclaro'])
                linha.pack(fill='x', pady=3)
                tk.Label(linha, text=item['nome'], bg=COR['verdeclaro'], fg=COR['verde2'], font=(FONTE, 10)).pack(side='left', padx=10, pady=7)
                tk.Label(linha, text=self._formatq(item['qtd'], item['unidade']), bg=COR['verdeclaro'], fg=COR['verde2'], font=('Consolas', 10, 'bold')).pack(side='right', padx=10)
        else:
            tk.Label(self.lista_mv, text='Nenhuma venda hoje ainda', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 10)).pack(pady=10)

        for w in self.lista_eb.winfo_children():
            w.destroy()
        zerados, baixos = dados['estoque_zerado'], dados['estoque_acabando']
        linhas = [(x, True) for x in zerados[:8]] + [(x, False) for x in baixos[:8]]
        if linhas:
            for item, zerado in linhas:
                cor_fundo = COR['vermelhoclaro'] if zerado else COR['amareloclaro']
                cor_texto = COR['vermelho'] if zerado else COR['ambar']
                linha = tk.Frame(self.lista_eb, bg=cor_fundo)
                linha.pack(fill='x', pady=3)
                tk.Label(linha, text=item['nome'], bg=cor_fundo, fg=cor_texto, font=(FONTE, 10, 'bold')).pack(side='left', padx=10, pady=7)
                tk.Label(linha, text=self._formatq(item['quantidade_estoque'], item['unidade']), bg=cor_fundo, fg=cor_texto, font=('Consolas', 10, 'bold')).pack(side='right', padx=10)
            if len(zerados) > 8:
                tk.Label(self.lista_eb, text=f'... e mais {len(zerados) - 8} produto(s) zerado(s)', bg=COR['branco'],
                         fg=COR['cinza'], font=(FONTE, 9)).pack(anchor='w', pady=(6, 0))
        else:
            tk.Label(self.lista_eb, text='Nenhum produto com estoque baixo 🎉', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 10)).pack(pady=10)

        for w in self.lista_val_painel.winfo_children():
            w.destroy()
        vencendo = val.produtos_vencendo(7)
        if vencendo:
            for item in vencendo[:10]:
                cor_fundo = COR['vermelhoclaro'] if item['vencido'] else COR['amareloclaro']
                cor_texto = COR['vermelho'] if item['vencido'] else COR['ambar']
                texto_dias = f"Vencido há {abs(item['dias_restantes'])}d" if item['vencido'] else f"{item['dias_restantes']}d restantes"
                linha = tk.Frame(self.lista_val_painel, bg=cor_fundo)
                linha.pack(fill='x', pady=3)
                tk.Label(linha, text=f"{item['nome']} ({self._formatq(item['quantidade'], item['unidade'])})",
                        bg=cor_fundo, fg=cor_texto, font=(FONTE, 9, 'bold'), wraplength=180, justify='left').pack(side='left', padx=10, pady=7)
                tk.Label(linha, text=texto_dias, bg=cor_fundo, fg=cor_texto, font=('Consolas', 8, 'bold')).pack(side='right', padx=10)
            if len(vencendo) > 10:
                tk.Label(self.lista_val_painel, text=f'... e mais {len(vencendo) - 10} lote(s)', bg=COR['branco'],
                        fg=COR['cinza'], font=(FONTE, 9)).pack(anchor='w', pady=(6, 0))
        else:
            tk.Label(self.lista_val_painel, text='Nada vencendo nos próximos 7 dias 🎉', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 10)).pack(pady=10)

        if hasattr(self, 'lista_pag_painel'):
            for w in self.lista_pag_painel.winfo_children():
                w.destroy()
            pag = op.resumo_por_forma_pagamento('hoje')
            if pag['itens']:
                for item in pag['itens']:
                    fiado = item['forma'] == 'fiado'
                    card = tk.Frame(self.lista_pag_painel, bg=COR['papel'])
                    card.pack(side='left', padx=(0, 12))
                    tk.Label(card, text=item['rotulo'], bg=COR['papel'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w')
                    tk.Label(card, text=self._moeda(item['total']), bg=COR['papel'],
                             fg=COR['ambar'] if fiado else COR['verde2'], font=('Consolas', 13, 'bold')).pack(anchor='w')
                    tk.Label(card, text=f"{item['n']} venda(s)" + (' · a receber' if fiado else ''), bg=COR['papel'],
                             fg=COR['cinza'], font=(FONTE, 8)).pack(anchor='w')
            else:
                tk.Label(self.lista_pag_painel, text='Nenhuma venda hoje ainda.', bg=COR['branco'],
                         fg=COR['cinza'], font=(FONTE, 10)).pack(anchor='w', pady=4)

    def _montar_analises(self):
        p = self.tab_analises
        p.columnconfigure(0, weight=1)
        p.rowconfigure(2, weight=1)

        cab = tk.Frame(p, bg=COR['papel'])
        cab.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        tk.Label(cab, text='Análises de vendas', bg=COR['papel'], fg=COR['verde2'], font=(FONTE, 20, 'bold')).pack(side='left')
        ttk.Button(cab, text='Atualizar', style='Secondary.TButton', command=self._carrega_analises).pack(side='right')
        self.periodo_analise = tk.StringVar(value='30dias')
        sel = tk.Frame(cab, bg=COR['papel'])
        sel.pack(side='right', padx=(0, 12))
        for texto, valor in [('Hoje', 'hoje'), ('7 dias', '7dias'), ('30 dias', '30dias'), ('Este mês', 'mes'), ('Tudo', 'tudo')]:
            ttk.Radiobutton(sel, text=texto, value=valor, variable=self.periodo_analise, command=self._carrega_analises).pack(side='left', padx=3)
        self.forma_analise = tk.StringVar(value='Todas')
        self.combo_forma_analise = ttk.Combobox(sel, textvariable=self.forma_analise, state='readonly',
                                                font=(FONTE, 9), width=11,
                                                values=['Todas'] + [r for _, r in op.FORMAS_PAGAMENTO_VENDA] + ['Cartão'])
        self.combo_forma_analise.pack(side='right', padx=(4, 0))
        self.combo_forma_analise.bind('<<ComboboxSelected>>', lambda e: self._carrega_analises())
        tk.Label(sel, text='Forma de pagamento:', bg=COR['papel'], fg=COR['cinza'],
                 font=(FONTE, 9)).pack(side='right', padx=(16, 0))

        cards_frame = tk.Frame(p, bg=COR['papel'])
        cards_frame.grid(row=1, column=0, sticky='ew', pady=(0, 12))
        cards_frame.columnconfigure((0, 1, 2, 3), weight=1)
        self.cards_an = {}
        specs = [
            ('faturamento', 'FATURAMENTO NO PERÍODO', COR['verde2'], 'white'),
            ('numero_vendas', 'VENDAS', COR['branco'], COR['verde2']),
            ('ticket_medio', 'TICKET MÉDIO', COR['branco'], COR['verde2']),
            ('lucro_estimado', 'LUCRO ESTIMADO', COR['amarelo'], COR['verde2']),
        ]
        for i, (chave, titulo, bg, fg) in enumerate(specs):
            f = tk.Frame(cards_frame, bg=bg, highlightbackground=COR['linha'], highlightthickness=(1 if bg == COR['branco'] else 0))
            f.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else 6, 0))
            tk.Label(f, text=titulo, bg=bg, fg=(fg if bg != COR['branco'] else COR['cinza']), font=(FONTE, 9, 'bold')).pack(anchor='w', padx=14, pady=(14, 4))
            label = tk.Label(f, text='—', bg=bg, fg=fg, font=('Consolas', 18, 'bold'))
            label.pack(anchor='w', padx=14, pady=(0, 14))
            self.cards_an[chave] = label

        corpo_wrap = tk.Frame(p, bg=COR['papel'])
        corpo_wrap.grid(row=2, column=0, sticky='nsew')
        corpo_wrap.rowconfigure(0, weight=1)
        corpo_wrap.columnconfigure(0, weight=1)
        canvas_corpo = tk.Canvas(corpo_wrap, bg=COR['papel'], highlightthickness=0)
        scroll_corpo = ttk.Scrollbar(corpo_wrap, orient='vertical', command=canvas_corpo.yview)
        canvas_corpo.configure(yscrollcommand=scroll_corpo.set)
        canvas_corpo.grid(row=0, column=0, sticky='nsew')
        scroll_corpo.grid(row=0, column=1, sticky='ns')
        corpo = tk.Frame(canvas_corpo, bg=COR['papel'])
        janela_corpo = canvas_corpo.create_window((0, 0), window=corpo, anchor='nw')
        corpo.bind('<Configure>', lambda e: canvas_corpo.configure(scrollregion=canvas_corpo.bbox('all')))
        canvas_corpo.bind('<Configure>', lambda e: canvas_corpo.itemconfig(janela_corpo, width=e.width))
        canvas_corpo.bind('<Enter>', lambda e: canvas_corpo.bind_all('<MouseWheel>', lambda ev: canvas_corpo.yview_scroll(int(-1 * (ev.delta / 120)), 'units')))
        canvas_corpo.bind('<Leave>', lambda e: canvas_corpo.unbind_all('<MouseWheel>'))

        bloco_pag = tk.Frame(corpo, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_pag.pack(fill='x', pady=(0, 12))
        cab_pag = tk.Frame(bloco_pag, bg=COR['branco'])
        cab_pag.pack(fill='x', padx=16, pady=(16, 2))
        tk.Label(cab_pag, text='Recebido por forma de pagamento', bg=COR['branco'], fg=COR['verde2'],
                 font=(FONTE, 12, 'bold')).pack(side='left')
        self.label_forma_analise = tk.Label(cab_pag, text='', bg=COR['branco'], fg=COR['ambar'], font=(FONTE, 9, 'bold'))
        self.label_forma_analise.pack(side='right')
        tk.Label(bloco_pag, text='Separa dinheiro, pix, débito, crédito, voucher e fiado. Escolha uma forma no topo pra filtrar TODAS as análises por esse meio de pagamento.',
                 bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8)).pack(anchor='w', padx=16, pady=(0, 8))
        self.lista_pag_analise = tk.Frame(bloco_pag, bg=COR['branco'])
        self.lista_pag_analise.pack(fill='x', padx=16, pady=(0, 4))
        self.canvas_pag = tk.Canvas(bloco_pag, bg=COR['branco'], height=170, highlightthickness=0)
        self.canvas_pag.pack(fill='x', padx=16, pady=(4, 16))
        self.canvas_pag.bind('<Configure>', lambda e: self._redesenhar_grafico_pag())

        bloco_tendencia = tk.Frame(corpo, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_tendencia.pack(fill='x', pady=(0, 12))
        cab_tend = tk.Frame(bloco_tendencia, bg=COR['branco'])
        cab_tend.pack(fill='x', padx=16, pady=(16, 4))
        tk.Label(cab_tend, text='Tendência de vendas', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 12, 'bold')).pack(side='left')
        self.granularidade_tendencia = tk.StringVar(value='dia')
        sel_gran = tk.Frame(cab_tend, bg=COR['branco'])
        sel_gran.pack(side='right')
        for texto, valor in [('Diário', 'dia'), ('Semanal', 'semana'), ('Mensal', 'mes')]:
            ttk.Radiobutton(sel_gran, text=texto, value=valor, variable=self.granularidade_tendencia,
                           command=self._atualiza_tendencia).pack(side='left', padx=3)
        self.canvas_tendencia = tk.Canvas(bloco_tendencia, bg=COR['branco'], height=190, highlightthickness=0)
        self.canvas_tendencia.pack(fill='x', padx=16, pady=(4, 16))
        self.canvas_tendencia.bind('<Configure>', lambda e: self._redesenhar_grafico_tendencia())

        bloco_tipodia = tk.Frame(corpo, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_tipodia.pack(fill='x', pady=(0, 12))
        tk.Label(bloco_tipodia, text='Feriado, véspera, dia de pagamento ou dia normal?', bg=COR['branco'], fg=COR['verde2'],
                 font=(FONTE, 12, 'bold')).pack(anchor='w', padx=16, pady=(16, 2))
        tk.Label(bloco_tipodia, text='O que de fato muda o movimento do mercadinho — não a data comemorativa em si.',
                 bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8)).pack(anchor='w', padx=16, pady=(0, 8))
        duas_col_tipodia = tk.Frame(bloco_tipodia, bg=COR['branco'])
        duas_col_tipodia.pack(fill='x', padx=16, pady=(0, 16))
        duas_col_tipodia.columnconfigure((0, 1), weight=1)
        self.lista_tipo_dia = tk.Frame(duas_col_tipodia, bg=COR['branco'])
        self.lista_tipo_dia.grid(row=0, column=0, sticky='new', padx=(0, 10))
        bloco_eventos = tk.Frame(duas_col_tipodia, bg=COR['branco'])
        bloco_eventos.grid(row=0, column=1, sticky='new', padx=(10, 0))
        tk.Label(bloco_eventos, text='PRÓXIMOS FERIADOS E DIAS DE PAGAMENTO', bg=COR['branco'], fg=COR['cinza'],
                 font=(FONTE, 8, 'bold')).pack(anchor='w', pady=(0, 6))
        self.lista_eventos = tk.Frame(bloco_eventos, bg=COR['branco'])
        self.lista_eventos.pack(fill='x')

        bloco_semana = tk.Frame(corpo, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_semana.pack(fill='x', pady=(0, 12))
        tk.Label(bloco_semana, text='Faturamento por dia da semana', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 12, 'bold')).pack(anchor='w', padx=16, pady=(16, 4))
        self.label_melhor_dia = tk.Label(bloco_semana, text='', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9))
        self.label_melhor_dia.pack(anchor='w', padx=16, pady=(0, 8))
        self.canvas_semana = tk.Canvas(bloco_semana, bg=COR['branco'], height=190, highlightthickness=0)
        self.canvas_semana.pack(fill='x', padx=16, pady=(0, 16))
        self.canvas_semana.bind('<Configure>', lambda e: self._redesenhar_grafico_semana())

        bloco_dia = tk.Frame(corpo, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_dia.pack(fill='x', pady=(0, 12))
        cab_dia = tk.Frame(bloco_dia, bg=COR['branco'])
        cab_dia.pack(fill='x', padx=16, pady=(16, 4))
        tk.Label(cab_dia, text='O que mais vende em cada dia da semana', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 12, 'bold')).pack(side='left')
        self.combo_dia_semana = ttk.Combobox(cab_dia, state='readonly', font=(FONTE, 10), width=14, values=an.NOMES_DIA_SEMANA)
        self.combo_dia_semana.current(an.dia_semana_hoje())
        self.combo_dia_semana.pack(side='right')
        self.combo_dia_semana.bind('<<ComboboxSelected>>', lambda e: self._carrega_produtos_do_dia())
        self.lista_produtos_dia = tk.Frame(bloco_dia, bg=COR['branco'])
        self.lista_produtos_dia.pack(fill='x', padx=16, pady=(4, 16))

        duas_col = tk.Frame(corpo, bg=COR['papel'])
        duas_col.pack(fill='x', pady=(0, 12))
        duas_col.columnconfigure((0, 1), weight=1)

        bloco_top = tk.Frame(duas_col, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_top.grid(row=0, column=0, sticky='nsew', padx=(0, 6))
        tk.Label(bloco_top, text='Top 15 produtos do período', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 12, 'bold')).pack(anchor='w', padx=16, pady=(16, 8))
        self.lista_top_produtos = tk.Frame(bloco_top, bg=COR['branco'])
        self.lista_top_produtos.pack(fill='x', padx=16, pady=(0, 16))

        bloco_hora = tk.Frame(duas_col, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_hora.grid(row=0, column=1, sticky='nsew', padx=(6, 0))
        tk.Label(bloco_hora, text='Movimento por horário', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 12, 'bold')).pack(anchor='w', padx=16, pady=(16, 4))
        self.label_pico = tk.Label(bloco_hora, text='', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9))
        self.label_pico.pack(anchor='w', padx=16, pady=(0, 8))
        self.canvas_hora = tk.Canvas(bloco_hora, bg=COR['branco'], height=190, highlightthickness=0)
        self.canvas_hora.pack(fill='both', expand=True, padx=16, pady=(0, 16))
        self.canvas_hora.bind('<Configure>', lambda e: self._redesenhar_grafico_hora())

        bloco_custos = tk.Frame(corpo, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_custos.pack(fill='x', pady=(0, 12))
        tk.Label(bloco_custos, text='Custos que não aparecem na venda (pesam no lucro real)', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 12, 'bold')).pack(anchor='w', padx=16, pady=(16, 4))
        self.label_custos_ocultos = tk.Label(bloco_custos, text='', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9), justify='left', wraplength=1100)
        self.label_custos_ocultos.pack(anchor='w', padx=16, pady=(0, 16))

        bloco_qualidade = tk.Frame(corpo, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        bloco_qualidade.pack(fill='x', pady=(0, 12))
        tk.Label(bloco_qualidade, text='Qualidade do cadastro de produtos', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 12, 'bold')).pack(anchor='w', padx=16, pady=(16, 4))
        self.label_qualidade = tk.Label(bloco_qualidade, text='', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9), justify='left', wraplength=1100)
        self.label_qualidade.pack(anchor='w', padx=16, pady=(0, 16))

        self._carrega_analises()

    def _desenhar_barras(self, canvas, dados, cor_barra, formatar=None):
        """Gráfico de barras verticais bem simples, desenhado direto no Canvas
        (sem depender de nenhuma biblioteca externa de gráficos)."""
        canvas.delete('all')
        largura = canvas.winfo_width()
        altura = canvas.winfo_height()
        if largura < 10 or altura < 10:
            return
        if not dados or not any(v for _, v in dados):
            canvas.create_text(largura / 2, altura / 2, text='Sem dados suficientes nesse período', fill=COR['cinza'], font=(FONTE, 9))
            return
        maximo = max(v for _, v in dados) or 1
        n = len(dados)
        margem_inf, margem_sup = 28, 16
        espaco = largura / n
        largura_barra = max(6, espaco * 0.55)
        altura_util = altura - margem_inf - margem_sup
        for i, (rotulo, valor) in enumerate(dados):
            x0 = i * espaco + (espaco - largura_barra) / 2
            x1 = x0 + largura_barra
            h = (valor / maximo) * altura_util if maximo else 0
            y1 = altura - margem_inf
            y0 = y1 - h
            canvas.create_rectangle(x0, y0, x1, y1, fill=cor_barra, outline='')
            texto_valor = formatar(valor) if formatar else str(valor)
            if texto_valor:
                canvas.create_text((x0 + x1) / 2, max(y0 - 9, 9), text=texto_valor, fill=COR['verde2'], font=(FONTE, 7, 'bold'))
            canvas.create_text((x0 + x1) / 2, altura - margem_inf + 13, text=str(rotulo), fill=COR['cinza'], font=(FONTE, 8))

    def _redesenhar_grafico_semana(self):
        dados = getattr(self, '_dados_grafico_semana', [])
        self._desenhar_barras(self.canvas_semana, dados, COR['verde'], formatar=lambda v: self._moeda(v) if v else '')

    def _redesenhar_grafico_tendencia(self):
        dados = getattr(self, '_dados_grafico_tendencia', [])
        self._desenhar_barras(self.canvas_tendencia, dados, COR['verde2'], formatar=lambda v: self._moeda(v) if v else '')

    def _atualiza_tendencia(self):
        inicio, fim = getattr(self, '_periodo_atual', (None, None))
        granularidade = self.granularidade_tendencia.get()
        limite = {'dia': 14, 'semana': 10, 'mes': 12}.get(granularidade, 14)
        serie = an.serie_temporal(granularidade, inicio, fim, limite=limite)
        self._dados_grafico_tendencia = [(item['rotulo'], item['faturamento']) for item in serie]
        self._redesenhar_grafico_tendencia()

    def _redesenhar_grafico_hora(self):
        dados = getattr(self, '_dados_grafico_hora', [])
        self._desenhar_barras(self.canvas_hora, dados, COR['amarelo'], formatar=lambda v: (str(int(v)) if v else ''))

    def _redesenhar_grafico_pag(self):
        dados = getattr(self, '_dados_grafico_pag', [])
        self._desenhar_barras(self.canvas_pag, dados, COR['verde'], formatar=lambda v: self._moeda(v) if v else '')

    def _carrega_analises(self):
        if not hasattr(self, 'cards_an'):
            return
        chave = self.periodo_analise.get()
        inicio, fim = an.periodo_preset(chave)
        self._periodo_atual = (inicio, fim)

        filtro_forma = getattr(self, 'forma_analise', None)
        filtro_forma = filtro_forma.get() if filtro_forma else 'Todas'
        forma = next((k for k, r in op.FORMAS_PAGAMENTO_VENDA if r == filtro_forma), None)
        if forma is None and filtro_forma == 'Cartão':
            forma = 'cartao'
        if hasattr(self, 'label_forma_analise'):
            self.label_forma_analise.config(
                text=f'Filtrando por: {filtro_forma}' if forma else '')

        resumo = an.resumo_periodo(inicio, fim, forma=forma)
        self.cards_an['faturamento'].config(text=self._moeda(resumo['faturamento']))
        self.cards_an['numero_vendas'].config(text=str(resumo['numero_vendas']))
        self.cards_an['ticket_medio'].config(text=self._moeda(resumo['ticket_medio']))
        self.cards_an['lucro_estimado'].config(text=self._moeda(resumo['lucro_estimado']))

        self._carrega_formas_analise(inicio, fim)

        dias = an.vendas_por_dia_semana(inicio, fim, forma=forma)
        self._dados_grafico_semana = [(d['abrev'], d['faturamento']) for d in dias]
        melhor, pior = an.melhor_pior_dia(inicio, fim, forma=forma)
        if melhor:
            self.label_melhor_dia.config(
                text=f"Melhor dia: {melhor['nome']} ({self._moeda(melhor['faturamento'])} em {melhor['numero_vendas']} venda(s))"
                     f"   ·   Mais fraco: {pior['nome']} ({self._moeda(pior['faturamento'])})")
        else:
            self.label_melhor_dia.config(text='Sem vendas suficientes no período para comparar os dias.')
        self._redesenhar_grafico_semana()

        self._atualiza_tendencia()

        for w in self.lista_tipo_dia.winfo_children():
            w.destroy()
        cores_classe = {
            'Feriado': (COR['vermelhoclaro'], COR['vermelho']),
            'Véspera de feriado': (COR['amareloclaro'], COR['ambar']),
            'Dia de pagamento': (COR['verdeclaro'], COR['verde2']),
            'Fim de semana': (COR['zebra'], COR['cinza']),
            'Dia normal': (COR['branco'], COR['cinza']),
        }
        for c in an.vendas_por_classe_dia(inicio, fim, forma=forma):
            bg, fg = cores_classe.get(c['classe'], (COR['branco'], COR['cinza']))
            linha_c = tk.Frame(self.lista_tipo_dia, bg=bg, highlightbackground=COR['linha'], highlightthickness=1)
            linha_c.pack(fill='x', pady=2)
            tk.Label(linha_c, text=c['classe'], bg=bg, fg=fg, font=(FONTE, 10, 'bold')).pack(side='left', padx=10, pady=6)
            texto_dir = f"{self._moeda(c['media_por_dia'])}/dia" if c['dias'] else 'sem dados no período'
            tk.Label(linha_c, text=texto_dir, bg=bg, fg=fg, font=('Consolas', 9)).pack(side='right', padx=10)

        for w in self.lista_eventos.winfo_children():
            w.destroy()
        eventos = an.proximos_eventos(45)
        if eventos:
            for e in eventos[:6]:
                bg = COR['vermelhoclaro'] if e['tipo'] == 'Feriado' else COR['verdeclaro']
                fg = COR['vermelho'] if e['tipo'] == 'Feriado' else COR['verde2']
                linha_e = tk.Frame(self.lista_eventos, bg=bg)
                linha_e.pack(fill='x', pady=2)
                tk.Label(linha_e, text=f"{e['data_br']} ({e['dia_semana']}) — {e['nome']}", bg=bg, fg=fg,
                        font=(FONTE, 9)).pack(side='left', padx=8, pady=5)
                tk.Label(linha_e, text=f"em {e['dias_restantes']}d", bg=bg, fg=fg, font=('Consolas', 9, 'bold')).pack(side='right', padx=8)
        else:
            tk.Label(self.lista_eventos, text='Nada nos próximos 45 dias', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9)).pack(anchor='w', pady=4)

        horas = an.vendas_por_hora(inicio, fim, forma=forma)
        self._dados_grafico_hora = [(f"{h['hora']:02d}h", h['numero_vendas']) for h in horas]
        horas_com_venda = [h for h in horas if h['numero_vendas']]
        if horas_com_venda:
            pico = max(horas_com_venda, key=lambda h: h['numero_vendas'])
            self.label_pico.config(text=f"Horário mais movimentado: {pico['hora']:02d}h ({pico['numero_vendas']} venda(s))")
        else:
            self.label_pico.config(text='Sem vendas suficientes no período.')
        self._redesenhar_grafico_hora()

        self._carrega_produtos_do_dia()

        for w in self.lista_top_produtos.winfo_children():
            w.destroy()
        top = an.produtos_mais_vendidos(inicio, fim, limite=15, forma=forma)
        if top:
            for item in top:
                linha = tk.Frame(self.lista_top_produtos, bg=COR['verdeclaro'])
                linha.pack(fill='x', pady=3)
                tk.Label(linha, text=item['nome'], bg=COR['verdeclaro'], fg=COR['verde2'], font=(FONTE, 10)).pack(side='left', padx=10, pady=7)
                tk.Label(linha, text=self._formatq(item['qtd'], item['unidade']), bg=COR['verdeclaro'], fg=COR['verde2'], font=('Consolas', 10, 'bold')).pack(side='right', padx=10)
        else:
            tk.Label(self.lista_top_produtos, text='Nenhuma venda no período', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 10)).pack(pady=10)

        q = an.qualidade_dados()
        partes = []
        if q['sem_categoria']:
            partes.append(f"{q['sem_categoria']} produto(s) sem categoria definida")
        if q['categorias_fora_padrao']:
            extras = ', '.join(f"{c['categoria']} ({c['n']})" for c in q['categorias_fora_padrao'])
            partes.append(f"categorias fora do padrão: {extras}")
        if q['sem_codigo_balanca']:
            partes.append(f"{q['sem_codigo_balanca']} produto(s) de balança sem código pra bipar")
        if q['sem_codigo_un']:
            partes.append(f"{q['sem_codigo_un']} produto(s) por unidade sem código de barras")
        self.label_qualidade.config(text='Tudo certo por aqui! 🎉' if not partes else '⚠ ' + '   ·   '.join(partes))

        perdas_periodo = op.total_perdas_periodo(inicio, fim)
        consumo_periodo = sum(d['total'] for d in op.resumo_consumo_por_motivo(inicio, fim))
        partes_custos = []
        if perdas_periodo['numero']:
            partes_custos.append(f"{self._moeda(perdas_periodo['valor_total'])} em perdas ({perdas_periodo['numero']} registro(s))")
        if consumo_periodo:
            partes_custos.append(f"{self._moeda(consumo_periodo)} em consumo interno/embalagens")
        if partes_custos:
            self.label_custos_ocultos.config(text='   ·   '.join(partes_custos) + ' — some do estoque a preço de custo, mas não é venda perdida no sistema automaticamente.')
        else:
            self.label_custos_ocultos.config(text='Nenhuma perda ou consumo interno registrado nesse período.')

    def _carrega_formas_analise(self, inicio, fim):
        if not hasattr(self, 'lista_pag_analise'):
            return
        for w in self.lista_pag_analise.winfo_children():
            w.destroy()
        formas = an.vendas_por_forma_pagamento(inicio, fim)
        self._dados_grafico_pag = [(f['rotulo'], f['total']) for f in formas]
        self._redesenhar_grafico_pag()
        if not formas:
            tk.Label(self.lista_pag_analise, text='Nenhuma venda no período.', bg=COR['branco'],
                     fg=COR['cinza'], font=(FONTE, 10)).pack(anchor='w', pady=6)
            return
        for i, f in enumerate(formas):
            fiado = f['forma'] == 'fiado'
            bg = COR['branco'] if i % 2 == 0 else COR['zebra']
            fg = COR['ambar'] if fiado else COR['verde2']
            linha = tk.Frame(self.lista_pag_analise, bg=bg)
            linha.pack(fill='x', pady=1)
            tk.Label(linha, text=f['rotulo'], bg=bg, fg=fg, font=(FONTE, 10, 'bold')).pack(side='left', padx=10, pady=6)
            tk.Label(linha, text=f"{f['n']} venda(s)", bg=bg, fg=COR['cinza'], font=(FONTE, 9)).pack(side='left', padx=(0, 10))
            if fiado:
                tk.Label(linha, text='a receber', bg=bg, fg=COR['ambar'], font=(FONTE, 8, 'bold')).pack(side='left')
            elif f['taxas']:
                tk.Label(linha, text=f"líquido {self._moeda(f['liquido'])}", bg=bg, fg=COR['cinza'], font=(FONTE, 8)).pack(side='left')
            tk.Label(linha, text=f"{self._moeda(f['total'])}  ({f['pct']:.1f}%)", bg=bg, fg=fg,
                     font=('Consolas', 10, 'bold')).pack(side='right', padx=10)

    def _carrega_produtos_do_dia(self):
        if not hasattr(self, 'lista_produtos_dia'):
            return
        for w in self.lista_produtos_dia.winfo_children():
            w.destroy()
        dia_idx = self.combo_dia_semana.current()
        inicio, fim = getattr(self, '_periodo_atual', (None, None))
        filtro_forma = getattr(self, 'forma_analise', None)
        filtro_forma = filtro_forma.get() if filtro_forma else 'Todas'
        forma = next((k for k, r in op.FORMAS_PAGAMENTO_VENDA if r == filtro_forma), None)
        if forma is None and filtro_forma == 'Cartão':
            forma = 'cartao'
        produtos = an.produtos_por_dia_semana(dia_idx, inicio, fim, limite=8, forma=forma)
        if produtos:
            for item in produtos:
                linha = tk.Frame(self.lista_produtos_dia, bg=COR['amareloclaro'])
                linha.pack(fill='x', pady=3)
                tk.Label(linha, text=item['nome'], bg=COR['amareloclaro'], fg=COR['verde2'], font=(FONTE, 10)).pack(side='left', padx=10, pady=7)
                tk.Label(linha, text=self._formatq(item['qtd'], item['unidade']), bg=COR['amareloclaro'], fg=COR['verde2'], font=('Consolas', 10, 'bold')).pack(side='right', padx=10)
        else:
            tk.Label(self.lista_produtos_dia, text=f"Sem vendas em {an.NOMES_DIA_SEMANA[dia_idx]}s nesse período", bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 10)).pack(pady=10)

    def _gerar_catalogo(self):
        preencher = messagebox.askyesno(
            'Gerar catálogo',
            'Deseja preencher automaticamente um código pra bipar nos itens de '
            'balança que ainda não têm nenhum? (não mexe nos que já têm código)')
        caminho = filedialog.asksaveasfilename(
            title='Salvar catálogo atualizado',
            defaultextension='.xlsx',
            filetypes=[('Planilha Excel', '*.xlsx')],
            initialfile=f'Catalogo_Mercadinho_{datetime.now().strftime("%Y-%m-%d")}.xlsx')
        if not caminho:
            return
        try:
            resultado = gerar_catalogo_xlsx(caminho, preencher_codigos_faltantes=preencher)
        except Exception as exc:
            messagebox.showerror('Erro ao gerar catálogo', str(exc))
            return
        msg = f"Catálogo salvo com {resultado['total_produtos']} produtos."
        if resultado['codigos_preenchidos']:
            msg += f"\n{len(resultado['codigos_preenchidos'])} item(ns) de balança ganharam um código novo (agora dá pra bipar direto da tela)."
        if resultado['sem_categoria']:
            msg += f"\n⚠ {resultado['sem_categoria']} produto(s) ainda sem categoria — vale revisar na aba Produtos."
        messagebox.showinfo('Catálogo gerado', msg)
        if resultado['codigos_preenchidos']:
            self._aba_atualizada()

    def _gerar_entrada_mercadoria(self):
        caminho = filedialog.asksaveasfilename(
            title='Salvar planilha de entrada de mercadoria',
            defaultextension='.xlsx',
            filetypes=[('Planilha Excel', '*.xlsx')],
            initialfile=f'Entrada_Mercadoria_{datetime.now().strftime("%Y-%m-%d")}.xlsx')
        if not caminho:
            return
        try:
            resultado = gerar_planilha_entrada(caminho)
        except Exception as exc:
            messagebox.showerror('Erro ao gerar planilha', str(exc))
            return
        messagebox.showinfo(
            'Planilha gerada',
            f"Planilha de entrada de mercadoria salva.\n\n"
            f"Preencha as colunas amarelas da aba \"Entrada\" com o que chegou — código, produto, "
            f"categoria, quantidade e o custo pago. O preço de venda já sai calculado pela margem "
            f"da categoria (ajustável na aba \"Margens\").\n\n"
            f"Depois é só Arquivo → Importar entrada de mercadoria.")

    def _importar_entrada_mercadoria(self):
        caminho = filedialog.askopenfilename(
            title='Abrir planilha de entrada preenchida',
            filetypes=[('Planilha Excel', '*.xlsx')])
        if not caminho:
            return
        try:
            plano = ientrada.pre_visualizar(caminho)
        except Exception as exc:
            messagebox.showerror('Erro ao ler planilha', str(exc))
            return
        if not plano['itens']:
            messagebox.showinfo('Nada pra importar', 'Não encontrei nenhuma linha preenchida na aba "Entrada".')
            return
        self._modal_previsao_entrada(caminho, plano)

    def _modal_previsao_entrada(self, caminho, plano):
        dlg = tk.Toplevel(self)
        dlg.title('Conferir antes de importar')
        dlg.geometry('820x560')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Conferir a entrada de mercadoria', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 15, 'bold')).pack(anchor='w', padx=24, pady=(16, 4))
        tk.Label(dlg, text=f"{plano['total_itens']} produto(s) · custo total R$ {plano['total_custo']:.2f} — nada foi gravado ainda",
                bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9)).pack(anchor='w', padx=24, pady=(0, 10))

        tv = ttk.Treeview(dlg, columns=('acao', 'nome', 'custo', 'venda', 'avisos'), show='headings', height=16)
        for c, t, w in [('acao', 'Ação', 90), ('nome', 'Produto', 260), ('custo', 'Custo unit.', 90),
                       ('venda', 'Preço final', 90), ('avisos', 'Avisos', 220)]:
            tv.heading(c, text=t)
            tv.column(c, width=w, anchor='w' if c in ('nome', 'avisos') else 'e')
        tv.tag_configure('par', background=COR['branco'])
        tv.tag_configure('impar', background=COR['zebra'])
        tv.tag_configure('alerta', background=COR['vermelhoclaro'], foreground=COR['vermelho'])
        tv.pack(fill='both', expand=True, padx=24, pady=(0, 10))
        sc = ttk.Scrollbar(dlg, orient='vertical', command=tv.yview)
        tv.configure(yscrollcommand=sc.set)

        for i, item in enumerate(plano['itens']):
            tag = 'alerta' if item['avisos'] else ('par' if i % 2 == 0 else 'impar')
            venda = self._moeda(item['preco_venda_novo']) if item['preco_venda_novo'] else '—'
            tv.insert('', 'end', tags=(tag,), values=(
                'Cadastrar' if item['acao'] == 'cadastrar' else 'Atualizar', item['nome'],
                self._moeda(item['custo_unitario']), venda, '; '.join(item['avisos']) or '—'))

        if plano['margens_novas']:
            tk.Label(dlg, text=f"A aba \"Margens\" também será sincronizada ({len(plano['margens_novas'])} categoria(s)).",
                    bg=COR['branco'], fg=COR['ambar'], font=(FONTE, 9, 'bold')).pack(anchor='w', padx=24, pady=(0, 6))

        def confirmar():
            try:
                resultado = ientrada.aplicar(caminho, plano)
            except Exception as exc:
                messagebox.showerror('Erro ao importar', str(exc), parent=dlg)
                return
            dlg.destroy()
            msg = (f"{len(resultado['atualizados'])} produto(s) atualizado(s), "
                   f"{len(resultado['cadastrados'])} cadastrado(s) novo(s).")
            if resultado['ignorados']:
                msg += f"\n⚠ {len(resultado['ignorados'])} linha(s) ignorada(s): {', '.join(resultado['ignorados'][:5])}"
            if resultado['margens_sincronizadas']:
                msg += "\nMargens por categoria atualizadas."
            msg += f"\n\nBackup do banco salvo antes de gravar em:\n{resultado['backup']}"
            messagebox.showinfo('Entrada importada', msg)
            self._aba_atualizada()

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=(6, 20), side='bottom')
        ttk.Button(botoes, text='CONFIRMAR E GRAVAR', style='Primary.TButton', command=confirmar).pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))

    def _importar_nfe(self):
        caminhos = filedialog.askopenfilenames(
            title='Selecione a(s) nota(s) fiscal(is) — XML, ZIP ou PDF/DANFE',
            filetypes=[('Notas fiscais', '*.xml *.zip *.pdf'),
                       ('XML da NF-e', '*.xml'), ('DANFE (PDF)', '*.pdf'),
                       ('Arquivo ZIP', '*.zip'), ('Todos os arquivos', '*.*')])
        if not caminhos:
            return
        try:
            plano = nfe.pre_visualizar(list(caminhos))
        except Exception as exc:
            messagebox.showerror('Erro ao ler a nota', str(exc))
            return
        if not plano['itens']:
            messagebox.showinfo('Nada para importar', 'Não encontrei produtos nas notas selecionadas.')
            return
        self._modal_previsao_nfe(caminhos, plano)

    def _modal_previsao_nfe(self, caminhos, plano):
        dlg = tk.Toplevel(self)
        dlg.title('Conferir nota fiscal (NF-e)')
        dlg.geometry('960x620')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Conferir a entrada pela nota fiscal', bg=COR['branco'], fg=COR['verde2'],
                 font=(FONTE, 15, 'bold')).pack(anchor='w', padx=24, pady=(16, 4))
        forn = ', '.join(plano['fornecedores'][:3]) + ('...' if len(plano['fornecedores']) > 3 else '')
        dup = plano['total_notas'] - plano.get('notas_novas', plano['total_notas'])
        tk.Label(dlg, text=f"{plano.get('notas_novas', plano['total_notas'])} nota(s) nova(s) · "
                           f"{plano.get('itens_novos', plano['total_itens'])} item(ns) · "
                           f"custo total {self._moeda(plano['total_custo'])} — nada foi gravado ainda"
                           + (f"  ·  {dup} nota(s) já importada(s) serão ignoradas" if dup else ''),
                 bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9)).pack(anchor='w', padx=24)
        tk.Label(dlg, text=f"Fornecedor(es): {forn}", bg=COR['branco'], fg=COR['cinza'],
                 font=(FONTE, 9)).pack(anchor='w', padx=24, pady=(0, 6))

        # Dados que a nota não traz precisam ser confirmados aqui (nunca inventados).
        ent_venc = ent_validade = None
        var_forma = tk.StringVar(value='A prazo')
        if plano.get('precisa_vencimento') or plano.get('precisa_forma') or plano.get('tem_perecivel'):
            confirmar_dados = tk.Frame(dlg, bg=COR['amareloclaro'])
            confirmar_dados.pack(fill='x', padx=24, pady=(0, 8))
            tk.Label(confirmar_dados, text='⚠ Confirme os dados que a nota não informa (obrigatório):',
                     bg=COR['amareloclaro'], fg=COR['ambar'], font=(FONTE, 9, 'bold')).pack(anchor='w', padx=12, pady=(8, 2))
            linha_dados = tk.Frame(confirmar_dados, bg=COR['amareloclaro'])
            linha_dados.pack(fill='x', padx=12, pady=(0, 8))
            if plano.get('precisa_vencimento'):
                tk.Label(linha_dados, text='Vencimento (AAAA-MM-DD):', bg=COR['amareloclaro'],
                         fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(side='left')
                ent_venc = tk.Entry(linha_dados, width=12, font=(FONTE, 10))
                ent_venc.pack(side='left', padx=(4, 16))
            if plano.get('precisa_forma'):
                tk.Label(linha_dados, text='Condição:', bg=COR['amareloclaro'],
                         fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(side='left')
                ttk.Combobox(linha_dados, textvariable=var_forma, state='readonly', width=10,
                             values=['A prazo', 'À vista']).pack(side='left', padx=(4, 16))
            if plano.get('tem_perecivel'):
                tk.Label(linha_dados, text='Validade dos perecíveis (AAAA-MM-DD):', bg=COR['amareloclaro'],
                         fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(side='left')
                ent_validade = tk.Entry(linha_dados, width=12, font=(FONTE, 10))
                ent_validade.pack(side='left', padx=(4, 16))

        tv = ttk.Treeview(dlg, columns=('nota', 'produto', 'qtd', 'un', 'custo', 'venda', 'acao', 'avisos'),
                          show='headings', height=15)
        for c, t, w, anc in [('nota', 'Nota', 70, 'w'), ('produto', 'Produto', 240, 'w'),
                             ('qtd', 'Qtd', 70, 'e'), ('un', 'Un', 42, 'center'),
                             ('custo', 'Custo un.', 80, 'e'), ('venda', 'Venda sug.', 85, 'e'),
                             ('acao', 'Ação', 82, 'w'), ('avisos', 'Avisos', 210, 'w')]:
            tv.heading(c, text=t)
            tv.column(c, width=w, anchor=anc)
        tv.tag_configure('par', background=COR['branco'])
        tv.tag_configure('impar', background=COR['zebra'])
        tv.tag_configure('alerta', background=COR['amareloclaro'], foreground=COR['ambar'])
        tv.tag_configure('novo', background=COR['verdeclaro'], foreground=COR['verde2'])
        tv.pack(fill='both', expand=True, padx=24, pady=(0, 8))
        sc = ttk.Scrollbar(dlg, orient='vertical', command=tv.yview)
        tv.configure(yscrollcommand=sc.set)

        for i, it in enumerate(plano['itens']):
            if it['acao'] == 'cadastrar':
                tag = 'novo'
            elif it['avisos']:
                tag = 'alerta'
            else:
                tag = 'par' if i % 2 == 0 else 'impar'
            venda = self._moeda(it['preco_venda_sugerido']) if it['preco_venda_sugerido'] else '—'
            tv.insert('', 'end', tags=(tag,), values=(
                it['documento'], it['nome'], self._formatq(it['quantidade'], it['unidade']),
                it['unidade'], self._moeda(it['custo_unitario']), venda,
                'Cadastrar' if it['acao'] == 'cadastrar' else 'Atualizar',
                '; '.join(it['avisos']) or '—'))

        aplicar_preco = tk.BooleanVar(value=False)
        tk.Checkbutton(dlg, text='Aplicar também o preço de venda sugerido nos produtos que já existem',
                       variable=aplicar_preco, bg=COR['branco'], fg=COR['cinza'], activebackground=COR['branco'],
                       selectcolor=COR['branco'], font=(FONTE, 9)).pack(anchor='w', padx=24)

        def confirmar():
            venc = ent_venc.get().strip() if ent_venc else None
            validade = ent_validade.get().strip() if ent_validade else None
            if plano.get('precisa_vencimento') and not venc:
                messagebox.showerror('Dados da nota', 'Informe o vencimento das notas que não trazem duplicata.', parent=dlg)
                return
            if plano.get('tem_perecivel') and not validade:
                messagebox.showerror('Dados da nota', 'Informe a validade dos itens perecíveis.', parent=dlg)
                return
            for rotulo, valor in (('vencimento', venc), ('validade', validade)):
                if valor:
                    try:
                        date.fromisoformat(valor)
                    except ValueError:
                        messagebox.showerror('Data inválida', f'{rotulo.capitalize()} deve estar em AAAA-MM-DD.', parent=dlg)
                        return
            try:
                resultado = nfe.aplicar(caminhos, plano, aplicar_preco.get(),
                                        vencimento_padrao=venc, forma_padrao=var_forma.get(),
                                        validade_padrao=validade)
            except Exception as exc:
                messagebox.showerror('Erro ao importar a nota', str(exc), parent=dlg)
                return
            dlg.destroy()
            msg = (f"{resultado['notas']} nota(s) importada(s).\n"
                   f"{len(resultado['cadastrados'])} produto(s) novo(s) cadastrado(s).")
            if resultado['avisos']:
                msg += '\n\n⚠ ' + '\n⚠ '.join(resultado['avisos'][:6])
            msg += f"\n\nBackup do banco salvo em:\n{resultado['backup']}"
            messagebox.showinfo('Nota importada', msg)
            self._aba_atualizada()

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=(6, 20), side='bottom')
        ttk.Button(botoes, text='CONFIRMAR E GRAVAR', style='Primary.TButton', command=confirmar).pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))

    def _revisar_categorias(self):
        resultado = catmod.analisar()
        if not resultado['mudancas']:
            messagebox.showinfo('Categorias', 'Nenhum produto sem categoria ou fora do padrão. Cadastro em ordem.')
            return
        self._modal_revisar_categorias(resultado['mudancas'])

    def _modal_revisar_categorias(self, mudancas):
        dlg = tk.Toplevel(self)
        dlg.title('Revisar categorias')
        dlg.geometry('640x520')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Categorias pra ajustar', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 15, 'bold')).pack(anchor='w', padx=24, pady=(16, 4))
        tk.Label(dlg, text=f"{len(mudancas)} produto(s) sem categoria ou fora do padrão. Nada foi gravado ainda.",
                bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9)).pack(anchor='w', padx=24, pady=(0, 10))

        tv = ttk.Treeview(dlg, columns=('nome', 'de', 'para'), show='headings', height=16)
        tv.heading('nome', text='Produto')
        tv.heading('de', text='Categoria atual')
        tv.heading('para', text='Categoria sugerida')
        tv.column('nome', width=280)
        tv.column('de', width=130)
        tv.column('para', width=160)
        tv.tag_configure('par', background=COR['branco'])
        tv.tag_configure('impar', background=COR['zebra'])
        tv.tag_configure('duvida', background=COR['amareloclaro'], foreground=COR['ambar'])
        tv.pack(fill='both', expand=True, padx=24, pady=(0, 10))
        sc = ttk.Scrollbar(dlg, orient='vertical', command=tv.yview)
        tv.configure(yscrollcommand=sc.set)
        for i, m in enumerate(mudancas):
            tag = 'par' if m['confiante'] and i % 2 == 0 else ('impar' if m['confiante'] else 'duvida')
            tv.insert('', 'end', tags=(tag,), values=(m['nome'], m['de'], m['para']))
        revisar = [m for m in mudancas if not m['confiante']]
        if revisar:
            tk.Label(dlg, text=f"⚠ {len(revisar)} em amarelo caíram no padrão geral (Mercearia) por falta de palavra-chave — vale conferir.",
                    bg=COR['branco'], fg=COR['ambar'], font=(FONTE, 9)).pack(anchor='w', padx=24, pady=(0, 6))

        def confirmar():
            n, backup = catmod.aplicar(mudancas)
            dlg.destroy()
            messagebox.showinfo('Categorias atualizadas', f'{n} produto(s) atualizado(s).\nBackup do banco em:\n{backup}')
            self._aba_atualizada()

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=(6, 20), side='bottom')
        ttk.Button(botoes, text='APLICAR', style='Primary.TButton', command=confirmar).pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))

    def _exportar_relatorio(self):
        caminho = filedialog.asksaveasfilename(
            title='Salvar relatório de análises',
            defaultextension='.xlsx',
            filetypes=[('Planilha Excel', '*.xlsx')],
            initialfile=f'Relatorio_Mercadinho_{datetime.now().strftime("%Y-%m-%d")}.xlsx')
        if not caminho:
            return
        inicio, fim = getattr(self, '_periodo_atual', (None, None))
        try:
            resultado = gerar_relatorio_xlsx(caminho, inicio, fim)
        except Exception as exc:
            messagebox.showerror('Erro ao gerar relatório', str(exc))
            return
        messagebox.showinfo(
            'Relatório gerado',
            f"Relatório salvo com {resultado['abas']} abas.\n"
            f"Período: {resultado['periodo']}\n"
            f"{resultado['numero_vendas']} venda(s) · {self._moeda(resultado['faturamento'])}")

    # ------------------------------------------------------------------
    # TELA DO CLIENTE — visor voltado pro cliente durante a compra
    # ------------------------------------------------------------------
    def _abrir_visor_cliente(self):
        if self.janela_cliente and self.janela_cliente.winfo_exists():
            self.janela_cliente.lift()
            self.janela_cliente.focus_force()
            return

        dlg = tk.Toplevel(self)
        self.janela_cliente = dlg
        dlg.title('FMG Mercadinho — Tela do Cliente')
        dlg.configure(bg=COR['papel'])
        dlg.geometry('900x600+80+40')
        dlg.minsize(640, 420)
        dlg._cheia = False

        def alternar_cheia(event=None):
            dlg._cheia = not dlg._cheia
            dlg.attributes('-fullscreen', dlg._cheia)

        def sair_cheia(event=None):
            dlg._cheia = False
            dlg.attributes('-fullscreen', False)

        dlg.bind('<F11>', alternar_cheia)
        dlg.bind('<Escape>', sair_cheia)

        topo = tk.Frame(dlg, bg=COR['verde2'], height=90)
        topo.pack(fill='x')
        topo.pack_propagate(False)
        tk.Label(topo, text='🧺 FMG Mercadinho', bg=COR['verde2'], fg='white', font=(FONTE, 24, 'bold')).pack(side='left', padx=30, pady=20)
        tk.Label(topo, text='F11: tela cheia   ·   Esc: sair da tela cheia', bg=COR['verde2'], fg='#6E9683', font=(FONTE, 9)).pack(side='right', padx=30)
        tk.Frame(dlg, bg=COR['amarelo'], height=4).pack(fill='x')

        corpo = tk.Frame(dlg, bg=COR['papel'])
        corpo.pack(fill='both', expand=True)
        corpo.rowconfigure(0, weight=1)
        corpo.columnconfigure(0, weight=1)
        canvas_v = tk.Canvas(corpo, bg=COR['papel'], highlightthickness=0)
        scroll_v = ttk.Scrollbar(corpo, orient='vertical', command=canvas_v.yview)
        canvas_v.configure(yscrollcommand=scroll_v.set)
        canvas_v.grid(row=0, column=0, sticky='nsew', padx=(20, 0), pady=20)
        scroll_v.grid(row=0, column=1, sticky='ns', pady=20)
        lista_v = tk.Frame(canvas_v, bg=COR['papel'])
        janela_v = canvas_v.create_window((0, 0), window=lista_v, anchor='nw')
        lista_v.bind('<Configure>', lambda e: canvas_v.configure(scrollregion=canvas_v.bbox('all')))
        canvas_v.bind('<Configure>', lambda e: canvas_v.itemconfig(janela_v, width=e.width))

        rodape = tk.Frame(dlg, bg=COR['amarelo'])
        rodape.pack(fill='x', side='bottom')
        total_lbl = tk.Label(rodape, text='R$ 0,00', bg=COR['amarelo'], fg=COR['verde2'], font=('Consolas', 46, 'bold'))
        total_lbl.pack(pady=18)

        dlg._lista_itens = lista_v
        dlg._label_total = total_lbl

        def ao_fechar():
            self.janela_cliente = None
            dlg.destroy()
        dlg.protocol('WM_DELETE_WINDOW', ao_fechar)

        self._atualizar_visor_cliente()

    def _atualizar_visor_cliente(self):
        dlg = getattr(self, 'janela_cliente', None)
        if not dlg or not dlg.winfo_exists() or getattr(self, '_visor_agradecendo', False):
            return
        lista = dlg._lista_itens
        for w in lista.winfo_children():
            w.destroy()
        if not self.carrinho:
            tk.Label(lista, text='Bem-vindo(a) à FMG Mercadinho! 🧺', bg=COR['papel'], fg=COR['verde2'], font=(FONTE, 22, 'bold')).pack(pady=(60, 10))
            tk.Label(lista, text='Aguardando o início da sua compra...', bg=COR['papel'], fg=COR['cinza'], font=(FONTE, 13)).pack()
            dlg._label_total.config(text='R$ 0,00')
            return
        for i, item in enumerate(self.carrinho):
            subtotal = max(0, item['quantidade'] * item['preco_unitario'] - item.get('desconto', 0))
            cor_fundo = COR['branco'] if i % 2 == 0 else COR['zebra']
            linha = tk.Frame(lista, bg=cor_fundo)
            linha.pack(fill='x', pady=1)
            tk.Label(linha, text=item['nome'], bg=cor_fundo, fg=COR['verde2'], font=(FONTE, 15), anchor='w').pack(side='left', fill='x', expand=True, padx=16, pady=10)
            tk.Label(linha, text=self._formatq(item['quantidade'], item['unidade']), bg=cor_fundo, fg=COR['cinza'], font=(FONTE, 12)).pack(side='left', padx=10)
            tk.Label(linha, text=self._moeda(subtotal), bg=cor_fundo, fg=COR['verde2'], font=('Consolas', 15, 'bold')).pack(side='right', padx=16)
        subtotal_total = max(0, sum(i['quantidade'] * i['preco_unitario'] - i.get('desconto', 0) for i in self.carrinho))
        dlg._label_total.config(text=self._moeda(subtotal_total))

    def _mostrar_agradecimento_visor(self, valor):
        dlg = getattr(self, 'janela_cliente', None)
        if not dlg or not dlg.winfo_exists():
            return
        self._visor_agradecendo = True
        lista = dlg._lista_itens
        for w in lista.winfo_children():
            w.destroy()
        tk.Label(lista, text='✅ Compra finalizada!', bg=COR['papel'], fg=COR['verde2'], font=(FONTE, 26, 'bold')).pack(pady=(60, 10))
        tk.Label(lista, text='Obrigado pela preferência, volte sempre 😊', bg=COR['papel'], fg=COR['cinza'], font=(FONTE, 14)).pack()
        dlg._label_total.config(text=self._moeda(valor))

        def _resetar():
            self._visor_agradecendo = False
            self._atualizar_visor_cliente()
        self.after(6000, _resetar)


    def _montar_estoque(self):
        """Aba Estoque/Validades: mostra o estoque por lote com datas de validade,
        permitindo ver o que vence em breve, o que já venceu, e gerenciar lotes."""
        p = self.tab_estoque
        p.columnconfigure(0, weight=1)
        p.rowconfigure(2, weight=1)

        # Cabeçalho
        cab = tk.Frame(p, bg=COR['papel'])
        cab.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        tk.Label(cab, text=T('tab_estoque'), bg=COR['papel'], fg=COR['verde2'], font=(FONTE, 20, 'bold')).pack(side='left')
        ttk.Button(cab, text=T('btn_atualizar'), style='Secondary.TButton', command=self._carrega_estoque).pack(side='right', padx=(0, 6))
        ttk.Button(cab, text=T('btn_adicionar_lote'), style='Primary.TButton', command=self._abrir_novo_lote_global).pack(side='right')

        # Filtros
        filtros = tk.Frame(p, bg=COR['papel'])
        filtros.grid(row=1, column=0, sticky='ew', pady=(0, 10))
        tk.Label(filtros, text='Filtrar:', bg=COR['papel'], fg=COR['cinza'], font=(FONTE, 9)).pack(side='left', padx=(0, 8))
        self.filtro_estoque_tipo = tk.StringVar(value='todos')
        for txt_key, val in [('filtro_todos', 'todos'), ('filtro_vencidos', 'vencidos'), ('filtro_proximos', 'proximos'), ('filtro_sem_data', 'sem_data')]:
            ttk.Radiobutton(filtros, text=T(txt_key), value=val, variable=self.filtro_estoque_tipo,
                           command=self._aplicar_filtro_estoque).pack(side='left', padx=4)
        tk.Label(filtros, text='Buscar:', bg=COR['papel'], fg=COR['cinza'], font=(FONTE, 9)).pack(side='left', padx=(16, 8))
        self.busca_estoque = tk.Entry(filtros, font=(FONTE, 10), relief='solid', bd=1, width=25)
        self.busca_estoque.pack(side='left', ipady=3)
        self.busca_estoque.bind('<KeyRelease>', lambda e: self._aplicar_filtro_estoque())
        _uppercase_ao_digitar(self.busca_estoque)

        # Tabela de lotes
        tabela = tk.Frame(p, bg=COR['branco'], highlightbackground=COR['linha'], highlightthickness=1)
        tabela.grid(row=2, column=0, sticky='nsew')
        tabela.rowconfigure(0, weight=1)
        tabela.columnconfigure(0, weight=1)
        self.tv_estoque = ttk.Treeview(tabela, columns=('produto', 'qtd', 'validade', 'situacao', 'obs', 'data_entrada'), show='headings')
        self.tv_estoque.grid(row=0, column=0, sticky='nsew')
        self.tv_estoque.heading('produto', text=T('tab_produtos'))
        self.tv_estoque.heading('qtd', text=T('tab_qtd') if hasattr(self, 'tab_qtd') else 'Qtd')
        self.tv_estoque.heading('validade', text='Validade')
        self.tv_estoque.heading('situacao', text='Situação')
        self.tv_estoque.heading('obs', text='Observação')
        self.tv_estoque.heading('data_entrada', text='Entrada')
        self.tv_estoque.column('produto', width=280)
        self.tv_estoque.column('qtd', width=80, anchor='center')
        self.tv_estoque.column('validade', width=100, anchor='center')
        self.tv_estoque.column('situacao', width=130, anchor='center')
        self.tv_estoque.column('obs', width=200)
        self.tv_estoque.column('data_entrada', width=120, anchor='center')
        self.tv_estoque.tag_configure('vencido', foreground=COR['vermelho'], background=COR['vermelhoclaro'])
        self.tv_estoque.tag_configure('proximo', foreground=COR['ambar'], background=COR['amareloclaro'])
        self.tv_estoque.tag_configure('ok', background=COR['branco'])
        self.tv_estoque.tag_configure('sem_data', background=COR['verdeclaro'])
        sc = ttk.Scrollbar(tabela, orient='vertical', command=self.tv_estoque.yview)
        sc.grid(row=0, column=1, sticky='ns')
        self.tv_estoque.configure(yscrollcommand=sc.set)
        self.tv_estoque.bind('<Double-1>', lambda e: self._editar_lote_selecionado())

        # Botões de ação
        botoes = tk.Frame(p, bg=COR['papel'])
        botoes.grid(row=3, column=0, sticky='ew', pady=(10, 0))
        ttk.Button(botoes, text=T('btn_editar_lote'), style='Secondary.TButton', command=self._editar_lote_selecionado).pack(side='left')
        ttk.Button(botoes, text=T('btn_registrar_perda'), style='Primary.TButton', command=self._registrar_perda_lote).pack(side='left', padx=(8, 0))
        ttk.Button(botoes, text=T('btn_remover_lote'), style='Secondary.TButton', command=self._remover_lote_selecionado).pack(side='left', padx=(8, 0))
        ttk.Button(botoes, text=T('btn_ajustar_estoque'), style='Secondary.TButton', command=self._ajustar_estoque_global).pack(side='right')

        self._carrega_estoque()

    def _montar_historico(self):
        p = self.tab_hist
        p.rowconfigure(2, weight=1)
        p.columnconfigure(0, weight=1)
        cab = tk.Frame(p, bg=COR['papel'])
        cab.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        tk.Label(cab, text='Histórico de vendas', bg=COR['papel'], fg=COR['verde2'], font=(FONTE, 20, 'bold')).pack(side='left')
        tk.Label(cab, text='dê 2 cliques numa venda pra ver os itens e reimprimir o recibo', bg=COR['papel'],
                 fg=COR['cinza'], font=(FONTE, 9)).pack(side='left', padx=(14, 0))
        ttk.Button(cab, text='Atualizar', style='Secondary.TButton', command=self._atualizar_hist).pack(side='right')

        # Resumo de recebimentos separado por forma de pagamento (dinheiro, pix,
        # débito, crédito, voucher...), com filtro de período.
        self.hist_periodo = tk.StringVar(value='hoje')
        self.hist_filtro = tk.StringVar(value='Todas')
        painel = tk.Frame(p, bg=COR['papel'])
        painel.grid(row=1, column=0, sticky='ew', pady=(0, 12))
        painel.columnconfigure(0, weight=1)
        topo = tk.Frame(painel, bg=COR['papel'])
        topo.grid(row=0, column=0, sticky='ew')
        tk.Label(topo, text='Recebido por forma de pagamento', bg=COR['papel'], fg=COR['verde2'],
                 font=(FONTE, 12, 'bold')).pack(side='left')
        for texto, valor in [('Tudo', 'tudo'), ('Mês', 'mes'), ('Semana', 'semana'), ('Hoje', 'hoje')]:
            ttk.Radiobutton(topo, text=texto, value=valor, variable=self.hist_periodo,
                            command=self._carrega_resumo_hist).pack(side='right', padx=(10, 0))
        tk.Label(topo, text='Filtrar vendas:', bg=COR['papel'], fg=COR['cinza'],
                 font=(FONTE, 9)).pack(side='right', padx=(20, 4))
        self.combo_hist_forma = ttk.Combobox(topo, textvariable=self.hist_filtro, state='readonly',
                                             font=(FONTE, 9), width=12,
                                             values=['Todas'] + [r for _, r in op.FORMAS_PAGAMENTO_VENDA] + ['Cartão'])
        self.combo_hist_forma.pack(side='right')
        self.combo_hist_forma.bind('<<ComboboxSelected>>', lambda e: self._carrega_hist())
        self.frame_resumo_pag = tk.Frame(painel, bg=COR['papel'])
        self.frame_resumo_pag.grid(row=1, column=0, sticky='ew', pady=(8, 0))

        tabela = tk.Frame(p, highlightbackground=COR['linha'], highlightthickness=1)
        tabela.grid(row=2, column=0, sticky='nsew')
        tabela.rowconfigure(0, weight=1)
        tabela.columnconfigure(0, weight=1)
        self.tvhist = ttk.Treeview(tabela, columns=('id', 'data', 'cliente', 'pag', 'valor'), show='headings')
        self.tvhist.grid(row=0, column=0, sticky='nsew')
        larguras = {'id': 60, 'data': 160, 'cliente': 160, 'pag': 130, 'valor': 110}
        for c, t in [('id', '#'), ('data', 'Data/Hora'), ('cliente', 'Cliente'), ('pag', 'Pagamento'), ('valor', 'Total')]:
            self.tvhist.heading(c, text=t)
            self.tvhist.column(c, width=larguras[c], anchor='e' if c in ('id', 'valor') else 'w')
        self.tvhist.tag_configure('par', background=COR['branco'])
        self.tvhist.tag_configure('impar', background=COR['zebra'])
        self.tvhist.tag_configure('fiado', foreground=COR['ambar'])
        self.tvhist.bind('<Double-1>', lambda e: self._abrir_detalhe_venda())
        sch = ttk.Scrollbar(tabela, orient='vertical', command=self.tvhist.yview)
        sch.grid(row=0, column=1, sticky='ns')
        self.tvhist.configure(yscrollcommand=sch.set)
        self._carrega_resumo_hist()
        self._carrega_hist()

    def _atualizar_hist(self):
        self._carrega_resumo_hist()
        self._carrega_hist()

    def _carrega_resumo_hist(self):
        dados = op.resumo_por_forma_pagamento(self.hist_periodo.get())
        for w in self.frame_resumo_pag.winfo_children():
            w.destroy()
        if not dados['itens']:
            tk.Label(self.frame_resumo_pag, text='Nenhuma venda registrada no período.', bg=COR['papel'],
                     fg=COR['cinza'], font=(FONTE, 10)).pack(anchor='w', pady=6)
            return
        for item in dados['itens']:
            fiado = item['forma'] == 'fiado'
            card = tk.Frame(self.frame_resumo_pag, bg=COR['branco'],
                            highlightbackground=COR['linha'], highlightthickness=1)
            card.pack(side='left', fill='y', padx=(0, 8))
            tk.Label(card, text=item['rotulo'].upper(), bg=COR['branco'], fg=COR['cinza'],
                     font=(FONTE, 8, 'bold')).pack(anchor='w', padx=12, pady=(8, 0))
            tk.Label(card, text=self._moeda(item['total']), bg=COR['branco'],
                     fg=COR['ambar'] if fiado else COR['verde2'],
                     font=('Consolas', 14, 'bold')).pack(anchor='w', padx=12)
            legenda = f"{item['n']} venda(s)" + (' · a receber' if fiado else '')
            tk.Label(card, text=legenda, bg=COR['branco'], fg=COR['cinza'],
                     font=(FONTE, 8)).pack(anchor='w', padx=12, pady=(0, 8))
        total = tk.Frame(self.frame_resumo_pag, bg=COR['verdeclaro'],
                         highlightbackground=COR['linha'], highlightthickness=1)
        total.pack(side='left', fill='y')
        tk.Label(total, text='TOTAL DO PERÍODO', bg=COR['verdeclaro'], fg=COR['verde2'],
                 font=(FONTE, 8, 'bold')).pack(anchor='w', padx=12, pady=(8, 0))
        tk.Label(total, text=self._moeda(dados['total']), bg=COR['verdeclaro'], fg=COR['verde2'],
                 font=('Consolas', 14, 'bold')).pack(anchor='w', padx=12)
        tk.Label(total, text='inclui fiado (a receber)', bg=COR['verdeclaro'], fg=COR['cinza'],
                 font=(FONTE, 8)).pack(anchor='w', padx=12, pady=(0, 8))

    def _carrega_hist(self):
        self.tvhist.delete(*self.tvhist.get_children())
        filtro = getattr(self, 'hist_filtro', None)
        filtro_atual = filtro.get() if filtro else 'Todas'
        chave_filtro = next((k for k, r in op.FORMAS_PAGAMENTO_VENDA if r == filtro_atual), None)
        if chave_filtro is None and filtro_atual == 'Cartão':
            chave_filtro = 'cartao'
        for i, venda in enumerate(op.listar_vendas()):
            if chave_filtro and venda['forma_pagamento'] != chave_filtro:
                continue
            rotulo = op.rotulo_forma_pagamento(venda['forma_pagamento'])
            if venda.get('voucher_marca'):
                rotulo += f" {venda['voucher_marca']}"
            tag = 'fiado' if venda['forma_pagamento'] == 'fiado' else ('par' if i % 2 == 0 else 'impar')
            self.tvhist.insert('', 'end', iid=str(venda['id']), tags=(tag,), values=(
                venda['id'], venda['data_hora'], venda['cliente_nome'] or '—', rotulo, self._moeda(venda['valor_total']) + (' CANCELADA' if venda.get('cancelada') else '')))

    # --- Estoque/Validades ---
    def _carrega_estoque(self):
        if not hasattr(self, 'tv_estoque'):
            return
        self._aplicar_filtro_estoque()

    def _aplicar_filtro_estoque(self):
        if not hasattr(self, 'tv_estoque'):
            return
        tipo = getattr(self, 'filtro_estoque_tipo', None)
        if not tipo:
            return
        filtro_tipo = tipo.get()
        termo = getattr(self, 'busca_estoque', None)
        busca = termo.get().strip() if termo else ''
        self.tv_estoque.delete(*self.tv_estoque.get_children())
        self._lotes_cache = {}
        todos = val.todos_lotes_com_produto()
        hoje = date.today()
        for lote in todos:
            if busca and busca.lower() not in lote['nome'].lower():
                continue
            if not lote['data_validade']:
                tag, situacao = 'sem_data', 'Sem validade'
            else:
                try:
                    dv = date.fromisoformat(lote['data_validade'])
                    dias = (dv - hoje).days
                    if dias < 0:
                        tag, situacao = 'vencido', f'Vencido há {abs(dias)}d'
                    elif dias <= 7:
                        tag, situacao = 'proximo', f'Vence em {dias}d'
                    else:
                        tag, situacao = 'ok', f'Vence em {dias}d'
                except ValueError:
                    tag, situacao = 'ok', 'Data inválida'
            if filtro_tipo == 'vencidos' and tag != 'vencido':
                continue
            if filtro_tipo == 'proximos' and tag != 'proximo':
                continue
            if filtro_tipo == 'sem_data' and tag != 'sem_data':
                continue
            self._lotes_cache[lote['lote_id']] = lote
            validade_br = datetime.strptime(lote['data_validade'], '%Y-%m-%d').strftime('%d/%m/%Y') if lote['data_validade'] else '—'
            entrada_br = datetime.strptime(lote['data_entrada'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y') if lote['data_entrada'] else '—'
            self.tv_estoque.insert('', 'end', iid=str(lote['lote_id']), tags=(tag,), values=(
                lote['nome'], self._formatq(lote['quantidade'], lote['unidade']), validade_br, situacao, lote['observacao'] or '', entrada_br))

    def _abrir_novo_lote_global_legado(self):
        dlg = tk.Toplevel(self)
        dlg.title('Adicionar lote de validade')
        dlg.geometry('420x480')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.resizable(False, False)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Adicionar lote de validade', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 14, 'bold')).pack(anchor='w', padx=24, pady=(16, 12))

        tk.Label(dlg, text='PRODUTO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24)
        ent_produto = tk.Entry(dlg, font=(FONTE, 10), relief='solid', bd=1,
                                highlightthickness=1, highlightbackground=COR['linha'], highlightcolor=COR['verde'])
        ent_produto.pack(fill='x', padx=24, ipady=5)
        _uppercase_ao_digitar(ent_produto)
        lista_sugestoes = tk.Listbox(dlg, height=4, font=(FONTE, 9))
        produto_escolhido = {'id': None}

        def buscar(event=None):
            termo = ent_produto.get().strip()
            lista_sugestoes.delete(0, 'end')
            if len(termo) < 2:
                lista_sugestoes.pack_forget()
                return
            achados = op.listar_produtos(termo)[:8]
            if not achados:
                lista_sugestoes.pack_forget()
                return
            for p in achados:
                lista_sugestoes.insert('end', p['nome'])
            lista_sugestoes._achados = achados
            lista_sugestoes.pack(fill='x', padx=24, pady=(2, 0))

        def escolher(event=None):
            sel = lista_sugestoes.curselection()
            if sel:
                p = lista_sugestoes._achados[sel[0]]
                ent_produto.delete(0, 'end')
                ent_produto.insert(0, p['nome'])
                produto_escolhido['id'] = p['id']
                lista_sugestoes.pack_forget()

        ent_produto.bind('<KeyRelease>', buscar)
        lista_sugestoes.bind('<Double-1>', escolher)
        lista_sugestoes.bind('<Return>', escolher)

        tk.Label(dlg, text='QUANTIDADE', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        ent_qtd = tk.Entry(dlg, font=(FONTE, 11), relief='solid', bd=1)
        ent_qtd.pack(fill='x', padx=24, ipady=5)
        _uppercase_ao_digitar(ent_qtd)

        tk.Label(dlg, text='DATA DE VALIDADE (AAAA-MM-DD, opcional)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        ent_validade = tk.Entry(dlg, font=(FONTE, 11), relief='solid', bd=1)
        ent_validade.pack(fill='x', padx=24, ipady=5)
        _uppercase_ao_digitar(ent_validade)

        tk.Label(dlg, text='OBSERVAÇÃO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        ent_obs = tk.Entry(dlg, font=(FONTE, 11), relief='solid', bd=1)
        ent_obs.pack(fill='x', padx=24, ipady=5)
        _uppercase_ao_digitar(ent_obs)

        def salvar():
            if not produto_escolhido['id']:
                messagebox.showerror('Produto', 'Selecione um produto da lista.', parent=dlg)
                return
            qtd = self._para_float(ent_qtd.get(), 0)
            if qtd <= 0:
                messagebox.showerror('Quantidade', 'Informe uma quantidade maior que zero.', parent=dlg)
                return
            data_validade = ent_validade.get().strip() or None
            if data_validade:
                try:
                    date.fromisoformat(data_validade)
                except ValueError:
                    messagebox.showerror('Data', 'Data de validade inválida. Use AAAA-MM-DD.', parent=dlg)
                    return
            try:
                val.registrar_lote(produto_escolhido['id'], qtd, data_validade, ent_obs.get().strip())
                dlg.destroy()
                self._carrega_estoque()
                self._carrega_produtos()
                self._toast('Lote adicionado')
            except Exception as exc:
                messagebox.showerror('Erro', str(exc), parent=dlg)

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=(12, 18), side='bottom')
        ttk.Button(botoes, text='Salvar', style='Primary.TButton', command=salvar).pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))
        ent_produto.focus_set()

    def _editar_lote_selecionado(self):
        sel = self.tv_estoque.selection()
        if not sel:
            messagebox.showinfo('Selecione', 'Clique num lote da lista primeiro.')
            return
        lote_id = int(sel[0])
        lote = self._lotes_cache.get(lote_id)
        if not lote:
            return
        dlg = tk.Toplevel(self)
        dlg.title('Editar lote')
        dlg.geometry('420x440')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.resizable(False, False)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text=f'Editar lote de {lote["nome"]}', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 14, 'bold')).pack(anchor='w', padx=24, pady=(16, 12))

        tk.Label(dlg, text='QUANTIDADE', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24)
        ent_qtd = tk.Entry(dlg, font=(FONTE, 11), relief='solid', bd=1)
        ent_qtd.pack(fill='x', padx=24, ipady=5)
        ent_qtd.insert(0, str(lote['quantidade']))
        _uppercase_ao_digitar(ent_qtd)

        tk.Label(dlg, text='DATA DE VALIDADE (AAAA-MM-DD, opcional)', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        ent_validade = tk.Entry(dlg, font=(FONTE, 11), relief='solid', bd=1)
        ent_validade.pack(fill='x', padx=24, ipady=5)
        if lote['data_validade']:
            ent_validade.insert(0, lote['data_validade'])
        _uppercase_ao_digitar(ent_validade)

        tk.Label(dlg, text='OBSERVAÇÃO', bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 8, 'bold')).pack(anchor='w', padx=24, pady=(12, 3))
        ent_obs = tk.Entry(dlg, font=(FONTE, 11), relief='solid', bd=1)
        ent_obs.pack(fill='x', padx=24, ipady=5)
        if lote['observacao']:
            ent_obs.insert(0, lote['observacao'])
        _uppercase_ao_digitar(ent_obs)

        def salvar():
            qtd = self._para_float(ent_qtd.get(), 0)
            if qtd < 0:
                messagebox.showerror('Quantidade', 'Quantidade não pode ser negativa.', parent=dlg)
                return
            data_validade = ent_validade.get().strip() or None
            if data_validade:
                try:
                    date.fromisoformat(data_validade)
                except ValueError:
                    messagebox.showerror('Data', 'Data de validade inválida. Use AAAA-MM-DD.', parent=dlg)
                    return
            try:
                val.editar_lote(lote_id, qtd, data_validade, ent_obs.get().strip())
                dlg.destroy()
                self._carrega_estoque()
                self._carrega_produtos()
                self._toast('Lote atualizado')
            except Exception as exc:
                messagebox.showerror('Erro', str(exc), parent=dlg)

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=(12, 18), side='bottom')
        ttk.Button(botoes, text='Salvar', style='Primary.TButton', command=salvar).pack(side='right')
        ttk.Button(botoes, text='Cancelar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))

    def _registrar_perda_lote(self):
        sel = self.tv_estoque.selection()
        if not sel:
            messagebox.showinfo('Selecione', 'Clique num lote da lista primeiro.')
            return
        lote_id = int(sel[0])
        lote = self._lotes_cache.get(lote_id)
        if not lote:
            return
        if not messagebox.askyesno(
                'Registrar perda',
                f'Jogar fora {self._formatq(lote["quantidade"], lote["unidade"])} de {lote["nome"]} '
                f'e registrar como perda (validade vencida)?'):
            return
        try:
            obs = f'Lote vencido em {lote["data_validade"]}' if lote['data_validade'] else 'Lote sem validade definida'
            op.registrar_perda([{'produto_id': lote['produto_id'], 'quantidade': lote['quantidade'], 'lote_id': lote_id}],
                                'Validade vencida', obs)
            self._carrega_estoque()
            self._carrega_produtos()
            self._carrega_resumo_perda()
            self._carrega_historico_perda()
            self._toast(f'{lote["nome"]} registrado como perda.')
        except Exception as exc:
            messagebox.showerror('Erro', str(exc))

    def _remover_lote_selecionado(self):
        sel = self.tv_estoque.selection()
        if not sel:
            messagebox.showinfo('Selecione', 'Clique num lote da lista primeiro.')
            return
        lote_id = int(sel[0])
        lote = self._lotes_cache.get(lote_id)
        if not lote:
            return
        if not messagebox.askyesno('Remover lote', f'Remover o lote de {lote["nome"]} ({self._formatq(lote["quantidade"], lote["unidade"])})?'):
            return
        try:
            val.excluir_lote(lote_id)
            self._carrega_estoque()
            self._carrega_produtos()
            self._toast('Lote removido')
        except Exception as exc:
            messagebox.showerror('Erro', str(exc))

    def _ajustar_estoque_global(self):
        sel = self.tv_estoque.selection()
        if not sel:
            messagebox.showinfo('Selecione', 'Clique num lote/produto da lista primeiro.')
            return
        lote_id = int(sel[0])
        lote = self._lotes_cache.get(lote_id)
        if not lote:
            return
        produto = op.buscar_por_codigo(str(lote['produto_id']))
        if not produto:
            messagebox.showerror('Erro', 'Produto não encontrado.')
            return
        texto = simpledialog.askstring('Ajustar estoque total', f'Novo total de {produto["nome"]} ({produto["unidade"]}):',
                                        initialvalue=str(produto['quantidade_estoque']), parent=self)
        if texto is None:
            return
        try:
            op.ajustar_estoque(produto['id'], self._para_float(texto), tipo='ajuste', observacao='Ajuste manual via Estoque/Validades')
            self._carrega_estoque()
            self._carrega_produtos()
            self._toast('Estoque ajustado')
        except Exception as exc:
            messagebox.showerror('Erro', str(exc))

    def _abrir_detalhe_venda(self):
        sel = self.tvhist.selection()
        if not sel:
            return
        venda_id = int(sel[0])
        try:
            venda = op.detalhar_venda(venda_id)
        except (op.ErroOperacao, g.ErroGestao) as exc:
            messagebox.showerror('Erro', str(exc))
            return

        dlg = tk.Toplevel(self)
        dlg.title(f'Venda #{venda_id}')
        dlg.geometry('460x520')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        cab = tk.Frame(dlg, bg=COR['branco'])
        cab.pack(fill='x', padx=24, pady=(16, 4))
        tk.Label(cab, text=f'Venda #{venda_id}', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 15, 'bold')).pack(side='left')
        tk.Label(cab, text=self._moeda(venda['valor_total']), bg=COR['branco'], fg=COR['verde2'], font=('Consolas', 15, 'bold')).pack(side='right')

        try:
            quando = datetime.strptime(venda['data_hora'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y %H:%M')
        except ValueError:
            quando = venda['data_hora']
        info = f"{quando}  ·  {op.rotulo_forma_pagamento(venda['forma_pagamento'])}"
        if venda.get('cliente_nome'):
            info += f"  ·  {venda['cliente_nome']}"
        tk.Label(dlg, text=info, bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9)).pack(anchor='w', padx=24, pady=(0, 12))
        pagamentos = venda.get('pagamentos') or []
        if len(pagamentos) > 1:
            partes = '   ·   '.join(
                f"{op.rotulo_forma_pagamento(p['forma'])} {self._moeda(p['valor'])}" for p in pagamentos)
            tk.Label(dlg, text=f'Pagamento dividido: {partes}', bg=COR['branco'], fg=COR['ambar'],
                     font=(FONTE, 9, 'bold')).pack(anchor='w', padx=24, pady=(0, 10))

        tabela = tk.Frame(dlg, highlightbackground=COR['linha'], highlightthickness=1)
        tabela.pack(fill='both', expand=True, padx=24)
        tv = ttk.Treeview(tabela, columns=('nome', 'qtd', 'sub'), show='headings')
        tv.heading('nome', text='Produto')
        tv.heading('qtd', text='Qtd')
        tv.heading('sub', text='Subtotal')
        tv.column('qtd', width=80, anchor='center')
        tv.column('sub', width=100, anchor='e')
        tv.tag_configure('par', background=COR['branco'])
        tv.tag_configure('impar', background=COR['zebra'])
        tv.pack(fill='both', expand=True)
        for i, item in enumerate(venda['itens']):
            sub = item['quantidade'] * item['preco_unitario']
            tag = 'par' if i % 2 == 0 else 'impar'
            tv.insert('', 'end', tags=(tag,), values=(item['nome'], self._formatq(item['quantidade'], item['unidade']), self._moeda(sub)))

        if venda.get('desconto'):
            tk.Label(dlg, text=f"Desconto: {self._moeda(venda['desconto'])}", bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9)).pack(anchor='e', padx=24, pady=(6, 0))

        def imprimir():
            try:
                self._imprimir_venda(venda_id)
                self._toast(f'Recibo da venda #{venda_id} enviado pra impressora.')
            except Exception as exc:
                messagebox.showerror('Impressão', str(exc), parent=dlg)

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=24, pady=18, side='bottom')
        ttk.Button(botoes, text='🖨 Imprimir recibo', style='Primary.TButton', command=imprimir).pack(side='right')
        ttk.Button(botoes, text='Fechar', style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))

    def _texto_status(self):
        agora = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        if getattr(self, 'balanca', None) and self.balanca.conectado:
            if self.balanca.leitura_recente(3.0):
                return f'Balança {self.balanca.porta} · {self.balanca.peso_atual():.3f} kg · {agora} · F1 = Atalhos'
            return f'Balança {self.balanca.porta} · conectada · {agora} · F1 = Atalhos'
        return f'SQLite · {agora} · F1 = Atalhos'

    def _atalho_global(self, func):
        """Embrulha um atalho de teclado que vale para o sistema inteiro.
        Ignora a tecla quando há um diálogo modal aberto (grab), pra não
        disparar a ação 'atrás' da janela que o usuário está usando, e
        devolve 'break' pra tecla não vazar pro widget com foco."""
        def handler(event=None):
            if self.grab_current() is not None:
                return None
            func()
            return 'break'
        return handler

    def _proxima_aba(self, passo=1):
        abas = self.nb.tabs()
        if not abas:
            return
        atual = self.nb.index(self.nb.select())
        self.nb.select(abas[(atual + passo) % len(abas)])

    def _atalho_aba(self, passo):
        """Ctrl+Tab / Ctrl+Shift+Tab. O próprio ttk.Notebook já troca de aba
        quando ele está com o foco; aqui só agimos quando o foco está em outro
        widget (ex.: o campo de busca), pra não avançar duas abas."""
        def handler(event=None):
            if self.grab_current() is not None:
                return None
            if self.focus_get() is self.nb:
                return None
            self._proxima_aba(passo)
            return 'break'
        return handler

    def _nova_venda_atalho(self):
        self.nb.select(self.tab_caixa)
        self.entrada.focus_set()
        self.entrada.selection_range(0, 'end')

    def _atalhos(self):
        """Atalhos de teclado globais do sistema (estilo caixa de mercado).
        As teclas F e Ctrl+tecla não digitam caracteres, então funcionam mesmo
        com o foco no campo de busca/código de barras, sem atrapalhar o bipador.
        Nenhum atalho de texto (Ctrl+C/V/X/A) é sobrescrito."""
        at = self._atalho_global

        # Ajuda e operação do caixa
        self.bind_all('<F1>', at(self._ajuda_atalhos))
        self.bind_all('<F2>', at(self._ir_para_busca))
        self.bind_all('<F3>', at(self._selecionar_cliente))
        self.bind_all('<F4>', at(self._focar_recebido))
        self.bind_all('<F5>', at(lambda: self._definir_pagamento('dinheiro')))
        self.bind_all('<F6>', at(lambda: self._definir_pagamento('cartao_credito')))
        self.bind_all('<F7>', at(lambda: self._definir_pagamento('cartao_debito')))
        self.bind_all('<F8>', at(lambda: self._definir_pagamento('pix')))
        self.bind_all('<F9>', at(lambda: self._definir_pagamento('voucher')))
        self.bind_all('<F10>', at(self._ativar_fiado_atalho))
        self.bind_all('<F12>', at(self._abrir_finalizar))

        # Ações rápidas disponíveis em qualquer tela
        for seq in ('<Control-p>', '<Control-P>'):
            self.bind_all(seq, at(self._imprimir_ultimo))
        for seq in ('<Control-r>', '<Control-R>'):
            self.bind_all(seq, at(self._atualizar_aba_selecionada))
        for seq in ('<Control-n>', '<Control-N>'):
            self.bind_all(seq, at(self._nova_venda_atalho))
        for seq in ('<Control-b>', '<Control-B>'):
            self.bind_all(seq, at(self._backup_manual))
        for seq in ('<Control-e>', '<Control-E>'):
            self.bind_all(seq, at(self._exportar_relatorio))
        for seq in ('<Control-k>', '<Control-K>'):
            self.bind_all(seq, at(self._gerar_catalogo))
        for seq in ('<Control-w>', '<Control-W>'):
            self.bind_all(seq, at(self._abrir_visor_cliente))
        self.bind_all('<Control-Delete>', at(self._cancelar_venda_atalho))

        # Navegação entre abas: ciclo e acesso direto (na ordem do sistema)
        self.bind_all('<Control-Tab>', self._atalho_aba(1))
        self.bind_all('<Control-ISO_Left_Tab>', self._atalho_aba(-1))
        self.bind_all('<Control-Shift-Key-Tab>', self._atalho_aba(-1))
        self.bind_all('<Control-Next>', at(lambda: self._proxima_aba(1)))
        self.bind_all('<Control-Prior>', at(lambda: self._proxima_aba(-1)))
        abas_numeradas = (self.tab_caixa, self.tab_prod, self.tab_cli, self.tab_consumo,
                          self.tab_perdas, self.tab_producao, self.tab_pain, self.tab_analises,
                          self.tab_hist, self.tab_estoque)
        for i, tab in enumerate(abas_numeradas, start=1):
            self.bind_all(f'<Control-Key-{i % 10}>', at(lambda t=tab: self.nb.select(t)))
        self.bind_all('<Control-Key-minus>', at(lambda: self.nb.select(self.tab_config)))
        self.bind_all('<Control-f>', at(lambda: self.nb.select(getattr(self, 'tab_fin', self.tab_config))))
        self.bind_all('<Control-g>', at(lambda: self.nb.select(getattr(self, 'tab_gestao', self.tab_config))))

        # Estes ficam só no carrinho da venda atual, pra não atrapalhar quando a
        # pessoa está digitando/apagando texto em outro campo.
        self.tree_car.bind('<Delete>', lambda e: self._remover())
        self.tree_car.bind('<plus>', lambda e: self._alterar_qtd(1))
        self.tree_car.bind('<KP_Add>', lambda e: self._alterar_qtd(1))
        self.tree_car.bind('<minus>', lambda e: self._alterar_qtd(-1))
        self.tree_car.bind('<KP_Subtract>', lambda e: self._alterar_qtd(-1))

    def _ir_para_busca(self):
        self.nb.select(self.tab_caixa)
        self.entrada.focus_set()
        self.entrada.selection_range(0, 'end')

    def _focar_recebido(self):
        self.nb.select(self.tab_caixa)
        self.recebido.focus_set()
        self.recebido.selection_range(0, 'end')

    def _definir_pagamento(self, valor):
        self.nb.select(self.tab_caixa)
        self.forma.set(valor)
        self._troca_pg()

    def _ativar_fiado_atalho(self):
        self.nb.select(self.tab_caixa)
        self._ativar_fiado()

    def _cancelar_venda_atalho(self):
        if not self.carrinho:
            return
        self.nb.select(self.tab_caixa)
        if messagebox.askyesno('Cancelar venda', 'Cancelar a venda atual e limpar o carrinho?'):
            self.carrinho = []
            self.cliente_fiado = None
            self.label_cliente.config(text='Nenhum')
            self.alertados_zero.clear()
            self.alertados_baixo.clear()
            self._render_car()

    def _ajuda_atalhos(self):
        dlg = tk.Toplevel(self)
        dlg.title('Atalhos do teclado')
        dlg.geometry('580x640')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())
        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text='Atalhos do teclado', bg=COR['branco'], fg=COR['verde2'], font=(FONTE, 15, 'bold')).pack(anchor='w', padx=24, pady=(16, 2))
        tk.Label(dlg, text='Funcionam em qualquer tela — são ignorados quando um diálogo está aberto.',
                 bg=COR['branco'], fg=COR['cinza'], font=(FONTE, 9)).pack(anchor='w', padx=24, pady=(0, 10))
        atalhos = [
            ('F1', 'Mostrar esta ajuda'),
            ('F2', 'Ir para a busca de produto (caixa)'),
            ('F3', 'Selecionar / cadastrar cliente'),
            ('F4', 'Focar o campo "Recebido"'),
            ('F5', 'Forma de pagamento: Dinheiro'),
            ('F6', 'Forma de pagamento: Crédito'),
            ('F7', 'Forma de pagamento: Débito'),
            ('F8', 'Forma de pagamento: Pix'),
            ('F9', 'Forma de pagamento: Voucher'),
            ('F10', 'Ativar venda fiado'),
            ('F11', 'Tela cheia total'),
            ('F12', 'Finalizar venda'),
            ('Ctrl+P', 'Reimprimir último cupom'),
            ('Ctrl+N', 'Nova venda (volta ao caixa)'),
            ('Ctrl+R', 'Atualizar a tela atual'),
            ('Ctrl+B', 'Fazer backup agora'),
            ('Ctrl+E', 'Exportar relatório de análises (.xlsx)'),
            ('Ctrl+K', 'Gerar catálogo de produtos (.xlsx)'),
            ('Ctrl+W', 'Abrir a tela do cliente (visor)'),
            ('Ctrl+Delete', 'Cancelar venda atual (limpa o carrinho)'),
            ('Ctrl+Tab', 'Ir para a próxima aba'),
            ('Ctrl+Shift+Tab', 'Voltar para a aba anterior'),
            ('Ctrl + 1 a 9', 'Abrir as abas 1 a 9: Caixa, Produtos, Clientes, Consumo interno, Perdas, Produção, Painel, Análises, Histórico'),
            ('Ctrl + 0', 'Abrir Estoque / Validades'),
            ('Ctrl + −', 'Abrir Configurações'),
            ('Ctrl+F', 'Abrir Financeiro'),
            ('Ctrl+G', 'Abrir Gestão'),
            ('Delete', 'Remover item selecionado no carrinho da venda'),
            ('+  /  −', 'Aumentar / diminuir quantidade do item selecionado no carrinho'),
            ('Esc', 'Fechar a janela aberta (ou sair da tela cheia total)'),
        ]
        wrap = tk.Frame(dlg, bg=COR['branco'])
        wrap.pack(fill='both', expand=True, padx=24, pady=(0, 10))
        canvas = tk.Canvas(wrap, bg=COR['branco'], highlightthickness=0)
        scroll = ttk.Scrollbar(wrap, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        corpo = tk.Frame(canvas, bg=COR['branco'])
        janela = canvas.create_window((0, 0), window=corpo, anchor='nw')
        corpo.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(janela, width=e.width))
        canvas.bind('<Enter>', lambda e: canvas.bind_all('<MouseWheel>', lambda ev: canvas.yview_scroll(int(-1 * (ev.delta / 120)), 'units')))
        canvas.bind('<Leave>', lambda e: canvas.unbind_all('<MouseWheel>'))
        for i, (tecla, desc) in enumerate(atalhos):
            cor_fundo = COR['zebra'] if i % 2 else COR['branco']
            linha = tk.Frame(corpo, bg=cor_fundo)
            linha.pack(fill='x')
            tk.Label(linha, text=tecla, bg=cor_fundo, fg=COR['verde2'], font=('Consolas', 10, 'bold'), width=15, anchor='w').pack(side='left', padx=(4, 8), pady=6)
            tk.Label(linha, text=desc, bg=cor_fundo, fg=COR['cinza'], font=(FONTE, 10), anchor='w', justify='left', wraplength=360).pack(side='left', fill='x', expand=True, pady=6)
        ttk.Button(dlg, text='Fechar', style='Primary.TButton', command=dlg.destroy).pack(fill='x', padx=24, pady=(0, 20))

    def _relogio(self):
        agora = datetime.now()
        ultimo = getattr(self, '_ultimo_relogio', None)
        self._ultimo_relogio = agora
        if ultimo is not None:
            atraso = (agora - ultimo).total_seconds()
            # Se o relogio (que roda a cada 1s) atrasou muito, a interface ficou
            # travada nesse intervalo. Registra para diagnostico.
            if atraso > 2.5:
                try:
                    import tempfile
                    destino = os.path.join(tempfile.gettempdir(), 'mercadinho_travamentos.log')
                    with open(destino, 'a', encoding='utf-8') as f:
                        f.write(f'{agora.isoformat(timespec="seconds")}  interface travada por ~{atraso:.1f}s\n')
                except Exception:
                    pass
        self.status.config(text=self._texto_status())
        self.after(1000, self._relogio)

    def _aba_atualizada(self):
        try:
            if hasattr(self,'painel_financeiro'): self._atualizar_financeiro()
            self._carrega_painel()
            self._carrega_analises()
            self._atualizar_hist()
            self._carrega_clientes()
            self._carrega_produtos()
            self._carrega_resumo_consumo()
            self._carrega_historico_consumo()
            self._carrega_resumo_perda()
            self._carrega_historico_perda()
            self._carrega_producao()
            self._carrega_estoque()
            aba = self.nb.select()
            if aba == str(self.tab_consumo):
                self.entrada_consumo.focus_set()
            elif aba == str(self.tab_perdas):
                self.entrada_perda.focus_set()
            elif aba == str(self.tab_caixa):
                self.entrada.focus_set()
        except Exception:
            pass

    def _atualizar_aba_selecionada(self):
        """Atualiza somente os dados da aba que ficou visivel. Evita recarregar
        as 12 abas a cada troca de aba (que deixava a navegacao lenta)."""
        try:
            aba = str(self.nb.select())
            mapa = {
                str(getattr(self, 'tab_prod', '')): (self._carrega_produtos,),
                str(getattr(self, 'tab_cli', '')): (self._carrega_clientes,),
                str(getattr(self, 'tab_consumo', '')): (self._carrega_resumo_consumo, self._carrega_historico_consumo),
                str(getattr(self, 'tab_perdas', '')): (self._carrega_resumo_perda, self._carrega_historico_perda),
                str(getattr(self, 'tab_producao', '')): (self._carrega_producao,),
                str(getattr(self, 'tab_pain', '')): (self._carrega_painel,),
                str(getattr(self, 'tab_analises', '')): (self._carrega_analises,),
                str(getattr(self, 'tab_hist', '')): (self._atualizar_hist,),
                str(getattr(self, 'tab_estoque', '')): (self._carrega_estoque,),
            }
            for fn in mapa.get(aba, ()):
                fn()
            if hasattr(self, 'painel_financeiro') and aba == str(getattr(self, 'tab_fin', '')):
                self._atualizar_financeiro()
            if aba == str(getattr(self, 'tab_consumo', '')):
                self.entrada_consumo.focus_set()
            elif aba == str(getattr(self, 'tab_perdas', '')):
                self.entrada_perda.focus_set()
            elif aba == str(getattr(self, 'tab_caixa', '')):
                self.entrada.focus_set()
        except Exception:
            pass

    def _tarefas_30min(self):
        try:
            registrar_fiado_recente(30)
        except Exception:
            pass
        self.after(30 * 60 * 1000, self._tarefas_30min)

    def _toast(self, texto):
        self.status.config(text=texto)
        self.after(5000, lambda: self.status.config(text=self._texto_status()))

    def _senha_configurada(self):
        """True quando há um usuário autenticado (fonte única: banco)."""
        return g.USUARIO != 'Sistema local'

    def _atualizar_identidade(self):
        if hasattr(self, 'identidade'):
            self.identidade.config(
                text=f'{g.USUARIO} • {g.PERFIL}' if g.PERFIL else 'Não autenticado')

    def _definir_senha(self, alterar=False):
        # A autenticação é única e vive no banco de dados (tabela usuarios).
        # Aqui só trocamos a senha do usuário logado; se ninguém estiver
        # logado, pedimos para entrar antes.
        if not self._senha_configurada():
            messagebox.showinfo('Segurança', 'Entre com um usuário para alterar a senha.')
            self._login_gestao()
            return
        dlg = tk.Toplevel(self)
        dlg.title(T('alterar_senha'))
        dlg.geometry('400x300')
        dlg.configure(bg=COR['branco'])
        dlg.transient(self)
        _grab_set_safe(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())
        tk.Frame(dlg, bg=COR['verde2'], height=6).pack(fill='x')
        tk.Label(dlg, text=T('alterar_senha'), bg=COR['branco'], fg=COR['verde2'],
                 font=(FONTE, 14, 'bold')).pack(anchor='w', padx=22, pady=(14, 4))
        tk.Label(dlg, text=f"Usuário: {g.USUARIO}", bg=COR['branco'], fg=COR['cinza'],
                 font=(FONTE, 9)).pack(anchor='w', padx=22, pady=(0, 6))

        entradas = {}
        for rotulo in (T('senha_atual'), T('nova_senha'), T('confirmar_senha')):
            tk.Label(dlg, text=rotulo, bg=COR['branco'], fg=COR['cinza'],
                     font=(FONTE, 8, 'bold')).pack(anchor='w', padx=22, pady=(10, 3))
            ent = tk.Entry(dlg, show='*', font=(FONTE, 11), relief='solid', bd=1, bg=COR['branco'])
            ent.pack(fill='x', padx=22, ipady=4)
            ent.focus_set()
            entradas[rotulo] = ent

        erro = tk.Label(dlg, text='', bg=COR['branco'], fg=COR['vermelho'], font=(FONTE, 9))
        erro.pack(anchor='w', padx=22, pady=(6, 0))

        def _salvar():
            atual = entradas[T('senha_atual')].get()
            nova = entradas[T('nova_senha')].get()
            confirma = entradas[T('confirmar_senha')].get()
            if not nova:
                erro.config(text=T('senha_vazia'))
                return
            if nova != confirma:
                erro.config(text=T('senha_divergente'))
                return
            try:
                g.alterar_senha(g.USUARIO, nova, atual)
            except g.ErroGestao as exc:
                erro.config(text=str(exc))
                return
            dlg.destroy()
            self._toast(T('senha_salva'))

        botoes = tk.Frame(dlg, bg=COR['branco'])
        botoes.pack(fill='x', padx=22, pady=(12, 18), side='bottom')
        ttk.Button(botoes, text=T('salvar'), style='Primary.TButton', command=_salvar).pack(side='right')
        ttk.Button(botoes, text=T('cancelar'), style='Secondary.TButton', command=dlg.destroy).pack(side='right', padx=(0, 8))

    def _aplicar_tema(self, tema):
        _aplicar_paleta()
        self.configure(bg=COR['papel'])
        self._style()
        self._recolorir(self)

    def _recolorir(self, widget):
        """Repinta os widgets já criados ao trocar de tema (claro/escuro)."""
        tema = (carregar_config().get('tema') or 'claro')
        if tema == 'escuro':
            origem, destino = _COR_PADRAO, COR_ESCURO
        else:
            origem, destino = COR_ESCURO, _COR_PADRAO
        mapa = {origem[k]: destino[k] for k in origem}
        for w in widget.winfo_children():
            try:
                classe = w.winfo_class()
            except Exception:
                classe = ''
            try:
                bg = str(w.cget('bg'))
            except Exception:
                bg = None
            try:
                fg = str(w.cget('fg'))
            except Exception:
                fg = None
            if bg and bg in mapa:
                try:
                    w.configure(bg=mapa[bg])
                except Exception:
                    pass
            if fg and fg in mapa:
                try:
                    w.configure(fg=mapa[fg])
                except Exception:
                    pass
            if classe == 'Entry':
                try:
                    w.configure(bg=COR['branco'], fg=COR['verde2'],
                                insertbackground=COR['verde2'])
                except Exception:
                    pass
            elif classe == 'Treeview':
                try:
                    w.tag_configure('par', background=COR['branco'])
                    w.tag_configure('impar', background=COR['zebra'])
                    w.tag_configure('zero', foreground=COR['vermelho'], background=COR['vermelhoclaro'])
                    w.tag_configure('baixo', foreground=COR['ambar'], background=COR['amareloclaro'])
                except Exception:
                    pass
            self._recolorir(w)

    def _escolher_idioma(self, codigo):
        definir_idioma(codigo)
        self.title(T('sistema'))
        self._menu()
        self._atualizar_abas_idioma()
        self._atualizar_cabecalhos_idioma()
        self._montar_configuracoes()
        messagebox.showinfo(T('idioma'), T('nota_reiniciar'), parent=self)

    def _atualizar_abas_idioma(self):
        nomes = [
            (self.tab_caixa, T('tab_caixa')), (self.tab_prod, T('tab_produtos')),
            (self.tab_cli, T('tab_clientes')), (self.tab_consumo, T('tab_consumo')),
            (self.tab_perdas, T('tab_perdas')), (self.tab_producao, T('tab_producao')),
            (self.tab_pain, T('tab_painel')), (self.tab_analises, T('tab_analises')),
            (self.tab_hist, T('tab_historico')), (self.tab_estoque, T('tab_estoque')),
            (self.tab_config, T('tab_configuracoes')),
        ]
        for i, (tab, nome) in enumerate(nomes):
            try:
                self.nb.tab(tab, text=f' {nome} ')
            except Exception:
                pass

    def _atualizar_cabecalhos_idioma(self):
        for w in (self.label_caixa, self.label_config):
            if w:
                try:
                    w.config(text=T('caixa_titulo') if w is self.label_caixa else T('config_titulo'))
                except Exception:
                    pass

    def _fechar(self):
        try:
            backup_diario()
            registrar_fiado_recente(30)
        except Exception:
            pass
        try:
            self.balanca.parar()
        except Exception:
            pass
        self.destroy()


def _avisar_instancia_aberta():
    """Avisa (multiplataforma) que o sistema já está aberto em outra janela."""
    import subprocess
    mensagem = 'O Sistema do Mercadinho já está aberto.'
    try:
        if os.name == 'nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, mensagem, 'Mercadinho', 0x40)
            return
        subprocess.Popen(['notify-send', '-a', 'Mercadinho', mensagem])
    except Exception:
        try:
            print(mensagem)
        except Exception:
            pass


def _bloquear_instancia_unica():
    """Garante que só exista uma cópia do sistema aberta (Windows e Linux).

    Duas instâncias acessando o mesmo SQLite fazem as operações travarem
    (espera de lock). Se já houver uma aberta, avisa e encerra esta.
    """
    import sys
    from applock import TravaInstancia, InstanciaJaAberta
    trava = TravaInstancia('mercadinho')
    try:
        trava.adquirir()
    except InstanciaJaAberta:
        _avisar_instancia_aberta()
        sys.exit(0)
    return trava


if __name__ == '__main__':
    _trava_instancia = _bloquear_instancia_unica()
    try:
        App().mainloop()
    finally:
        _trava_instancia.liberar()
