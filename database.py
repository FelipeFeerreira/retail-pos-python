import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'mercadinho.db')
SCHEMA_PATH = os.path.join(BASE_DIR, 'schema.sql')

# Versão do esquema. IMPORTANTE: sempre que uma migração alterar o esquema
# (nova coluna, tabela ou índice), AUMENTE este número. É a comparação
# `versao_gravada < SCHEMA_VERSAO` que dispara o backup pré-migração — se a
# versão não mudar, instalações que já estão nela migram SEM backup.
# Histórico: v1 = migração de gestão inicial; v2 = venda_pagamentos;
# v3 = chave de idempotência em consumo_interno, perdas e producoes;
# v4 = coluna estornado (estorno auditado) em consumo_interno e perdas;
# v5 = custo_conhecido em produtos; finalidade estável em consumo_interno;
#      estornado em producoes (correção de produção);
# v6 = snapshot de estoque/custo anterior para reversão exata de produção.
SCHEMA_VERSAO = 6


def _backup_antes_migracao():
    """Cópia consistente (API do SQLite) antes de migrar um banco existente."""
    from datetime import datetime
    pasta = os.path.join(os.path.dirname(DB_PATH), 'backups')
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, f'antes_migracao_v{SCHEMA_VERSAO}_{datetime.now().strftime("%Y-%m-%d_%H%M%S")}.db')
    origem = sqlite3.connect(DB_PATH)
    copia = sqlite3.connect(destino)
    try:
        origem.backup(copia)
        if copia.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Backup pré-migração não íntegro.')
    finally:
        origem.close()
        copia.close()
    return destino


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 20000')
    conn.create_function('usuario_atual', 0, lambda: getattr(sys.modules.get('gestao'), 'USUARIO', 'Sistema local'))
    return conn


def _colunas(conn, tabela):
    return {row['name'] for row in conn.execute(f'PRAGMA table_info({tabela})').fetchall()}


