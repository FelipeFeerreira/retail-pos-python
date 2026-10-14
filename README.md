# Retail POS — Python Desktop

A desktop retail-management application built with **Python, Tkinter and SQLite**. It combines checkout and inventory operations with customer credit, purchasing and financial management. The user interface is primarily in Brazilian Portuguese.

## Features

- Product catalog, checkout, stock movements and customer accounts.
- Cash-session opening/closing, accounts payable/receivable and financial summaries.
- Customer credit policies, partial payments and repayment receipts.
- Expiration batches, first-expiring-first-out consumption, waste tracking and production recipes.
- Spreadsheet imports and reports, local backups, serial-scale and Windows receipt-printer integration.
- First-run manager registration and regression tests that use temporary databases.

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

## Roteiro do operador — consumo, perdas e produção

**Consumo interno** (o que a própria casa/equipe usa, sai pelo preço de custo, não é venda):
1. Aba **Consumo interno** → busque o produto por nome/código e informe a quantidade.
2. Confira a lista e escolha o **motivo** (limpeza, equipe, pessoal/família, operacional).
3. **Registrar consumo**. Se o estoque for insuficiente, o sistema avisa a causa — registre a **entrada/inventário** primeiro (não force saldo negativo).

**Perdas** (venceu, estragou, quebrou — prejuízo puro):
1. Aba **Perdas** → adicione o produto e a quantidade. Se o item tiver lotes, **escolha o lote perdido** (na tela de lotes há o atalho "Registrar perda deste lote").
2. Informe o **motivo** e confirme. Lote vencido pode ser baixado como perda (com motivo); para consumo/produção/venda, lote vencido é **bloqueado** mesmo havendo outro lote válido.

**Produção** (transforma insumos em um produto que entra no estoque):
1. Cadastre a **receita** (produto final, rendimento e insumos) — selecione cada insumo e produto final na lista de sugestões (nome + unidade + código).
2. **Registrar produção** → informe quantas vezes fez a receita, o rendimento real (se diferente) e a validade do produto final.
3. Tudo é gravado numa **única transação**: se faltar um insumo, nada é alterado. Duplo clique não gera duas produções (idempotência por chave).

**Saneamento de estoque negativo** (conferência, sem inventar custo):
- Estoque negativo é erro de registro. Ao repor (compra, produção ou ajuste), o **custo médio** só é ponderado quando o saldo anterior é positivo; com saldo negativo/zero, assume o **custo da própria entrada** — nunca divide por zero nem inventa custo.
- Faça **inventário** (Produtos → Inventário) para acertar o saldo físico antes de operar. O banco **não é saneado automaticamente**.

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
.venv\Scripts\python.exe test_interface.py

# Linux / macOS
.venv/bin/python -m unittest test_gestao test_correcoes -v
.venv/bin/python test_interface.py
```

The regression suite redirects database operations to temporary files. The interface smoke test requires a desktop session and disables scale/printer activity. Do not use its optional live-store flags for a portfolio demo. See [verification notes](docs/PORTFOLIO_VALIDATION.md).

## Code map

| Module | Responsibility |
| --- | --- |
| `app.py`, `gestao_ui.py` | Tkinter application and finance screens |
| `database.py`, `schema.sql`, `gestao_schema.sql` | Persistence and schema initialization |
| `operacoes.py`, `gestao.py` | Retail operations and finance rules |
| `producao.py`, `validade.py` | Recipes, production and expiration batches |
| `balanca.py`, `impressora.py` | Hardware integration |
| `applock.py` | Cross-platform single-instance lock |
| `backup.py` | Consistent SQLite backups, retention and restore |
| `importar_nfe.py` | Supplier invoice (NF-e) import with safe preview |
| `test_gestao.py`, `test_correcoes.py`, `test_interface.py` | Regression, security/import/backup and UI smoke tests |

## Limitations

This portfolio snapshot is intended for local demonstrations. Physical peripherals were not validated during publication. It does not provide fiscal certification or direct payment processing. The [Java/React version](https://github.com/FelipeFeerreira/retail-pos-java) explores a separate web-based implementation.
