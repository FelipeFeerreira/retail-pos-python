# Retail POS — Python Desktop

A desktop retail-management application built with **Python, Tkinter and SQLite**. It combines checkout and inventory operations with customer credit, purchasing and financial management. The user interface is primarily in Brazilian Portuguese.

## Features

- Product catalog, checkout, stock movements and customer accounts.
- Cash-session opening/closing, accounts payable/receivable and financial summaries.
- Customer credit policies, partial payments and repayment receipts.
- Expiration batches, first-expiring-first-out consumption, waste tracking and production recipes.
- Spreadsheet imports and reports, local backups, serial-scale and Windows receipt-printer integration.
- First-run manager registration and regression tests that use temporary databases.

## Duas interfaces (transição)

- **Interface reformulada (nova) — `app_reformulado.py`**: navegação por áreas
  (Início, Vendas, Clientes, Produtos e estoque, Compras, Operacional,
  Financeiro, Resultados, Diagnóstico, Administração), organizada em
  `reformulacao/` (`tema`, `componentes`, `paginas`, `shell`). Usa o **mesmo
  banco e os mesmos serviços**. É a entrada principal da nova versão.
  Operacional tem abas Consumo/Perdas/Produção/Receitas. Veja a
  [matriz de funcionalidades](docs/MATRIZ_FUNCIONALIDADES.md).
- **Interface antiga — `app.py`**: continua disponível durante a transição.

As duas **não podem rodar juntas** no mesmo banco (a trava de instância única
impede). O banco e as regras são os mesmos; migrações são compartilhadas.

```bash
# nova interface
.venv/bin/python app_reformulado.py
# interface antiga (transição)
.venv/bin/python app.py
```

## Run locally

Requires Python 3.13 with Tkinter support. `pywin32` (Windows printer integration) is marked Windows-only in `requirements.txt`, so the same file installs cleanly on Linux/macOS too.

### Windows

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
# or just double-click / run:
Mercadinho.bat
```

### Linux / macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
# or just run the launcher (it finds the project folder and the venv itself):
./Mercadinho.sh
```

The application initializes its SQLite database on first run. On the first launch you register the manager account (there is no default password); after that, every protected operation requires an authenticated user. This repository intentionally contains no live database, store configuration, customer records or backups.

## Security and data safety

- **Authentication:** profiles live in the database (`usuarios`) with PBKDF2-hashed passwords. Until someone signs in, no profile is active and no protected operation is allowed. The first user must be a manager; afterwards, creating users and destructive actions require the `configurar` permission. Use **Sair (bloquear)** to end a session.
- **Backups:** daily backups use SQLite's consistent backup API (never a raw file copy) and pass an integrity check. Retention is configurable via `backup_retencao_dias` in `config.json` (default 30). A full backup is taken automatically before any restore.
- **NF-e import:** the app never fabricates expiration dates or payment terms. When the invoice does not carry the due date, payment condition or the expiration of perishables, the preview asks for them explicitly and blocks the import until they are provided. Duplicate invoices are detected and ignored, and a failed import does not leave orphan product registrations.
- **Single instance:** a cross-platform lock (Windows `msvcrt` / Unix `flock`) prevents two copies from opening the same SQLite file.

## Roteiro do operador

**1. Compra e entrada de mercadoria**
- **Arquivo → Importar nota fiscal (NF-e)** para nota de fornecedor, ou **Receber mercadoria** (Ferramentas) para digitar. Ambos fazem prévia, pedem confirmação e fazem backup antes de gravar. A mercadoria entra no **estoque** e o valor vira **conta a pagar** (categoria "Mercadoria para revenda") — não é despesa: o custo só é reconhecido quando vender/consumir/perder (CMV).

**2. Consumo interno** (uso operacional/equipe — sai pelo preço de custo, não é venda):
1. Aba **Consumo interno** → busque o produto por nome/código e informe a quantidade (aceita vírgula).
2. Escolha a **Finalidade** (código estável: Operacional / Equipe / Pessoal‑família / Outro) e, se quiser, escreva um **Motivo** livre (não classifica nada).
3. **Registrar consumo**. A tela mostra a **prévia do custo**; se o custo for desconhecido, avisa e marca o total como parcial. Falta de estoque mostra a causa (registre entrada/inventário primeiro).

**3. Retirada familiar** — mesma tela do consumo, motivo **"Consumo pessoal/família"**. Entra como **retirada** (não é despesa operacional) e aparece separada no resultado.

