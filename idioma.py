"""Idioma do sistema: português (padrão) e inglês.

O idioma fica salvo em config.json (chave "idioma": "pt" ou "en").
Use T('chave') em qualquer lugar do app para obter o texto traduzido.
"""

from impressora import carregar_config, salvar_config

_idioma_atual = None


def idioma_atual():
    global _idioma_atual
    if _idioma_atual is None:
        conf = carregar_config()
        _idioma_atual = (conf.get('idioma') or 'pt').lower()
        if _idioma_atual not in ('pt', 'en'):
            _idioma_atual = 'pt'
    return _idioma_atual


def definir_idioma(codigo):
    global _idioma_atual
    _idioma_atual = ('pt' if codigo != 'en' else 'en')
    salvar_config({'idioma': _idioma_atual})
    return _idioma_atual


_PT = {
    'sistema': 'Sistema do Mercadinho',
    'arquivo': 'Arquivo',
    'ajuda': 'Ajuda',
    'sair': 'Sair',
    'backup_agora': 'Backup agora',
    'configurar_impressora': 'Configurar impressora',
    'configurar_balanca': 'Configurar balança',
    'abrir_tela_cliente': 'Abrir tela do cliente',
    'gerar_catalogo': 'Gerar catálogo atualizado (.xlsx)',
    'gerar_planilha_entrada': 'Gerar planilha de entrada de mercadoria (.xlsx)',
    'importar_entrada': 'Importar entrada de mercadoria (.xlsx)',
    'importar_nfe': 'Importar nota fiscal do fornecedor (NF-e / XML)',
    'revisar_categorias': 'Revisar categorias dos produtos',
    'exportar_relatorio': 'Exportar relatório de análises (.xlsx)',
    'atalhos_do_teclado': 'Atalhos do teclado (F1)',
    'alterar_senha_menu': 'Alterar senha de acesso',
    'tab_caixa': 'Caixa',
    'tab_produtos': 'Produtos',
    'tab_clientes': 'Clientes',
    'tab_consumo': 'Consumo interno',
    'tab_perdas': 'Perdas',
    'tab_producao': 'Produção',
    'tab_painel': 'Painel',
    'tab_analises': 'Análises',
    'tab_historico': 'Histórico',
    'tab_estoque': 'Estoque/Validades',
    'tab_configuracoes': 'Configurações',
    'filtro_todos': 'Todos',
    'filtro_vencidos': 'Vencidos',
    'filtro_proximos': 'Vencendo (7d)',
    'filtro_sem_data': 'Sem validade',
    'btn_atualizar': 'Atualizar',
    'btn_adicionar_lote': '+ Lote',
    'btn_editar_lote': 'Editar lote',
    'btn_registrar_perda': 'Registrar perda',
    'btn_remover_lote': 'Remover lote',
    'btn_ajustar_estoque': 'Ajustar estoque total',
    'mercadinho': 'Mercadinho',
    'status_sqlite': 'SQLite · backup automático',
    'status_f1': 'F1 = Atalhos',
    'titulo_login': 'Login de acesso',
    'senha': 'Senha',
    'entrar': 'Entrar',
    'cancelar': 'Cancelar',
    'senha_incorreta': 'Senha incorreta. Tente novamente.',
    'senha_incorreta_encerrar': 'Senha incorreta muitas vezes. O programa será encerrado.',
    'senha_dica': 'Para redefinir a senha, apague a chave "senha_hash" do arquivo config.json.',
    'definir_senha': 'Definir senha de acesso',
    'definir_senha_btn': 'Definir senha',
    'alterar_senha': 'Alterar senha de acesso',
    'nova_senha': 'Nova senha',
    'confirmar_senha': 'Confirmar senha',
    'senha_atual': 'Senha atual',
    'senha_vazia': 'A senha não pode ficar vazia.',
    'senha_divergente': 'As senhas informadas são diferentes.',
    'senha_atual_errada': 'A senha atual está incorreta.',
    'senha_salva': 'Senha de acesso definida.',
    'apar_idioma': 'Aparência e idioma',
    'tema': 'Tema',
    'tema_claro': 'Tema claro',
    'tema_escuro': 'Tema escuro',
    'idioma': 'Idioma',
    'portugues': 'Português',
    'ingles': 'English',
    'nota_reiniciar': 'Algumas telas serão atualizadas quando o programa abrir novamente.',
    'preferencias_salvas': 'Preferências salvas',
    'seguranca': 'Segurança',
    'dica_sem_senha': 'O sistema abre sem pedir senha. Defina uma para exigir login ao iniciar.',
    'dica_com_senha': 'A senha é exigida ao abrir o sistema. Altere quando quiser.',
    'salvar': 'Salvar',
    'fechar': 'Fechar',
    'caixa_titulo': 'Caixa',
    'buscar_bipar': 'BUSCAR / BIPAR CÓDIGO DE BARRAS',
    'tela_do_cliente': 'Tela do cliente',
    'imprimir_ultimo_cupom': 'Imprimir último cupom (Ctrl+P)',
    'finalizar': 'FINALIZAR (F12)',
    'config_titulo': 'Configurações',
    'taxas_maquininha': 'Taxas da maquininha',
    'salvar_taxas': 'Salvar taxas',
    'vouchers_aceitos': 'Vouchers aceitos',
    'adicionar_voucher': '+ Adicionar voucher',
    'nenhum_voucher': 'Nenhum voucher cadastrado ainda.',
    'login': 'Entre com a senha para acessar o sistema.',
    'administrador': 'Acesso ao sistema',
    'feche': 'Feche para sair',
    'vender_sem_estoque': 'Permitir vender sem estoque (estoque pode ficar negativo)',
    'vender_sem_estoque_dica': 'Quando marcado, a venda não é bloqueada por falta de estoque ou validade.',
}

