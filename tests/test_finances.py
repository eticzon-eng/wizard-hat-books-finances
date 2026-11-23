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

from finances import db, receipt_read, royalties  # noqa: E402
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
        self.assertEqual(names, ["Home", "InkFish Books", "Barrington Books", "TikTok Shop", "Website"])

    def test_each_section_is_its_own_page(self):
        home = self.client.get("/", follow_redirects=False)
        self.assertEqual(home.status_code, 307)
        self.assertEqual(home.headers["location"], "/expenses")
        pages = {
            "/expenses": "expenseDialog",
            "/royalties": "royaltyForm",
            "/inventory": "titleForm",
            "/orders": "orderDialog",
            "/refunds": "refundForm",
        }
        for path, marker in pages.items():
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn(f'id="{marker}"', response.text)
            self.assertIn('href="/orders"', response.text)
            self.assertIn('href="/refunds"', response.text)
            self.assertEqual(response.text.count('aria-current="page"'), 1)
        self.assertNotIn('id="orderDialog"', self.client.get("/refunds").text)
        self.assertNotIn('id="refundForm"', self.client.get("/orders").text)
        slash = self.client.get("/orders/", follow_redirects=False)
        self.assertEqual(slash.status_code, 307)
        self.assertEqual(slash.headers["location"], "/orders")

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
        page = (ROOT / "static" / "expenses.html").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="expenseDialog"', page)
        self.assertIn('id="deleteExpenseBtn"', page)
        self.assertIn('id="expensePayment"', page)
        self.assertIn('id="expenseWriteOffPercent"', page)
        self.assertIn('id="expenseFiles"', page)
        self.assertIn('id="expenseCapture"', page)
        self.assertIn('id="discardExpenseBtn"', page)
        self.assertNotIn('<label class="field">\n            <span>Vendor</span>', page)
        script = (ROOT / "static" / "expenses.js").read_text(encoding="utf-8")
        self.assertIn("/api/expenses/read-receipt", script)
        self.assertIn("Nothing is saved until you click Save", script)
        self.assertNotIn("expenseRows", page)
        self.assertIn("margin: 0 auto", css)
        self.assertIn("min(var(--max), calc(100% - 2rem))", css)

    def test_read_receipt_fills_fields_without_saving(self):
        categories = [row["label"] for row in db.list_expense_categories()]
        receipt = """
        CURSOR
        Date: April 7, 2026
        Description: Cursor Pro
        Subtotal $180.00
        Tax $25.44
        Total $205.44
        Visa debit
        Silas and the Wizard
        Invoice #1042
        """
        fields = receipt_read.parse_receipt_text(
            receipt,
            vendors=["Cursor"],
            categories=categories,
            books=["Silas and the Wizard"],
        )
        self.assertEqual(fields["spent_on"], "2026-04-07")
        self.assertEqual(fields["payee"], "Cursor")
        self.assertEqual(fields["amount"], "205.44")
        self.assertEqual(fields["currency"], "USD")
        self.assertEqual(fields["category"], "Software")
        self.assertEqual(fields["description"], "Cursor Pro")
        self.assertEqual(fields["payment_method"], "Visa debit")
        self.assertEqual(fields["title"], "Silas and the Wizard")
        self.assertEqual(fields["notes"], "Invoice #1042")

        bank = """
        Chase
        Debit card purchase
        META PLATFORMS
        FACEBOOK ADS
        10/03/2026
        -$5.00
        """
        bank_fields = receipt_read.parse_receipt_text(
            bank,
            vendors=["Meta"],
            categories=categories,
            books=["Silas and the Wizard"],
        )
        self.assertEqual(bank_fields["spent_on"], "2026-10-03")
        self.assertEqual(bank_fields["payee"], "Meta")
        self.assertEqual(bank_fields["amount"], "5.00")
        self.assertEqual(bank_fields["currency"], "USD")
        self.assertEqual(bank_fields["category"], "Advertising")
        self.assertEqual(bank_fields["description"], "FACEBOOK ADS")
        self.assertEqual(bank_fields["payment_method"], "Debit card purchase")
        self.assertEqual(bank_fields["title"], "")
        self.assertEqual(bank_fields["notes"], "")

        blank = receipt_read.parse_receipt_text("hello", categories=categories)
        for name in receipt_read.FIELD_NAMES:
            self.assertEqual(blank[name], "")

        highlighted = """
        Aug 13 CURSOR USAGE JUL Purchase -$17.70
        [[highlight]]Apr 07 CURSOR AI POWERED IDE Purchase -$205.44
        May 11 CURSOR USAGE MID MAY Purchase -$21.74
        """
        picked = receipt_read.parse_receipt_text(
            highlighted,
            vendors=["Cursor"],
            categories=categories,
            books=["Silas and the Wizard"],
        )
        self.assertTrue(picked["highlighted"])
        self.assertEqual(picked["spent_on"], "2026-04-07")
        self.assertEqual(picked["payee"], "Cursor")
        self.assertEqual(picked["amount"], "205.44")
        self.assertEqual(picked["currency"], "USD")
        self.assertEqual(picked["description"], "CURSOR AI POWERED IDE")
        self.assertEqual(picked["payment_method"], "Purchase")
        self.assertNotEqual(picked["amount"], "17.70")

        unhighlighted = """
        Aug 13 CURSOR USAGE JUL Purchase -$17.70
        Apr 07 CURSOR AI POWERED IDE Purchase -$205.44
        May 11 CURSOR USAGE MID MAY Purchase -$21.74
        """
        shared = receipt_read.parse_receipt_text(
            unhighlighted,
            vendors=["Cursor"],
            categories=categories,
            books=["Silas and the Wizard"],
        )
        self.assertFalse(shared["highlighted"])
        self.assertEqual(shared["amount"], "")
        self.assertEqual(shared["spent_on"], "")
        self.assertEqual(shared["payee"], "Cursor")

        detail = """
        Sep 07 Facebook Professional Services Edward T...8066 $2.00
        You earned $0.03 Rewards cash with this transaction!
        Purchased: Sun, Sep 6, 2026
        Posted: Mon, Sep 7, 2026
        Appears on statement as: FACEBK *JNFTA2WE34
        """
        facebook = receipt_read.parse_receipt_text(
            detail,
            vendors=["Meta"],
            categories=categories,
            books=["Silas and the Wizard"],
        )
        self.assertEqual(facebook["spent_on"], "2026-09-07")
        self.assertEqual(facebook["payee"], "Meta")
        self.assertEqual(facebook["amount"], "2.00")
        self.assertEqual(facebook["currency"], "USD")
        self.assertEqual(facebook["category"], "Advertising")
        self.assertEqual(facebook["description"], "FACEBK *JNFTA2WE34")

        same_line = """
        ^ 07 Facebook 1.5% cash back $2.00
        You earned $0.03 Rewards cash with this transaction!
        Posted: Mon, Sep 7, 2026
        Аppears on statement as: FACEBK *JNFTA2WE34
        """
        reward_line = receipt_read.parse_receipt_text(
            same_line,
            vendors=["Meta"],
            categories=categories,
            books=["Silas and the Wizard"],
        )
        self.assertEqual(reward_line["amount"], "2.00")
        self.assertEqual(reward_line["spent_on"], "2026-09-07")
        self.assertEqual(reward_line["description"], "FACEBK *JNFTA2WE34")
        self.assertFalse(reward_line["highlighted"])

        banner = """
        [[highlight]]Payment complete! Work with Hannah again?
        Total $2,602.60
        Payment received Jul 27, 2026
        Developmental Editing
        """
        invoice = receipt_read.parse_receipt_text(
            banner,
            vendors=["Reedsy"],
            categories=categories,
            books=["Silas and the Wizard"],
        )
        self.assertFalse(invoice["highlighted"])
        self.assertEqual(invoice["amount"], "2602.60")
        self.assertEqual(invoice["spent_on"], "2026-07-27")

        before = self.client.get("/api/expenses").json()["expenses"]
        tiny = bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
            "de0000000c4944415408d763f8ffff3f0005fe02fe5b2a1a2e0000000049454e44ae426082"
        )
        read = self.client.post(
            "/api/expenses/read-receipt",
            files={"file": ("shot.png", tiny, "image/png")},
        )
        self.assertEqual(read.status_code, 200, read.text)
        body = read.json()
        for name in receipt_read.FIELD_NAMES:
            self.assertEqual(body[name], "")
        self.assertEqual(self.client.get("/api/expenses").json()["expenses"], before)
        self.assertEqual(db.list_expenses(), before)

    def test_screenshot_ocr_does_not_save_until_confirm(self):
        if not receipt_read.ocr_available():
            self.skipTest("macOS Vision OCR is not available")
        self.client.post("/api/expense-vendors", json={"name": "Cursor"})
        self.client.post("/api/expense-books", json={"name": "Silas and the Wizard"})
        image = Path(self.tmp.name) / "receipt.png"
        receipt_read.render_receipt_image(
            image,
            "\n".join(
                [
                    "CURSOR",
                    "Date: April 7, 2026",
                    "Description: Cursor Pro",
                    "Total $205.44",
                    "Visa debit",
                    "Silas and the Wizard",
                    "Invoice #1042",
                ]
            ),
        )
        before = self.client.get("/api/expenses").json()["expenses"]
        read = self.client.post(
            "/api/expenses/read-receipt",
            files={"file": ("receipt.png", image.read_bytes(), "image/png")},
        )
        self.assertEqual(read.status_code, 200, read.text)
        body = read.json()
        self.assertEqual(body["spent_on"], "2026-04-07")
        self.assertEqual(body["payee"], "Cursor")
        self.assertEqual(body["amount"], "205.44")
        self.assertEqual(body["currency"], "USD")
        self.assertEqual(body["category"], "Software")
        self.assertEqual(body["description"], "Cursor Pro")
        self.assertEqual(body["payment_method"], "Visa debit")
        self.assertEqual(body["title"], "Silas and the Wizard")
        self.assertEqual(body["notes"], "Invoice #1042")
        self.assertEqual(self.client.get("/api/expenses").json()["expenses"], before)

        unread = Path(self.tmp.name) / "blank.png"
        receipt_read.render_receipt_image(unread, "hello")
        blank = self.client.post(
            "/api/expenses/read-receipt",
            files={"file": ("blank.png", unread.read_bytes(), "image/png")},
        )
        self.assertEqual(blank.status_code, 200, blank.text)
        for name in receipt_read.FIELD_NAMES:
            self.assertEqual(blank.json()[name], "")
        self.assertEqual(self.client.get("/api/expenses").json()["expenses"], before)

        listed = Path(self.tmp.name) / "list.png"
        receipt_read.render_highlighted_list(listed)
        before_list = self.client.get("/api/expenses").json()["expenses"]
        read_list = self.client.post(
            "/api/expenses/read-receipt",
            files={"file": ("list.png", listed.read_bytes(), "image/png")},
        )
        self.assertEqual(read_list.status_code, 200, read_list.text)
        chosen = read_list.json()
        self.assertTrue(chosen["highlighted"])
        self.assertEqual(chosen["amount"], "205.44")
        self.assertEqual(chosen["payee"], "Cursor")
        self.assertEqual(chosen["spent_on"], "2026-04-07")
        self.assertNotIn("17.70", chosen["amount"])
        self.assertEqual(self.client.get("/api/expenses").json()["expenses"], before_list)

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

    def test_orders_track_shipping_refunds_and_the_stripe_fee(self):
        orders_page = self.client.get("/orders")
        refunds_page = self.client.get("/refunds")
        self.assertEqual(orders_page.status_code, 200)
        self.assertEqual(refunds_page.status_code, 200)
        self.assertIn('id="view-orders"', orders_page.text)
        self.assertIn('id="view-refunds"', refunds_page.text)
        self.assertNotIn("sk_live_", orders_page.text)
        self.assertNotIn("sk_test_", orders_page.text)
        self.assertNotIn("sk_live_", refunds_page.text)
        self.assertNotIn("sk_test_", refunds_page.text)

        title = self.client.post("/api/titles", json={"name": "Silas and the Wizard"}).json()
        locations = {row["name"]: row["id"] for row in self.client.get("/api/locations").json()}
        received = self.client.post(
            "/api/inventory/receive",
            json={
                "title_id": title["id"],
                "location_id": locations["Home"],
                "quantity": 2,
                "happened_on": "2026-11-01",
            },
        )
        self.assertEqual(received.status_code, 200, received.text)

        created = self.client.post(
            "/api/orders",
            json={
                "ordered_on": "2026-11-02",
                "buyer_name": "Ada Lovelace",
                "email": "ada@example.com",
                "ship_to": "1 Analytical Engine\nLondon",
                "title_id": title["id"],
                "quantity": 1,
                "from_location_id": locations["Home"],
                "amount_cents": 3699,
                "currency": "USD",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        order = created.json()
        self.assertEqual(order["ship_status"], "not_shipped")
        self.assertEqual(order["stripe_fee_cents"], 137)
        self.assertEqual(order["net_cents"], 3562)
        self.assertIn("\n", order["ship_to"])

        on_hand = {
            (row["location"], row["quantity"])
            for row in self.client.get("/api/inventory").json()["on_hand"]
            if row["title_id"] == title["id"]
        }
        self.assertIn(("Home", 2), on_hand)
        waiting = self.client.get("/api/inventory").json()["awaiting_shipment"]
        self.assertEqual(waiting, [{"title_id": title["id"], "title": "Silas and the Wizard", "quantity": 1}])

        refused = self.client.post(
            "/api/orders",
            json={
                "ordered_on": "2026-11-02",
                "buyer_name": "Grace Hopper",
                "title_id": title["id"],
                "quantity": 1,
                "amount_cents": 3699,
                "currency": "CAD",
            },
        )
        self.assertEqual(refused.status_code, 400)
        self.assertIn("Stripe fee", refused.json()["detail"])

        cad = self.client.post(
            "/api/orders",
            json={
                "ordered_on": "2026-11-03",
                "buyer_name": "Grace Hopper",
                "title_id": title["id"],
                "quantity": 1,
                "from_location_id": locations["Home"],
                "amount_cents": 4000,
                "stripe_fee_cents": 146,
                "currency": "CAD",
            },
        )
        self.assertEqual(cad.status_code, 200, cad.text)

        shipped = self.client.post(
            f"/api/orders/{order['id']}/ship",
            json={
                "shipped_on": "2026-11-04",
                "from_location_id": locations["Home"],
                "tracking_number": "1Z999",
                "carrier": "UPS",
            },
        )
        self.assertEqual(shipped.status_code, 200, shipped.text)
        self.assertEqual(shipped.json()["ship_status"], "shipped")
        self.assertEqual(shipped.json()["tracking_number"], "1Z999")
        self.assertEqual(shipped.json()["carrier"], "UPS")

        home = next(
            row["quantity"]
            for row in self.client.get("/api/inventory").json()["on_hand"]
            if row["title_id"] == title["id"] and row["location"] == "Home"
        )
        self.assertEqual(home, 1)
        sales = self.client.get("/api/inventory").json()["sales"]
        self.assertEqual(sales[0]["channel"], "Website")
        self.assertEqual(sales[0]["quantity"], 1)
        self.assertEqual(sales[0]["amount_cents"], 3699)
        event_id = next(row["id"] for row in self.client.get("/api/inventory").json()["events"] if row["kind"] == "sale")
        blocked = self.client.delete(f"/api/inventory/events/{event_id}")
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("Orders", blocked.json()["detail"])

        over = self.client.post(
            "/api/orders",
            json={
                "ordered_on": "2026-11-05",
                "buyer_name": "Too Many",
                "title_id": title["id"],
                "quantity": 5,
                "from_location_id": locations["Home"],
                "amount_cents": 1000,
                "stripe_fee_cents": 0,
                "currency": "USD",
            },
        )
        self.assertEqual(over.status_code, 200, over.text)
        cannot_ship = self.client.post(
            f"/api/orders/{over.json()['id']}/ship",
            json={"shipped_on": "2026-11-05", "from_location_id": locations["Home"]},
        )
        self.assertEqual(cannot_ship.status_code, 400)
        self.assertEqual(self.client.get(f"/api/orders").json()["orders"][0]["ship_status"], "not_shipped")

        refund = self.client.post(
            f"/api/orders/{order['id']}/refunds",
            json={"requested_on": "2026-11-06", "amount_cents": 1000, "reason": "Damaged corner"},
        )
        self.assertEqual(refund.status_code, 200, refund.text)
        self.assertEqual(refund.json()["status"], "open")
        totals = {row["currency"]: row for row in self.client.get("/api/orders").json()["totals"]["by_currency"]}
        self.assertEqual(totals["USD"]["gross_cents"], 4699)
        self.assertEqual(totals["USD"]["stripe_fee_cents"], 137)
        self.assertEqual(totals["USD"]["sales_after_fee_cents"], 4562)
        self.assertEqual(totals["USD"]["refunded_cents"], 0)
        self.assertEqual(totals["CAD"]["sales_after_fee_cents"], 3854)
        self.assertEqual(self.client.get("/api/orders").json()["totals"]["open_refunds"], 1)

        too_much = self.client.post(
            f"/api/orders/{order['id']}/refunds",
            json={"requested_on": "2026-11-06", "amount_cents": 3000, "reason": "Also this"},
        )
        self.assertEqual(too_much.status_code, 400)

        marked = self.client.patch(f"/api/refunds/{refund.json()['id']}", json={"status": "refunded"})
        self.assertEqual(marked.status_code, 200, marked.text)
        usd = {row["currency"]: row for row in self.client.get("/api/orders").json()["totals"]["by_currency"]}["USD"]
        self.assertEqual(usd["refunded_cents"], 1000)
        self.assertEqual(usd["sales_after_fee_cents"], 4562)
        self.assertEqual(usd["net_cents"], 3562)

        unshipped = self.client.post(f"/api/orders/{order['id']}/unship")
        self.assertEqual(unshipped.status_code, 200, unshipped.text)
        self.assertEqual(unshipped.json()["ship_status"], "not_shipped")
        self.assertEqual(unshipped.json()["tracking_number"], "1Z999")
        home_again = next(
            row["quantity"]
            for row in self.client.get("/api/inventory").json()["on_hand"]
            if row["title_id"] == title["id"] and row["location"] == "Home"
        )
        self.assertEqual(home_again, 2)

        removed = self.client.delete(f"/api/orders/{order['id']}")
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertFalse(any(row["buyer_name"] == "Ada Lovelace" for row in self.client.get("/api/orders").json()["orders"]))

    def test_paid_checkout_takes_stock_and_leaves_shipping_open(self):
        short = self.client.post(
            "/api/orders/checkout",
            json={
                "checkout_session_id": "cs_test_short_stock",
                "ordered_on": "2026-11-21",
                "buyer_name": "Short Stock",
                "email": "short@example.com",
                "ship_to": "1 Main St\nProvidence RI 02903\nUnited States",
                "title": "Silas and the Wizard",
                "quantity": 1,
                "amount_cents": 4199,
                "currency": "USD",
            },
        )
        self.assertEqual(short.status_code, 200, short.text)
        self.assertEqual(short.json()["ship_status"], "not_shipped")
        self.assertEqual(short.json()["tracking_number"], "")
        self.assertEqual(short.json()["stock_taken_at"], "")
        self.assertIn("Not enough copies", short.json()["notes"])
        self.assertEqual(short.json()["stripe_fee_cents"], 152)
        self.assertEqual(short.json()["refunds"], [])

        title_id = short.json()["title_id"]
        locations = {row["name"]: row["id"] for row in self.client.get("/api/locations").json()}
        received = self.client.post(
            "/api/inventory/receive",
            json={
                "title_id": title_id,
                "location_id": locations["Home"],
                "quantity": 2,
                "happened_on": "2026-11-20",
            },
        )
        self.assertEqual(received.status_code, 200, received.text)

        paid = self.client.post(
            "/api/orders/checkout",
            json={
                "checkout_session_id": "cs_test_paid_order",
                "ordered_on": "2026-11-21",
                "buyer_name": "Ada Lovelace",
                "email": "ada@example.com",
                "ship_to": "1 Analytical Engine\nLondon",
                "title": "Silas and the Wizard",
                "quantity": 1,
                "amount_cents": 4199,
                "stripe_fee_cents": 80,
                "currency": "USD",
            },
        )
        self.assertEqual(paid.status_code, 200, paid.text)
        order = paid.json()
        self.assertEqual(order["buyer_name"], "Ada Lovelace")
        self.assertEqual(order["ship_to"], "1 Analytical Engine\nLondon")
        self.assertEqual(order["amount_cents"], 4199)
        self.assertEqual(order["stripe_fee_cents"], 80)
        self.assertEqual(order["ship_status"], "not_shipped")
        self.assertEqual(order["tracking_number"], "")
        self.assertEqual(order["carrier"], "")
        self.assertEqual(order["stock_taken_at"], "payment")
        self.assertEqual(order["refunds"], [])

        def home_quantity():
            return next(
                row["quantity"]
                for row in self.client.get("/api/inventory").json()["on_hand"]
                if row["title_id"] == title_id and row["location"] == "Home"
            )

        self.assertEqual(home_quantity(), 1)
        waiting = self.client.get("/api/inventory").json()["awaiting_shipment"]
        self.assertTrue(all(row["title_id"] != title_id or row["quantity"] == 1 for row in waiting))
        sales = self.client.get("/api/inventory").json()["sales"]
        self.assertEqual(sales[0]["channel"], "Website")
        self.assertEqual(sales[0]["quantity"], 1)

        again = self.client.post(
            "/api/orders/checkout",
            json={
                "checkout_session_id": "cs_test_paid_order",
                "ordered_on": "2026-11-21",
                "buyer_name": "Ada Lovelace",
                "title": "Silas and the Wizard",
                "quantity": 1,
                "amount_cents": 4199,
                "stripe_fee_cents": 80,
                "currency": "USD",
            },
        )
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["id"], order["id"])
        self.assertEqual(home_quantity(), 1)

        shipped = self.client.post(
            f"/api/orders/{order['id']}/ship",
            json={
                "shipped_on": "2026-11-22",
                "from_location_id": locations["Home"],
                "tracking_number": "1Z999",
                "carrier": "UPS",
            },
        )
        self.assertEqual(shipped.status_code, 200, shipped.text)
        self.assertEqual(shipped.json()["ship_status"], "shipped")
        self.assertEqual(shipped.json()["tracking_number"], "1Z999")
        self.assertEqual(shipped.json()["stock_taken_at"], "payment")
        self.assertEqual(home_quantity(), 1)
        self.assertEqual(self.client.get("/api/inventory").json()["sales"][0]["quantity"], 1)

        unshipped = self.client.post(f"/api/orders/{order['id']}/unship")
        self.assertEqual(unshipped.status_code, 200, unshipped.text)
        self.assertEqual(unshipped.json()["ship_status"], "not_shipped")
        self.assertEqual(unshipped.json()["stock_taken_at"], "payment")
        self.assertEqual(home_quantity(), 1)


if __name__ == "__main__":
    unittest.main()