def init_db():
    existe = os.path.exists(DB_PATH) and os.path.getsize(DB_PATH)
    # Backup pré-migração: só quando já existe banco e a versão gravada é
    # menor que a do código (ou seja, há migração a aplicar). Bancos novos não
    # precisam. Assim as migrações ficam versionadas, repetíveis e reversíveis.
    if existe:
        try:
            origem = sqlite3.connect(DB_PATH)
            try:
                tem_meta = origem.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='schema_meta'").fetchone()
                versao = 0
                if tem_meta:
                    r = origem.execute("SELECT valor FROM schema_meta WHERE chave='versao'").fetchone()
                    versao = int(r[0]) if r else 0
            finally:
                origem.close()
            if versao < SCHEMA_VERSAO:
                _backup_antes_migracao()
        except (sqlite3.DatabaseError, ValueError):
            pass
    conn = get_conn()
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS schema_meta (chave TEXT PRIMARY KEY, valor TEXT NOT NULL)')
        with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
            conn.executescript(f.read())

        # Migração segura para quem já possui o mercadinho.db com vendas antigas.
        vendas_colunas = _colunas(conn, 'vendas')
        if 'cliente_id' not in vendas_colunas:
            conn.execute('ALTER TABLE vendas ADD COLUMN cliente_id INTEGER')
        if 'taxa_paga' not in vendas_colunas:
            conn.execute('ALTER TABLE vendas ADD COLUMN taxa_paga REAL NOT NULL DEFAULT 0')
        if 'voucher_marca' not in vendas_colunas:
            conn.execute('ALTER TABLE vendas ADD COLUMN voucher_marca TEXT')

        conn.execute('''CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            telefone TEXT DEFAULT '',
            documento_tipo TEXT DEFAULT '',
            documento TEXT DEFAULT '',
            endereco TEXT DEFAULT '',
            observacao TEXT DEFAULT '',
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )''')
        # Migração pra quem já tinha "clientes" só com nome/telefone/observação.
        clientes_colunas = _colunas(conn, 'clientes')
        if 'documento_tipo' not in clientes_colunas:
            conn.execute("ALTER TABLE clientes ADD COLUMN documento_tipo TEXT DEFAULT ''")
        if 'documento' not in clientes_colunas:
            conn.execute("ALTER TABLE clientes ADD COLUMN documento TEXT DEFAULT ''")
        if 'endereco' not in clientes_colunas:
            conn.execute("ALTER TABLE clientes ADD COLUMN endereco TEXT DEFAULT ''")
        conn.execute('''CREATE TABLE IF NOT EXISTS pagamentos_fiado (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            valor REAL NOT NULL,
            forma_pagamento TEXT DEFAULT '',
            data_hora TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            observacao TEXT DEFAULT '',
            FOREIGN KEY (cliente_id) REFERENCES clientes(id)
        )''')
        # Migração pra quem já tinha "pagamentos_fiado" sem a forma de pagamento.
        if 'forma_pagamento' not in _colunas(conn, 'pagamentos_fiado'):
            conn.execute("ALTER TABLE pagamentos_fiado ADD COLUMN forma_pagamento TEXT DEFAULT ''")
        conn.execute('CREATE INDEX IF NOT EXISTS idx_vendas_cliente ON vendas(cliente_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_pagamentos_cliente ON pagamentos_fiado(cliente_id)')

        # Consumo interno: o que a própria casa/família tira do estoque (a preço de custo,
        # não é venda) — usado na aba "Consumo interno".
        conn.execute('''CREATE TABLE IF NOT EXISTS consumo_interno (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_hora TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            motivo TEXT DEFAULT '',
            valor_total REAL NOT NULL DEFAULT 0,
            observacao TEXT DEFAULT ''
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS itens_consumo_interno (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            consumo_id INTEGER NOT NULL,
            produto_id INTEGER NOT NULL,
            quantidade REAL NOT NULL,
            preco_custo_unitario REAL NOT NULL,
            subtotal REAL NOT NULL,
            FOREIGN KEY (consumo_id) REFERENCES consumo_interno(id),
            FOREIGN KEY (produto_id) REFERENCES produtos(id)
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_itens_consumo_consumo ON itens_consumo_interno(consumo_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_consumo_data ON consumo_interno(data_hora)')

        # Empréstimo de casco (garrafa retornável): quantidade positiva = cliente pegou
        # casco emprestado (aumenta o quanto ele deve); negativa = cliente devolveu ou
        # deixou casco a mais (diminui a dívida ou vira crédito). Mesmo espírito do
        # saldo_fiado em dinheiro, só que contando cascos em vez de reais.
        conn.execute('''CREATE TABLE IF NOT EXISTS movimentos_casco (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            tipo_casco TEXT NOT NULL DEFAULT 'Coca',
            quantidade INTEGER NOT NULL,
            data_hora TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            observacao TEXT DEFAULT '',
            FOREIGN KEY (cliente_id) REFERENCES clientes(id)
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_casco_cliente ON movimentos_casco(cliente_id)')

        # Produção própria: receita (o que o produto final leva de matéria-prima) e o
        # registro de cada vez que uma produção foi feita, dando baixa nos insumos e
        # entrada no produto final — usado na aba "Produção".
        conn.execute('''CREATE TABLE IF NOT EXISTS receitas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER NOT NULL UNIQUE,
            rendimento REAL NOT NULL DEFAULT 1,
            observacao TEXT DEFAULT '',
            ativo INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (produto_id) REFERENCES produtos(id)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS receita_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receita_id INTEGER NOT NULL,
            insumo_id INTEGER NOT NULL,
            quantidade REAL NOT NULL,
            FOREIGN KEY (receita_id) REFERENCES receitas(id),
            FOREIGN KEY (insumo_id) REFERENCES produtos(id)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS producoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receita_id INTEGER NOT NULL,
            data_hora TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            multiplicador REAL NOT NULL,
            quantidade_produzida REAL NOT NULL,
            custo_total REAL NOT NULL DEFAULT 0,
            custo_unitario REAL NOT NULL DEFAULT 0,
            observacao TEXT DEFAULT '',
            FOREIGN KEY (receita_id) REFERENCES receitas(id)
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_receita_itens_receita ON receita_itens(receita_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_producoes_receita ON producoes(receita_id)')

        # Validade em lotes: o mesmo produto pode ter partes do estoque vencendo em datas
        # diferentes (ex.: 2 unidades no dia 5, 3 unidades no dia 7). quantidade_estoque
        # em produtos continua sendo o total; os lotes são o detalhamento por validade.
        conn.execute('''CREATE TABLE IF NOT EXISTS lotes_validade (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER NOT NULL,
            quantidade REAL NOT NULL,
            data_validade TEXT,
            data_entrada TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            observacao TEXT DEFAULT '',
            FOREIGN KEY (produto_id) REFERENCES produtos(id)
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_lotes_produto ON lotes_validade(produto_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_lotes_validade ON lotes_validade(data_validade)')

        # Perdas: produto que teve que ser jogado fora (venceu, estragou, quebrou) —
        # diferente do consumo interno porque ninguém aproveitou nada, é prejuízo puro.
        conn.execute('''CREATE TABLE IF NOT EXISTS perdas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_hora TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            motivo TEXT NOT NULL DEFAULT 'Outro',
            valor_total REAL NOT NULL DEFAULT 0,
            observacao TEXT DEFAULT ''
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS itens_perda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            perda_id INTEGER NOT NULL,
            produto_id INTEGER NOT NULL,
            quantidade REAL NOT NULL,
            preco_custo_unitario REAL NOT NULL,
            subtotal REAL NOT NULL,
            FOREIGN KEY (perda_id) REFERENCES perdas(id),
            FOREIGN KEY (produto_id) REFERENCES produtos(id)
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_itens_perda_perda ON itens_perda(perda_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_perdas_data ON perdas(data_hora)')
        from gestao import migrar
        migrar(conn)
        conn.execute("INSERT OR REPLACE INTO schema_meta(chave,valor) VALUES('versao',?)", (str(SCHEMA_VERSAO),))
        conn.commit()
    finally:
        conn.close()


# Mantida por compatibilidade com versões antigas.
def seed_demo_data():
    return