**4. Perda** (venceu, estragou, quebrou — prejuízo puro):
1. Aba **Perdas** → adicione o produto e a quantidade. Se o item tiver lotes, **escolha o lote perdido** (ou use o atalho **"Registrar perda"** na aba Lotes e validade).
2. Informe o **motivo** e confirme. Lote vencido pode ser baixado como perda (com motivo); para consumo/produção/venda, lote vencido é **bloqueado** mesmo havendo outro lote válido.

**5. Produção** (transforma insumos em um produto que entra no estoque):
1. Cadastre a **receita** (produto final, rendimento e insumos) — selecione cada insumo e produto final na lista de sugestões (nome + unidade + código).
2. **Registrar produção** → a tela mostra a **prévia** (insumos necessários × disponíveis, custo, rendimento previsto/real, validade). Informe quantas vezes fez a receita, o rendimento real e a validade.
3. Tudo é gravado numa **única transação**: se faltar um insumo, nada é alterado. O custo dos insumos vira o custo do produto final **uma única vez** (não é lançado também como consumo). Duplo clique não gera duas produções.
4. **Correção:** no detalhe da produção, **Estornar produção** devolve os insumos e remove o produto acabado — mas **só** se o produto ainda não foi vendido/consumido/perdido depois (o sistema detecta e bloqueia).

**6. Conta da loja e pagamento**
- **Financeiro → Contas a pagar → Nova conta**: credor, descrição, categoria (aluguel, energia, água, internet, salários, manutenção, serviços...), valor, **competência** (mês em que conta no resultado), vencimento e documento.
- **Registrar pagamento**: escolha a conta financeira e o valor (aceita pagamento parcial). A despesa conta no **resultado pela competência** (valor cheio) e no **caixa quando é paga** — pagamento parcial não duplica a despesa.
- Mercadoria para revenda e Investimento **não** são despesa operacional. Aportes, retiradas e transferências **não** são receita nem despesa.

**7. Consulta do resultado e do saldo financeiro**
- **Financeiro → DRE gerencial**: painel por competência com filtro **Hoje / 7 / 30 dias / período personalizado** (campos de data no topo). Estrutura:

  ```
  Vendas líquidas de descontos e cancelamentos
  − CMV histórico das mercadorias vendidas
  = Margem bruta
  − taxas de cartão e outros meios
  − perdas (a preço de custo)
  − consumo operacional
  − consumo da equipe
  − consumo a classificar
  − despesas da loja por competência
  + outras receitas  − outras despesas
  = RESULTADO LÍQUIDO GERENCIAL
  − retiradas pessoais/familiares (a preço de custo)
  = RESULTADO APÓS RETIRADAS PESSOAIS/FAMILIARES
  ```

  Selecione uma linha e clique em **Ver lançamentos** (ou dê duplo clique) para abrir os registros que compõem o valor. Se faltar custo em algum item, o painel avisa **"RESULTADO PARCIAL"** e lista as pendências.
- Ao lado, o bloco **"Caixa não é lucro"**: dinheiro em caixa, saldo bancário registrado, cartão a receber, fiado a receber, contas a pagar em aberto e o fluxo efetivo do período. Fiado é resultado da venda, mas não é dinheiro recebido; o recebimento depois não é uma segunda venda.

**Estorno de consumo/perda:** no histórico de **Consumo interno** ou **Perdas**, abra o lançamento (duplo clique) e use **Estornar lançamento** com o motivo. O original é preservado (marcado como estornado), o estoque e os lotes voltam e o indicador é corrigido. Estorno duplicado é bloqueado.

**Saneamento de estoque negativo** (conferência, sem inventar custo):
- Estoque negativo é erro de registro. Ao repor (compra, produção ou ajuste), o **custo médio** só é ponderado quando o saldo anterior é positivo; com saldo negativo/zero, assume o **custo da própria entrada** — nunca divide por zero nem inventa custo.
- Faça **inventário** (Produtos → Inventário) para acertar o saldo físico antes de operar. O banco **não é saneado automaticamente**.

**Custo desconhecido:** quando o produto está sem preço de custo (≤ 0), as telas de consumo, perdas e produção mostram "custo desconhecido" em vez de R$ 0,00, e o total fica marcado como parcial — para não confundir desconhecido com custo zero.

