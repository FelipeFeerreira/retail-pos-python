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

Use Windows and Python 3.13 with Tkinter support. The requirements include Windows-specific printer integration.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

The application initializes its SQLite database on first run. Create a manager account and configure store preferences locally. This repository intentionally contains no live database, store configuration, customer records or backups.

## Verification

```powershell
.venv\Scripts\python.exe -m unittest test_gestao -v
.venv\Scripts\python.exe test_interface.py
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
| `test_gestao.py`, `test_interface.py` | Regression and UI smoke tests |

## Limitations

This portfolio snapshot is intended for local demonstrations. Physical peripherals were not validated during publication. It does not provide fiscal certification or direct payment processing. The [Java/React version](https://github.com/FelipeFeerreira/retail-pos-java) explores a separate web-based implementation.
