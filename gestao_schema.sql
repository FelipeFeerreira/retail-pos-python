CREATE TABLE IF NOT EXISTS gestao_config (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS auditoria (
 id INTEGER PRIMARY KEY, data_hora TEXT NOT NULL DEFAULT (datetime('now','localtime')),
 usuario TEXT NOT NULL, acao TEXT NOT NULL, entidade TEXT NOT NULL, referencia TEXT, detalhes TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usuarios (
 id INTEGER PRIMARY KEY, nome TEXT NOT NULL UNIQUE, perfil TEXT NOT NULL,
 salt TEXT NOT NULL, senha_hash TEXT NOT NULL, ativo INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS contas_financeiras (
 id INTEGER PRIMARY KEY, nome TEXT NOT NULL UNIQUE, tipo TEXT NOT NULL,
 saldo_inicial_centavos INTEGER NOT NULL DEFAULT 0, conferida INTEGER NOT NULL DEFAULT 0,
 data_base TEXT NOT NULL DEFAULT (date('now','localtime'))
);
CREATE TABLE IF NOT EXISTS movimentos_financeiros (
 id INTEGER PRIMARY KEY, conta_id INTEGER NOT NULL REFERENCES contas_financeiras(id),
 valor_centavos INTEGER NOT NULL CHECK(valor_centavos != 0),
 data TEXT NOT NULL, categoria TEXT NOT NULL, descricao TEXT NOT NULL,
 origem TEXT NOT NULL, referencia TEXT NOT NULL, chave TEXT NOT NULL UNIQUE,
 usuario TEXT NOT NULL, conciliado INTEGER NOT NULL DEFAULT 0,
 estorno_de INTEGER UNIQUE REFERENCES movimentos_financeiros(id)
);
CREATE INDEX IF NOT EXISTS idx_fin_data ON movimentos_financeiros(data);
CREATE TABLE IF NOT EXISTS credores (
 id INTEGER PRIMARY KEY, nome TEXT NOT NULL, documento TEXT NOT NULL DEFAULT '', telefone TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS contas_pagar (
 id INTEGER PRIMARY KEY, credor_id INTEGER NOT NULL REFERENCES credores(id),
 descricao TEXT NOT NULL, categoria TEXT NOT NULL, documento TEXT NOT NULL DEFAULT '',
 valor_centavos INTEGER NOT NULL CHECK(valor_centavos > 0), emissao TEXT NOT NULL,
 vencimento TEXT NOT NULL, competencia TEXT NOT NULL, compra_ref TEXT NOT NULL DEFAULT '',
 cancelada INTEGER NOT NULL DEFAULT 0, usuario TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pagamentos_contas (
 id INTEGER PRIMARY KEY, titulo_id INTEGER NOT NULL REFERENCES contas_pagar(id),
 principal_centavos INTEGER NOT NULL CHECK(principal_centavos > 0),
 encargos_centavos INTEGER NOT NULL DEFAULT 0, desconto_centavos INTEGER NOT NULL DEFAULT 0,
 data TEXT NOT NULL, metodo TEXT NOT NULL, comprovante TEXT NOT NULL DEFAULT '',
 movimento_id INTEGER REFERENCES movimentos_financeiros(id), chave TEXT NOT NULL UNIQUE,
 estornado INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS titulos_receber (
 id INTEGER PRIMARY KEY, venda_id INTEGER NOT NULL UNIQUE REFERENCES vendas(id),
 cliente_id INTEGER NOT NULL REFERENCES clientes(id), valor_centavos INTEGER NOT NULL,
 recebido_centavos INTEGER NOT NULL DEFAULT 0, vencimento TEXT,
 juros_dia REAL NOT NULL DEFAULT 0, multa_dia REAL NOT NULL DEFAULT 0,
 legado INTEGER NOT NULL DEFAULT 0, cancelado INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS recebimentos_titulos (
 id INTEGER PRIMARY KEY, titulo_id INTEGER NOT NULL REFERENCES titulos_receber(id),
 pagamento_id INTEGER NOT NULL REFERENCES pagamentos_fiado(id),
 principal_centavos INTEGER NOT NULL, encargos_centavos INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS recebiveis_cartao (
 id INTEGER PRIMARY KEY, origem TEXT NOT NULL, referencia TEXT NOT NULL,
 bruto_centavos INTEGER NOT NULL, taxa_centavos INTEGER NOT NULL DEFAULT 0,
 previsto TEXT NOT NULL, liquidado TEXT, movimento_id INTEGER REFERENCES movimentos_financeiros(id)
);
CREATE TABLE IF NOT EXISTS sessoes_caixa (
 id INTEGER PRIMARY KEY, abertura TEXT NOT NULL DEFAULT (datetime('now','localtime')),
 fechamento TEXT, usuario TEXT NOT NULL, inicial_centavos INTEGER NOT NULL,
 contado_centavos INTEGER, esperado_centavos INTEGER, justificativa TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS caixa_unico_aberto ON sessoes_caixa((1)) WHERE fechamento IS NULL;
CREATE TABLE IF NOT EXISTS historico_precos (
 id INTEGER PRIMARY KEY, produto_id INTEGER NOT NULL REFERENCES produtos(id),
 anterior REAL NOT NULL, novo REAL NOT NULL,
 data_hora TEXT NOT NULL DEFAULT (datetime('now','localtime')), usuario TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS baixas_lotes (
 id INTEGER PRIMARY KEY, lote_id INTEGER NOT NULL REFERENCES lotes_validade(id),
 quantidade REAL NOT NULL, origem TEXT NOT NULL, referencia TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inventarios (
 id INTEGER PRIMARY KEY, produto_id INTEGER NOT NULL REFERENCES produtos(id),
 antes REAL NOT NULL, contado REAL NOT NULL, motivo TEXT NOT NULL,
 data_hora TEXT NOT NULL DEFAULT (datetime('now','localtime')), usuario TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orcamentos (
 mes TEXT NOT NULL, categoria TEXT NOT NULL, valor_centavos INTEGER NOT NULL,
 PRIMARY KEY(mes,categoria)
);
CREATE TABLE IF NOT EXISTS extrato_bancario (
 id INTEGER PRIMARY KEY, conta_id INTEGER NOT NULL REFERENCES contas_financeiras(id),
 data TEXT NOT NULL, descricao TEXT NOT NULL, valor_centavos INTEGER NOT NULL,
 identificador TEXT NOT NULL, movimento_id INTEGER UNIQUE REFERENCES movimentos_financeiros(id),
 UNIQUE(conta_id,identificador)
);
CREATE TABLE IF NOT EXISTS promocoes (
 id INTEGER PRIMARY KEY, produto_id INTEGER NOT NULL REFERENCES produtos(id),
 inicio TEXT NOT NULL, fim TEXT NOT NULL, preco REAL NOT NULL CHECK(preco >= 0)
);
CREATE TABLE IF NOT EXISTS insumos_producao (
 id INTEGER PRIMARY KEY, producao_id INTEGER NOT NULL REFERENCES producoes(id),
 produto_id INTEGER NOT NULL REFERENCES produtos(id), nome TEXT NOT NULL, unidade TEXT NOT NULL,
 quantidade REAL NOT NULL, custo_unitario REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS compras_estoque (
 id INTEGER PRIMARY KEY, documento TEXT NOT NULL, fornecedor TEXT NOT NULL,
 data TEXT NOT NULL, valor_centavos INTEGER NOT NULL, titulo_id INTEGER REFERENCES contas_pagar(id),
 usuario TEXT NOT NULL, chave TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS itens_compra (
 id INTEGER PRIMARY KEY, compra_id INTEGER NOT NULL REFERENCES compras_estoque(id),
 produto_id INTEGER NOT NULL REFERENCES produtos(id), quantidade REAL NOT NULL,
 custo_unitario REAL NOT NULL, validade TEXT
);
-- Detalhamento do pagamento dividido (venda com mais de uma forma): guarda
-- cada parte para o recibo e o histórico mostrarem como foi realmente pago.
CREATE TABLE IF NOT EXISTS venda_pagamentos (
 id INTEGER PRIMARY KEY, venda_id INTEGER NOT NULL REFERENCES vendas(id),
 forma TEXT NOT NULL, valor_centavos INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_venda_pagamentos ON venda_pagamentos(venda_id);
