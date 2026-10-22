# Capture guide — screenshots

This is a complete desktop application with checkout, inventory, credit and
finance, and it currently has no image. For a desktop POS, screenshots of the
operational screens are the strongest evidence that it works.

## Setup

1. Run the app against a **seeded demo database**, never a real store database.
2. Window at 1280×800 or larger, Windows default theme.
3. Fictional product names, prices and customers.

## Required shots

| File | Frame |
| --- | --- |
| `docs/screenshots/01-checkout.png` | Checkout with items in the cart, total visible |
| `docs/screenshots/02-inventory.png` | Product list with stock and expiration batches |
| `docs/screenshots/03-credit.png` | Customer credit account with a partial payment and receipt |
| `docs/screenshots/04-finance.png` | Cash session close or the financial summary |
| `docs/screenshots/05-receipt.png` | Printed or previewed receipt, next to the sale |

## Optional GIF (8–10 s)

Checkout flow: add product → change quantity → apply customer credit → finish sale.

## Paste into the README

After the intro paragraph:

```markdown
![Checkout screen](docs/screenshots/01-checkout.png)

| Checkout | Inventory | Customer credit | Finance |
| --- | --- | --- | --- |
| ![](docs/screenshots/01-checkout.png) | ![](docs/screenshots/02-inventory.png) | ![](docs/screenshots/03-credit.png) | ![](docs/screenshots/04-finance.png) |
```

## Also worth adding

- A one-line statement of how to build a Windows executable, since a desktop app
  that only runs from source loses non-technical readers.
- The same treatment for `docs/screenshots/` naming as the rest of the profile.
