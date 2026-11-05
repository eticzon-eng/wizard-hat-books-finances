import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("FINANCES_DB", str(ROOT / "data" / "test-unused.db"))

from fastapi.testclient import TestClient  # noqa: E402

from finances import db, royalties  # noqa: E402
from finances.api import app  # noqa: E402


KDP_CSV = (ROOT / "samples" / "kdp-royalties.csv").read_bytes()
KDP_PRIOR = (ROOT / "samples" / "kdp-prior-month-royalties.csv").read_bytes()
INGRAM_COMP = (ROOT / "samples" / "ingramspark-compensation.csv").read_bytes()
INGRAM_REGION = (ROOT / "samples" / "ingramspark-sales-by-region.csv").read_bytes()


class ParserTests(unittest.TestCase):
    def test_kdp_royalty_estimator_row(self):
        rows = royalties.parse_report(KDP_CSV, filename="kdp-royalties.csv", source="kdp")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["title"], "Silas and the Wizard")
        self.assertEqual(row["period"], "2026-09")
        self.assertEqual(row["royalty_date"], "2026-09-18")
        self.assertEqual(row["product_id"], "B0SAMPLE01")
        self.assertEqual(row["marketplace"], "Amazon.com")
        self.assertEqual(row["format"], "Paperback")
        self.assertEqual(row["net_units"], 3)
        self.assertEqual(row["amount_cents"], 840)
        self.assertEqual(row["currency"], "USD")

    def test_kdp_prior_month_needs_a_period(self):
        with self.assertRaises(royalties.ImportError_):
            royalties.parse_report(KDP_PRIOR, filename="kdp-prior-month-royalties.csv", source="kdp")
        rows = royalties.parse_report(
            KDP_PRIOR, filename="kdp-prior-month-royalties.csv", source="kdp", period="2026-08"
        )
        self.assertEqual(rows[0]["period"], "2026-08")
        self.assertEqual(rows[0]["amount_cents"], 699)
        self.assertEqual(rows[0]["net_units"], 2)

    def test_kdp_period_can_come_from_the_filename(self):
        rows = royalties.parse_report(KDP_PRIOR, filename="Prior_Months_Royalties_2026-08.csv", source="kdp")
        self.assertEqual(rows[0]["period"], "2026-08")

    def test_ingram_compensation_cleans_excel_isbn(self):
        rows = royalties.parse_report(
            INGRAM_COMP, filename="compensation.csv", source="ingramspark", period="2026-09"
        )
        row = rows[0]
        self.assertEqual(row["product_id"], "9780000000001")
        self.assertEqual(row["net_units"], 2)
        self.assertEqual(row["amount_cents"], 680)
        self.assertEqual(row["format"], "Paperback")
        self.assertEqual(row["marketplace"], "US")
        self.assertEqual(row["wholesale_price_cents"], 650)
        self.assertEqual(row["print_cost_cents"], 310)

    def test_ingram_sales_by_region_units_only(self):
        rows = royalties.parse_report(
            INGRAM_REGION, filename="sales.csv", source="ingramspark", period="2026-07"
        )
        self.assertEqual(rows[0]["net_units"], 4)
        self.assertIsNone(rows[0]["amount_cents"])
        self.assertEqual(rows[0]["format"], "Hardcover")
        self.assertEqual(rows[0]["product_id"], "9780000000001")

    def test_utf16_ingram_file(self):
        text = "Title,ISBN,Format,Country,Units Sold\nSilas and the Wizard,9780000000001,Paperback,US,1\n"
        raw = text.encode("utf-16")
        rows = royalties.parse_report(raw, filename="sales.csv", source="ingramspark", period="2026-09")
        self.assertEqual(rows[0]["net_units"], 1)

    def test_sources_reject_each_others_files(self):
        with self.assertRaises(royalties.ImportError_) as caught:
            royalties.parse_report(KDP_CSV, filename="kdp.csv", source="ingramspark")
        self.assertIn("KDP", str(caught.exception))
        with self.assertRaises(royalties.ImportError_) as caught:
            royalties.parse_report(INGRAM_COMP, filename="ingram.csv", source="kdp", period="2026-09")
        self.assertIn("IngramSpark", str(caught.exception))

    def test_kdp_workbook_uses_combined_sales_only(self):
        book = Workbook()
        decoy = book.active
        decoy.title = "eBook Royalty"
        decoy.append(["Royalty Date", "Title", "Marketplace", "Net Units Sold", "Royalty", "Currency"])
        decoy.append(["2026-01-01", "Should Not Import", "Amazon.com", 9, 99, "USD"])
        combined = book.create_sheet("Combined Sales")
        combined.append(
            [
                "Royalty Date",
                "Title",
                "Author Name",
                "ASIN/ISBN",
                "Marketplace",
                "Transaction Type",
                "Net Units Sold",
                "Royalty",
                "Currency",
            ]
        )
        combined.append(["2026-09-18", "Silas and the Wizard", "Edward Ticzon", "B0SAMPLE01", "Amazon.com", "Standard - Paperback", 1, 2.5, "USD"])
        buffer = io.BytesIO()
        book.save(buffer)
        rows = royalties.parse_report(buffer.getvalue(), filename="estimator.xlsx", source="kdp")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Silas and the Wizard")
        self.assertEqual(rows[0]["amount_cents"], 250)
        self.assertEqual(rows[0]["format"], "Paperback")


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["FINANCES_DB"] = str(Path(self.tmp.name) / "finances.db")
        db.init_db()
        self.client = TestClient(app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_locations_are_seeded(self):
        names = [row["name"] for row in self.client.get("/api/locations").json()]
        self.assertEqual(names, ["Home", "InkFish Books", "Barrington Books", "TikTok Shop"])

    def test_expense_round_trip(self):
        created = self.client.post(
            "/api/expenses",
            json={
                "spent_on": "2026-08-02",
                "payee": "Harbor Print",
                "category": "Printing",
                "description": "Proof copies",
                "amount_cents": 4525,
                "currency": "USD",
                "title": "Silas and the Wizard",
                "notes": "Invoice 14",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        body = created.json()
        self.assertEqual(body["payee"], "Harbor Print")
        self.assertEqual(body["amount_cents"], 4525)
        self.assertEqual(body["category"], "Printing")
        self.assertEqual(body["title"], "Silas and the Wizard")
        self.assertEqual(body["notes"], "Invoice 14")
        listed = self.client.get("/api/expenses").json()
        self.assertEqual(listed["expenses"][0]["id"], body["id"])
        self.assertEqual(listed["totals"][0]["amount_cents"], 4525)
        patched = self.client.patch(f"/api/expenses/{body['id']}", json={"notes": "Invoice 14 paid"})
        self.assertEqual(patched.json()["notes"], "Invoice 14 paid")
        self.assertEqual(patched.json()["amount_cents"], 4525)
        self.assertEqual(created.json()["payment_method"], "")
        self.assertEqual(created.json()["write_off_percent"], 100)

    def test_expense_modal_fields_round_trip(self):
        created = self.client.post(
            "/api/expenses",
            json={
                "spent_on": "2026-05-02",
                "payee": "Verizon",
                "category": "Mobile Phone",
                "description": "Mobile phone service",
                "amount_cents": 10000,
                "currency": "USD",
                "title": "",
                "notes": "",
                "payment_method": "Auto pay",
                "write_off_percent": 50,
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        body = created.json()
        self.assertEqual(body["payment_method"], "Auto pay")
        self.assertEqual(body["write_off_percent"], 50)
        self.assertEqual(body["write_off_cents"], 5000)
        self.assertEqual(body["book_title"], "General")
        uploaded = self.client.post(
            f"/api/expenses/{body['id']}/attachments",
            files=[("files", ("bill.png", b"receipt-bytes", "image/png"))],
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        attachment = uploaded.json()["attachments"][0]
        self.assertEqual(attachment["original_name"], "bill.png")
        downloaded = self.client.get(f"/api/expense-receipts/{attachment['id']}")
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.content, b"receipt-bytes")
        page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="expenseDialog"', page)
        self.assertIn('id="deleteExpenseBtn"', page)
        self.assertIn('id="expensePayment"', page)
        self.assertIn('id="expenseWriteOffPercent"', page)
        self.assertIn('id="expenseFiles"', page)
        self.assertNotIn("expenseRows", page)
        self.assertIn("margin: 0 auto", css)
        self.assertIn("min(var(--max), calc(100% - 2rem))", css)

    def test_library_seed_imports_through_the_model(self):
        seed = json.loads((ROOT / "seeds" / "expenses.json").read_text(encoding="utf-8"))
        self.assertEqual(len(seed), 90)
        self.assertEqual(sum(row["amount_cents"] for row in seed), 690533)
        self.assertEqual(self.client.get("/api/expenses").json()["expenses"], [])
        created = db.create_expenses(seed)
        self.assertEqual(len(created), 90)
        listed = self.client.get("/api/expenses").json()
        self.assertEqual(listed["totals"], [{"currency": "USD", "amount_cents": 690533, "count": 90}])
        titles = [row["title"] for row in created]
        self.assertEqual(titles.count("Silas and the Wizard"), 61)
        self.assertEqual(titles.count(""), 29)
        cursor = next(
            row for row in created if row["payee"] == "Cursor" and row["spent_on"] == "2026-04-07"
        )
        self.assertEqual(cursor["category"], "Software")
        self.assertEqual(cursor["description"], "Cursor AI Powered IDE")
        self.assertEqual(cursor["amount_cents"], 20544)
        self.assertEqual(cursor["currency"], "USD")
        self.assertEqual(cursor["title"], "")
        self.assertEqual(cursor["payment_method"], "Checking Debit Card")
        self.assertEqual(cursor["write_off_percent"], 100)
        internet = next(row for row in created if row["notes"] == "50% write off")
        self.assertEqual(internet["payee"], "Cox Communications/Spectrum")
        self.assertEqual(internet["category"], "Internet")
        self.assertEqual(internet["spent_on"], "2026-04-28")
        self.assertEqual(internet["amount_cents"], 9000)
        self.assertEqual(internet["write_off_percent"], 50)
        self.assertEqual(internet["payment_method"], "Checking Debit Card")
        self.assertEqual(sum(len(row.get("receipts") or []) for row in seed), 90)

    def test_royalty_samples_stay_separate(self):
        kdp = self.client.post(
            "/api/royalties/import",
            data={"source": "kdp", "period": ""},
            files={"file": ("kdp-royalties.csv", KDP_CSV, "text/csv")},
        )
        self.assertEqual(kdp.status_code, 200, kdp.text)
        self.assertEqual(kdp.json()["imported"], 1)
        ingram = self.client.post(
            "/api/royalties/import",
            data={"source": "ingramspark", "period": "2026-09"},
            files={"file": ("ingramspark-compensation.csv", INGRAM_COMP, "text/csv")},
        )
        self.assertEqual(ingram.status_code, 200, ingram.text)
        self.assertEqual(ingram.json()["imported"], 1)
        again = self.client.post(
            "/api/royalties/import",
            data={"source": "ingramspark", "period": "2026-09"},
            files={"file": ("ingramspark-compensation.csv", INGRAM_COMP, "text/csv")},
        )
        self.assertEqual(again.json()["imported"], 0)
        self.assertEqual(again.json()["skipped"], 1)

        mixed = self.client.post(
            "/api/royalties/import",
            data={"source": "ingramspark", "period": ""},
            files={"file": ("kdp-royalties.csv", KDP_CSV, "text/csv")},
        )
        self.assertEqual(mixed.status_code, 400)
        self.assertIn("KDP", mixed.json()["detail"])

        totals = self.client.get("/api/royalties").json()["totals"]
        by_source = {(row["source"], row["currency"]): row for row in totals["by_source"]}
        self.assertEqual(by_source[("kdp", "USD")]["amount_cents"], 840)
        self.assertEqual(by_source[("kdp", "USD")]["net_units"], 3)
        self.assertEqual(by_source[("ingramspark", "USD")]["amount_cents"], 680)
        self.assertEqual(by_source[("ingramspark", "USD")]["net_units"], 2)
        titles = {(row["source"], row["title"]) for row in totals["by_title"]}
        self.assertIn(("kdp", "Silas and the Wizard"), titles)
        self.assertIn(("ingramspark", "Silas and the Wizard"), titles)
        periods = {(row["source"], row["period"]) for row in totals["by_period"]}
        self.assertIn(("kdp", "2026-09"), periods)
        self.assertIn(("ingramspark", "2026-09"), periods)
        kdp_only = self.client.get("/api/royalties", params={"source": "kdp"}).json()["entries"]
        self.assertEqual(len(kdp_only), 1)
        self.assertTrue(all(row["source"] == "kdp" for row in kdp_only))

    def test_inventory_moves_and_tiktok_sale(self):
        title = self.client.post("/api/titles", json={"name": "Silas and the Wizard"}).json()
        locations = {row["name"]: row["id"] for row in self.client.get("/api/locations").json()}
        received = self.client.post(
            "/api/inventory/receive",
            json={
                "title_id": title["id"],
                "location_id": locations["Home"],
                "quantity": 10,
                "happened_on": "2026-09-01",
            },
        )
        self.assertEqual(received.status_code, 200, received.text)
        for name, qty in (("InkFish Books", 3), ("Barrington Books", 2)):
            moved = self.client.post(
                "/api/inventory/move",
                json={
                    "title_id": title["id"],
                    "from_location_id": locations["Home"],
                    "to_location_id": locations[name],
                    "quantity": qty,
                    "happened_on": "2026-09-02",
                },
            )
            self.assertEqual(moved.status_code, 200, moved.text)
        sold = self.client.post(
            "/api/inventory/sale",
            json={
                "title_id": title["id"],
                "from_location_id": locations["Home"],
                "channel_location_id": locations["TikTok Shop"],
                "quantity": 1,
                "happened_on": "2026-09-03",
                "unit_price_cents": 1499,
            },
        )
        self.assertEqual(sold.status_code, 200, sold.text)
        self.assertEqual(sold.json()["channel"], "TikTok Shop")
        on_hand = {
            (row["location"], row["quantity"])
            for row in self.client.get("/api/inventory").json()["on_hand"]
        }
        self.assertIn(("Home", 4), on_hand)
        self.assertIn(("InkFish Books", 3), on_hand)
        self.assertIn(("Barrington Books", 2), on_hand)
        self.assertIn(("TikTok Shop", 0), on_hand)
        sales = self.client.get("/api/inventory").json()["sales"]
        self.assertEqual(sales[0]["channel"], "TikTok Shop")
        self.assertEqual(sales[0]["quantity"], 1)
        self.assertEqual(sales[0]["amount_cents"], 1499)
        oversell = self.client.post(
            "/api/inventory/sale",
            json={
                "title_id": title["id"],
                "from_location_id": locations["Home"],
                "channel_location_id": locations["TikTok Shop"],
                "quantity": 99,
                "happened_on": "2026-09-04",
            },
        )
        self.assertEqual(oversell.status_code, 400)
        self.assertIn("Home", oversell.json()["detail"])


if __name__ == "__main__":
    unittest.main()
