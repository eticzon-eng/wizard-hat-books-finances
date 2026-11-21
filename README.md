# Wizard Hat Books Finances

Local site for Wizard Hat Books expenses, Amazon KDP royalties, IngramSpark royalties, copies on hand, and direct orders.

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

Open http://127.0.0.1:8791/expenses

The database is `data/finances.db` on this computer. The server listens on localhost only. It does not call Amazon, IngramSpark, or Stripe.

- Expenses: http://127.0.0.1:8791/expenses
- Royalties: http://127.0.0.1:8791/royalties
- Inventory: http://127.0.0.1:8791/inventory
- Orders: http://127.0.0.1:8791/orders
- Refunds: http://127.0.0.1:8791/refunds

http://127.0.0.1:8791 opens Expenses. An older address such as http://127.0.0.1:8791/#orders opens Orders.

`python3 -m finances init` creates the database without starting the site.

## Expenses

The Expenses page matches the Book Art Library ledger. Filter by year, book, vendor, category, and write-off, search, and print the report. Click a row to open it. Add and edit in that window: date, vendor, category, description, amount, currency, book (General when it is not tied to a book), payment method, tax write-off percent, notes, and receipt files. Delete is in that window. Totals stay per currency, and the tax write-off is the deductible part of each amount.

## Royalties

KDP and IngramSpark are separate ledgers. Totals are shown by source, by title, and by period, and the two sources are never added into one number. Different currencies are not added together.

Enter a row by hand, or import a report:

- **Amazon KDP — Royalties Estimator.** CSV, or the xlsx workbook. The import reads the Combined Sales sheet (Royalty Date, Title, Author Name, ASIN/ISBN, Marketplace, Royalty Type, Transaction Type, Units Sold, Units Refunded, Net Units Sold, Royalty, Currency).
- **Amazon KDP — Prior Month’s Royalties.** CSV with Title, ASIN, Marketplace, Net Units Sold, and Total Earnings. Set the report month when the file has no date. A name like `Prior_Months_Royalties_2026-08.csv` supplies that month.
- **IngramSpark — compensation.** Title, ISBN, Quantity Shipped, Returns, Wholesale Price, Cost of Printing, Net Compensation. Publisher Compensation is accepted as the same amount.
- **IngramSpark — sales by region.** Title, ISBN, Format, Country, Units Sold. Those rows can have units and no compensation.

UTF-16 exports and ISBNs wrapped as Excel formulas (`="978…"`) are accepted. Importing the same file twice skips rows that are already stored. Import one report shape per month; a compensation file and a sales-by-region file for the same sales would count those copies twice.

Sample files in `samples/` are fake figures for checking the import. They are not a statement.

## Orders

Direct orders are kept here. Stripe only pays them out. The site does not call Stripe, and it does not store a Stripe key.

An order records the buyer, the title, the copies, where those copies will leave, the sale total, and the Stripe fee. Leave the fee blank on a US dollar sale and the site estimates 2.9% + $0.30, which is the part Stripe keeps from the payout. Enter the fee when you know the payout amount, or when the sale is not in US dollars. Sales minus the Stripe fee is the total on the Orders screen. Currencies stay separate.

The order you add on this screen stays not shipped, and the copies stay on the shelf, until you mark it shipped. Shipping takes the copies from the shelf you chose, stores the carrier and tracking number, and counts the sale under Website. Marking that kind of order not shipped puts the copies back.

A paid test checkout on the local author site is different. The author site tells this site about the paid Checkout Session. The order is saved with the buyer, the address, the amount charged, and the Stripe fee. When the session includes the fee Stripe kept, that fee is stored. Otherwise a US dollar sale uses 2.9% + $0.30. The copies leave Home at that moment and the sale is counted under Website. The order stays not shipped, with no tracking number and no refund, until you enter those here. Marking it shipped or not shipped after that does not move the copies again.

Refund requests are on their own screen. An open or declined request does not change the sales total. Mark it refunded when that amount should come out. The Stripe fee stays in the fee total either way.

## Inventory

Add a title, receive copies (usually at Home), move them, and record a sale.

A sale says where the copies left and where they sold. A TikTok Shop sale of a copy that was still at home leaves Home and is counted under TikTok Shop. A copy sent to InkFish Books or Barrington Books stays on hand at that shop until you record a sale from there. The site will not move or sell more copies than a location has.

Not shipped, on the inventory table, is the number of copies on orders that have not shipped and have not already left the shelf. Website on the sales list is the sale price before the Stripe fee. A paid test checkout shows up there as soon as it is recorded.

## Tests

```bash
python3 -m unittest tests.test_finances -v
```