**Idempotência:** consumo, perdas e produção gravam uma chave única. Duplo clique ou reenvio da mesma tentativa não gera dois lançamentos (inclui o consumo por Ferramentas e a perda pela aba Lotes).

## Migrações

O esquema é versionado (`schema_meta.versao` em `database.py`, constante `SCHEMA_VERSAO`). Ao abrir o app, se o banco estiver numa versão anterior, é criado um **backup pré-migração** consistente (`backups/antes_migracao_v<versão>_<data>.db`) antes de aplicar colunas/tabelas/índices — a migração é aditiva e repetível. **Ao alterar o esquema, aumente `SCHEMA_VERSAO`**, senão bancos já na versão atual migram sem backup.

## Balança Toledo 8217 (Prix)

Configuração em **Arquivo → Configurar balança**. O app já fala os protocolos da 8217 (P05A, P05B, P05, P06).

1. Na balança, programe o protocolo **P05A** (parâmetro `C09`) e escolha o **baud rate** (parâmetro `C10`; padrão de fábrica **2400**).
2. No app, selecione a porta, o protocolo, o **mesmo baud rate** e a paridade (normalmente **Nenhuma**).
3. Clique em **Testar conexão**: coloque um peso na balança e confira o "Peso: X kg" que aparece. Se não vier peso, o campo **Bytes recebidos** mostra o que está chegando (ajuda a achar baud/paridade corretos). Salve.

Portas seriais:
- **Windows:** `COM3`, `COM4`, ... (aparecem na lista automaticamente).
- **Linux:** normalmente `/dev/ttyUSB0` (conversor USB) ou `/dev/ttyS0` (serial nativa). Se der erro de permissão, adicione o usuário ao grupo: `sudo usermod -aG dialout $USER` (relogar depois).

O protocolo P05A manda o peso como 5 dígitos sem ponto (`15000` = 15,000 kg); P05B/P06 mandam com ponto (`00.185`). Pesos instáveis (`IIIII`), negativos (`NNNNN`) e de sobrecarga (`SSSSS`) são ignorados. A leitura roda em segundo plano e não trava o caixa; na tela de venda, ao adicionar um produto por KG, o peso da balança é usado automaticamente quando disponível.

> A integração foi validada por testes automatizados do parser e do diálogo, mas **não foi verificada fisicamente** com a balança conectada — a conferência final depende do equipamento e do cabo.

## Verification

```bash
# Windows
.venv\Scripts\python.exe -m unittest test_gestao test_correcoes -v
.venv\Scripts\python.exe test_producao_ui.py
.venv\Scripts\python.exe test_operacional_ui.py
.venv\Scripts\python.exe test_interface.py

# Linux / macOS
.venv/bin/python -m unittest test_gestao test_correcoes -v
.venv/bin/python test_producao_ui.py
.venv/bin/python test_operacional_ui.py
.venv/bin/python test_interface.py
```

The regression suite redirects database operations to temporary files. The interface smoke test requires a desktop session and disables scale/printer activity. Do not use its optional live-store flags for a portfolio demo. See [verification notes](docs/PORTFOLIO_VALIDATION.md).

## Code map

| Module | Responsibility |
| --- | --- |
| `app_reformulado.py`, `reformulacao/` | Nova interface (shell, páginas, componentes, tema) |
| `app.py`, `gestao_ui.py` | Interface antiga (transição) e telas de gestão |
| `database.py`, `schema.sql`, `gestao_schema.sql` | Persistence and schema initialization |
| `operacoes.py`, `gestao.py` | Retail operations and finance rules |
| `producao.py`, `validade.py` | Recipes, production and expiration batches |
| `balanca.py`, `impressora.py` | Hardware integration |
| `applock.py` | Cross-platform single-instance lock |
| `backup.py` | Consistent SQLite backups, retention and restore |
| `importar_nfe.py`, `importar_entrada.py`, `importar_planilha.py` | Supplier invoice and spreadsheet imports with safe preview |
| `test_gestao.py`, `test_correcoes.py` | Regression, security, import, backup and migration tests |
| `test_producao_ui.py`, `test_operacional_ui.py`, `test_interface.py` | GUI tests (recipe selection, loss flow) and interface smoke test |

## Limitations

This portfolio snapshot is intended for local demonstrations. Physical peripherals were not validated during publication. It does not provide fiscal certification or direct payment processing. The [Java/React version](https://github.com/FelipeFeerreira/retail-pos-java) explores a separate web-based implementation.