_EN = {
    'sistema': 'Convenience Store System',
    'arquivo': 'File',
    'ajuda': 'Help',
    'sair': 'Exit',
    'backup_agora': 'Back up now',
    'configurar_impressora': 'Configure thermal printer',
    'configurar_balanca': 'Configure scale',
    'abrir_tela_cliente': 'Open customer screen',
    'gerar_catalogo': 'Generate catalog (.xlsx)',
    'gerar_planilha_entrada': 'Generate merchandise intake sheet (.xlsx)',
    'importar_entrada': 'Import merchandise intake (.xlsx)',
    'importar_nfe': 'Import supplier invoice (NF-e / XML)',
    'revisar_categorias': 'Review product categories',
    'exportar_relatorio': 'Export analytics report (.xlsx)',
    'atalhos_do_teclado': 'Keyboard shortcuts (F1)',
    'alterar_senha_menu': 'Change access password',
    'tab_caixa': 'Point of Sale',
    'tab_produtos': 'Products',
    'tab_clientes': 'Customers',
    'tab_consumo': 'Internal use',
    'tab_perdas': 'Losses',
    'tab_producao': 'Production',
    'tab_painel': 'Dashboard',
    'tab_analises': 'Analytics',
    'tab_historico': 'History',
    'tab_estoque': 'Stock/Expiry',
    'tab_configuracoes': 'Settings',
    'filtro_todos': 'All',
    'filtro_vencidos': 'Expired',
    'filtro_proximos': 'Expiring (7d)',
    'filtro_sem_data': 'No expiry',
    'btn_atualizar': 'Refresh',
    'btn_adicionar_lote': '+ Lot',
    'btn_editar_lote': 'Edit lot',
    'btn_registrar_perda': 'Record loss',
    'btn_remover_lote': 'Remove lot',
    'btn_ajustar_estoque': 'Adjust total stock',
    'mercadinho': 'Store',
    'status_sqlite': 'SQLite · automatic backup',
    'status_f1': 'F1 = Shortcuts',
    'titulo_login': 'Access login',
    'senha': 'Password',
    'entrar': 'Sign in',
    'cancelar': 'Cancel',
    'senha_incorreta': 'Wrong password. Try again.',
    'senha_incorreta_encerrar': 'Too many wrong passwords. The program will close.',
    'senha_dica': 'To reset the password, remove the "senha_hash" key from config.json.',
    'definir_senha': 'Set access password',
    'definir_senha_btn': 'Set password',
    'alterar_senha': 'Change access password',
    'nova_senha': 'New password',
    'confirmar_senha': 'Confirm password',
    'senha_atual': 'Current password',
    'senha_vazia': 'The password cannot be empty.',
    'senha_divergente': 'The passwords do not match.',
    'senha_atual_errada': 'The current password is incorrect.',
    'senha_salva': 'Access password set.',
    'apar_idioma': 'Appearance & language',
    'tema': 'Theme',
    'tema_claro': 'Light theme',
    'tema_escuro': 'Dark theme',
    'idioma': 'Language',
    'portugues': 'Português',
    'ingles': 'English',
    'nota_reiniciar': 'Some screens will update the next time the program opens.',
    'preferencias_salvas': 'Preferences saved',
    'seguranca': 'Security',
    'dica_sem_senha': 'The system opens without asking for a password. Set one to require login on startup.',
    'dica_com_senha': 'The password is required when opening the system. Change it anytime.',
    'salvar': 'Save',
    'fechar': 'Close',
    'caixa_titulo': 'Checkout',
    'buscar_bipar': 'SEARCH / SCAN BARCODE',
    'tela_do_cliente': 'Customer screen',
    'imprimir_ultimo_cupom': 'Reprint last receipt (Ctrl+P)',
    'finalizar': 'CHECKOUT (F12)',
    'config_titulo': 'Settings',
    'taxas_maquininha': 'Card machine fees',
    'salvar_taxas': 'Save fees',
    'vouchers_aceitos': 'Accepted vouchers',
    'adicionar_voucher': '+ Add voucher',
    'nenhum_voucher': 'No vouchers registered yet.',
    'login': 'Enter the password to access the system.',
    'administrador': 'System access',
    'feche': 'Close to exit',
    'vender_sem_estoque': 'Allow selling without stock (stock can go negative)',
    'vender_sem_estoque_dica': 'When enabled, sales are not blocked by lack of stock or expiry.',
}


def T(chave):
    """Retorna o texto traduzido para a chave informada (pt ou en)."""
    tabela = _EN if idioma_atual() == 'en' else _PT
    return tabela.get(chave, chave)


def traduzir_texto(texto):
    """Traduz strings diretas (não-chaves) usadas nas telas principais."""
    if idioma_atual() != 'en':
        return texto
    mapa = {v: k for k, v in _PT.items()}
    chave = mapa.get(texto.strip())
    if chave and chave in _EN:
        return _EN[chave]
    return texto