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
