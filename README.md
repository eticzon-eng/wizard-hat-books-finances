# Wizard Hat Books Finances

Local site for Wizard Hat Books expenses, Amazon KDP royalties, IngramSpark royalties, and copies on hand.

This repository is separate from the art library and the author site (`eticzon-eng/book-art-library`) and from the tennis league (`eticzon-eng/fantasy_league`). Artwork and the public author site stay in the art library.

Book Art Library expenses are in `seeds/expenses.json`, with receipt files under `seeds/receipts/`. Starting the site creates `data/finances.db` and, when that database has no expenses yet, loads the seed. An existing copy of those rows is filled in with payment method, tax write-off percent, and receipts. The database file stays on this computer. Inventory starts with four locations: Home, InkFish Books, Barrington Books, and TikTok Shop.

## Run locally

```bash
cd ~/Documents/AI/wizard-hat-books-finances
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m finances serve
```

Open http://127.0.0.1:8791

The database is `data/finances.db` on this computer. The server listens on localhost only. It does not call Amazon or IngramSpark.

`python3 -m finances init` creates the database without starting the site.

## Expenses

The Expenses tab matches the Book Art Library ledger. Filter by year, book, vendor, category, and write-off, search, and print the report. Click a row to open it. Add and edit in that window: date, vendor, category, description, amount, currency, book (General when it is not tied to a book), payment method, tax write-off percent, notes, and receipt files. Delete is in that window. Totals stay per currency, and the tax write-off is the deductible part of each amount.

## Royalties

KDP and IngramSpark are separate ledgers. Totals are shown by source, by title, and by period, and the two sources are never added into one number. Different currencies are not added together.

Enter a row by hand, or import a report:

- **Amazon KDP — Royalties Estimator.** CSV, or the xlsx workbook. The import reads the Combined Sales sheet (Royalty Date, Title, Author Name, ASIN/ISBN, Marketplace, Royalty Type, Transaction Type, Units Sold, Units Refunded, Net Units Sold, Royalty, Currency).
- **Amazon KDP — Prior Month’s Royalties.** CSV with Title, ASIN, Marketplace, Net Units Sold, and Total Earnings. Set the report month when the file has no date. A name like `Prior_Months_Royalties_2026-08.csv` supplies that month.
- **IngramSpark — compensation.** Title, ISBN, Quantity Shipped, Returns, Wholesale Price, Cost of Printing, Net Compensation. Publisher Compensation is accepted as the same amount.
- **IngramSpark — sales by region.** Title, ISBN, Format, Country, Units Sold. Those rows can have units and no compensation.

UTF-16 exports and ISBNs wrapped as Excel formulas (`="978…"`) are accepted. Importing the same file twice skips rows that are already stored. Import one report shape per month; a compensation file and a sales-by-region file for the same sales would count those copies twice.

Sample files in `samples/` are fake figures for checking the import. They are not a statement.

## Inventory

Add a title, receive copies (usually at Home), move them, and record a sale.

A sale says where the copies left and where they sold. A TikTok Shop sale of a copy that was still at home leaves Home and is counted under TikTok Shop. A copy sent to InkFish Books or Barrington Books stays on hand at that shop until you record a sale from there. The site will not move or sell more copies than a location has.

## Tests

```bash
python3 -m unittest tests.test_finances -v
```
