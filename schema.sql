-- Banco do Sistema do Mercadinho
CREATE TABLE IF NOT EXISTS produtos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_barras TEXT UNIQUE,
    nome TEXT NOT NULL,
    categoria TEXT,
    unidade TEXT NOT NULL DEFAULT 'UN' CHECK (unidade IN ('UN', 'KG')),
    preco_custo REAL NOT NULL DEFAULT 0,
    preco_venda REAL NOT NULL,
    quantidade_estoque REAL NOT NULL DEFAULT 0,
    estoque_minimo REAL NOT NULL DEFAULT 5,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    telefone TEXT DEFAULT '',
    documento_tipo TEXT DEFAULT '',
    documento TEXT DEFAULT '',
    endereco TEXT DEFAULT '',
    observacao TEXT DEFAULT '',
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS vendas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    valor_total REAL NOT NULL,
    desconto REAL NOT NULL DEFAULT 0,
    forma_pagamento TEXT NOT NULL,
    cliente_id INTEGER,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS itens_venda (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venda_id INTEGER NOT NULL,
    produto_id INTEGER NOT NULL,
    quantidade REAL NOT NULL,
    preco_unitario REAL NOT NULL,
    FOREIGN KEY (venda_id) REFERENCES vendas(id),
    FOREIGN KEY (produto_id) REFERENCES produtos(id)
);

CREATE TABLE IF NOT EXISTS movimentacoes_estoque (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    produto_id INTEGER NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('entrada', 'saida', 'ajuste')),
    quantidade REAL NOT NULL,
    data_hora TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    observacao TEXT,
    FOREIGN KEY (produto_id) REFERENCES produtos(id)
);

CREATE TABLE IF NOT EXISTS pagamentos_fiado (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL,
    valor REAL NOT NULL,
    forma_pagamento TEXT DEFAULT '',
    data_hora TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    observacao TEXT DEFAULT '',
    FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

-- Consumo interno: o que a própria casa/família tira do estoque (a preço de custo).
CREATE TABLE IF NOT EXISTS consumo_interno (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    motivo TEXT DEFAULT '',
    valor_total REAL NOT NULL DEFAULT 0,
    observacao TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS itens_consumo_interno (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consumo_id INTEGER NOT NULL,
    produto_id INTEGER NOT NULL,
    quantidade REAL NOT NULL,
    preco_custo_unitario REAL NOT NULL,
    subtotal REAL NOT NULL,
    FOREIGN KEY (consumo_id) REFERENCES consumo_interno(id),
    FOREIGN KEY (produto_id) REFERENCES produtos(id)
);

-- Empréstimo de casco (garrafa retornável): positivo = cliente pegou emprestado,
-- negativo = cliente devolveu ou deixou a mais.
CREATE TABLE IF NOT EXISTS movimentos_casco (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL,
    tipo_casco TEXT NOT NULL DEFAULT 'Coca',
    quantidade INTEGER NOT NULL,
    data_hora TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    observacao TEXT DEFAULT '',
    FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

-- Produção própria: receita (matéria-prima do produto final) e cada produção feita.
CREATE TABLE IF NOT EXISTS receitas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    produto_id INTEGER NOT NULL UNIQUE,
    rendimento REAL NOT NULL DEFAULT 1,
    observacao TEXT DEFAULT '',
    ativo INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (produto_id) REFERENCES produtos(id)
);

CREATE TABLE IF NOT EXISTS receita_itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receita_id INTEGER NOT NULL,
    insumo_id INTEGER NOT NULL,
    quantidade REAL NOT NULL,
    FOREIGN KEY (receita_id) REFERENCES receitas(id),
    FOREIGN KEY (insumo_id) REFERENCES produtos(id)
);

CREATE TABLE IF NOT EXISTS producoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receita_id INTEGER NOT NULL,
    data_hora TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    multiplicador REAL NOT NULL,
    quantidade_produzida REAL NOT NULL,
    custo_total REAL NOT NULL DEFAULT 0,
    custo_unitario REAL NOT NULL DEFAULT 0,
    observacao TEXT DEFAULT '',
    FOREIGN KEY (receita_id) REFERENCES receitas(id)
);

-- Validade em lotes: o mesmo produto pode ter partes vencendo em datas diferentes.
CREATE TABLE IF NOT EXISTS lotes_validade (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    produto_id INTEGER NOT NULL,
    quantidade REAL NOT NULL,
    data_validade TEXT,
    data_entrada TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    observacao TEXT DEFAULT '',
    FOREIGN KEY (produto_id) REFERENCES produtos(id)
);

-- Perdas: produto jogado fora (venceu, estragou, quebrou) — prejuízo puro, ninguém aproveitou.
CREATE TABLE IF NOT EXISTS perdas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    motivo TEXT NOT NULL DEFAULT 'Outro',
    valor_total REAL NOT NULL DEFAULT 0,
    observacao TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS itens_perda (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    perda_id INTEGER NOT NULL,
    produto_id INTEGER NOT NULL,
    quantidade REAL NOT NULL,
    preco_custo_unitario REAL NOT NULL,
    subtotal REAL NOT NULL,
    FOREIGN KEY (perda_id) REFERENCES perdas(id),
    FOREIGN KEY (produto_id) REFERENCES produtos(id)
);

CREATE INDEX IF NOT EXISTS idx_produtos_codigo ON produtos(codigo_barras);
CREATE INDEX IF NOT EXISTS idx_produtos_nome ON produtos(nome);
CREATE INDEX IF NOT EXISTS idx_vendas_data ON vendas(data_hora);
-- idx_vendas_cliente é criado pelo database.py depois da migração de bancos antigos.
CREATE INDEX IF NOT EXISTS idx_itens_venda_venda ON itens_venda(venda_id);
CREATE INDEX IF NOT EXISTS idx_mov_produto ON movimentacoes_estoque(produto_id);
CREATE INDEX IF NOT EXISTS idx_pagamentos_cliente ON pagamentos_fiado(cliente_id);
CREATE INDEX IF NOT EXISTS idx_itens_consumo_consumo ON itens_consumo_interno(consumo_id);
CREATE INDEX IF NOT EXISTS idx_consumo_data ON consumo_interno(data_hora);
CREATE INDEX IF NOT EXISTS idx_casco_cliente ON movimentos_casco(cliente_id);
CREATE INDEX IF NOT EXISTS idx_receita_itens_receita ON receita_itens(receita_id);
CREATE INDEX IF NOT EXISTS idx_producoes_receita ON producoes(receita_id);
CREATE INDEX IF NOT EXISTS idx_lotes_produto ON lotes_validade(produto_id);
CREATE INDEX IF NOT EXISTS idx_lotes_validade ON lotes_validade(data_validade);
CREATE INDEX IF NOT EXISTS idx_itens_perda_perda ON itens_perda(perda_id);
CREATE INDEX IF NOT EXISTS idx_perdas_data ON perdas(data_hora);
