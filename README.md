# Retail POS — Python Desktop

A desktop retail-management application built with **Python, Tkinter and SQLite**. It combines checkout and inventory operations with customer credit, purchasing and financial management. The user interface is primarily in Brazilian Portuguese.

| | |
|:--|:--|
| **Live demo** | Desktop app — no hosted demo |
| **Screenshots** | Pending — see [docs/CAPTURE_GUIDE.md](docs/CAPTURE_GUIDE.md) |
| **Stack** | Python · Tkinter · SQLite |
| **License** | MIT — [LICENSE](LICENSE) |

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

## Operator runbook

**1. Purchase and goods receipt**
- **File → Import invoice (NF-e)** for a supplier invoice, or **Receive goods** (Tools) to type it. Both show a preview, ask for confirmation and back up before writing. The goods enter **stock** and the amount becomes an **account payable** (category "Goods for resale") — it is not an expense: cost is only recognised when the item is sold, consumed or lost (COGS).

**2. Internal consumption** (operational/team use — leaves at cost price, not a sale):
1. **Internal consumption** tab → search the product by name/code and enter the quantity (commas accepted).
2. Check the list and choose the **reason** (cleaning/packaging = operational, "Team snacks" = team, "Personal/family consumption" = owner withdrawal).
3. **Record consumption**. The screen shows a **cost preview**; if the cost is unknown it warns and marks the total as partial. Missing stock shows the cause (record a receipt/inventory count first).

**3. Family withdrawal** — same screen as consumption, reason **"Personal/family consumption"**. It is booked as a **withdrawal** (not an operating expense) and appears separately in the result.

**4. Loss** (expired, spoiled, broken — a pure loss):
1. **Losses** tab → add the product and quantity. If the item has batches, **choose the lost batch** (or use the **"Record loss"** shortcut on the Batches and expiry tab).
2. Enter the **reason** and confirm. An expired batch can be written off as a loss (with a reason); for consumption/production/sale, an expired batch is **blocked** even when another valid batch exists.

**5. Production** (turns inputs into a product that enters stock):
1. Register the **recipe** (finished product, yield and inputs) — pick each input and the finished product from the suggestion list (name + unit + code).
2. **Record production** → the screen shows a **preview** (inputs needed × available, cost, expected/actual yield, expiry). Enter how many times the recipe was made, the actual yield and the expiry.
3. Everything is written in a **single transaction**: if one input is missing, nothing changes. Input cost becomes the finished product cost **once** (it is not also booked as consumption). A double click does not create two productions.

**6. Store bills and payment**
- **Finance → Accounts payable → New bill**: payee, description, category (rent, power, water, internet, salaries, maintenance, services...), amount, **accrual month** (the month it hits the result), due date and document.
- **Record payment**: choose the financial account and the amount (partial payments accepted). The expense hits the **result by accrual** (full amount) and the **cash when paid** — a partial payment does not duplicate the expense.
- Goods for resale and Investment are **not** operating expenses. Capital injections, withdrawals and transfers are **neither revenue nor expense**.

**7. Reading the result and the cash position**
- **Finance → Management P&L**: panel by accrual month with a **Today / 7 / 30 days / custom period** filter (date fields at the top). Structure:

  ```
  Net sales after discounts and cancellations
  − historical COGS of the goods sold
  = Gross margin
  − card and other payment-method fees
  − losses (at cost price)
  − operational consumption
  − team consumption
  − consumption to be classified
  − store expenses by accrual
  + other income  − other expenses
  = NET MANAGEMENT RESULT
  − personal/family withdrawals (at cost price)
  = RESULT AFTER PERSONAL/FAMILY WITHDRAWALS
  ```

  Select a line and click **View entries** (or double-click) to open the records behind the value. If any item is missing a cost, the panel warns **"PARTIAL RESULT"** and lists the pending items.
- Next to it, the **"Cash is not profit"** block: cash on hand, recorded bank balance, card receivables, customer credit receivables, open payables and the period's effective cash flow. Customer credit is a sale result, but not money received; receiving it later is not a second sale.

**Reversing consumption/loss:** in the **Internal consumption** or **Losses** history, open the entry (double-click) and use **Reverse entry** with a reason. The original is preserved (marked as reversed), stock and batches come back and the indicator is corrected. A duplicate reversal is blocked.

**Cleaning up negative stock** (reconciliation, without inventing cost):
- Negative stock is a recording error. When restocking (purchase, production or adjustment), the **average cost** is only weighted when the previous balance is positive; with a negative/zero balance it takes the **cost of that receipt** — it never divides by zero nor invents a cost.
- Run an **inventory count** (Products → Inventory) to fix the physical balance before operating. The database is **not cleaned up automatically**.

**Unknown cost:** when a product has no cost price (≤ 0), the consumption, loss and production screens show "unknown cost" instead of R$ 0.00, and the total is marked as partial — so unknown is never confused with zero cost.

**Idempotency:** consumption, losses and production write a unique key. A double click or a resend of the same attempt does not create two entries (this includes consumption from Tools and losses from the Batches tab).

## Migrations

The schema is versioned (`schema_meta.versao` in `database.py`, the `SCHEMA_VERSAO` constant). When the app opens and the database is on an older version, a consistent **pre-migration backup** is created (`backups/antes_migracao_v<version>_<date>.db`) before columns/tables/indexes are applied — the migration is additive and repeatable. **When changing the schema, bump `SCHEMA_VERSAO`**, otherwise databases already on the current version migrate without a backup.

## Toledo 8217 scale (Prix)

Configuration in **File → Configure scale**. The app already speaks the 8217 protocols (P05A, P05B, P05, P06).

1. On the scale, program protocol **P05A** (parameter `C09`) and choose the **baud rate** (parameter `C10`; factory default **2400**).
2. In the app, select the port, the protocol, the **same baud rate** and the parity (usually **None**).
3. Click **Test connection**: put a weight on the scale and check the "Weight: X kg" that appears. If no weight arrives, the **Bytes received** field shows what is coming in (it helps find the right baud/parity). Save.

Serial ports:
- **Windows:** `COM3`, `COM4`, ... (listed automatically).
- **Linux:** usually `/dev/ttyUSB0` (USB adapter) or `/dev/ttyS0` (native serial). On a permission error, add the user to the group: `sudo usermod -aG dialout $USER` (log in again afterwards).

The P05A protocol sends the weight as 5 digits without a decimal point (`15000` = 15.000 kg); P05B/P06 send it with one (`00.185`). Unstable (`IIIII`), negative (`NNNNN`) and overload (`SSSSS`) weights are ignored. Reading runs in the background and never blocks the checkout; on the sale screen, when adding a product by KG the scale weight is used automatically when available.

> The integration was validated by automated parser and dialog tests, but **was not physically verified** with a scale connected — the final check depends on the hardware and the cable.

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
| `app.py`, `gestao_ui.py` | Tkinter application and finance screens |
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

---

## What I would do next

- Capture the operator screens and build a Windows .exe so the app can be tried without Python.
- Validate the Toledo 8217 scale integration on real hardware and record the result in Verification.
- Add automated tests around stock movements and cash closing.

## License

MIT - see [LICENSE](LICENSE). You may use, modify and redistribute this code with attribution.
