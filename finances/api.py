from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, royalties
from .paths import STATIC_DIR, ensure_dirs

app = FastAPI(title="Wizard Hat Books Finances", version="0.1.0")


class ExpenseBody(BaseModel):
    spent_on: str
    payee: str
    category: str
    description: str = ""
    amount_cents: int
    currency: str = "USD"
    title: str = ""
    notes: str = ""
    payment_method: str = ""
    write_off_percent: int = 100


class ExpensePatch(BaseModel):
    spent_on: Optional[str] = None
    payee: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    amount_cents: Optional[int] = None
    currency: Optional[str] = None
    title: Optional[str] = None
    notes: Optional[str] = None
    payment_method: Optional[str] = None
    write_off_percent: Optional[int] = None


class ExpenseNameBody(BaseModel):
    name: str = ""


class ExpenseCategoryBody(BaseModel):
    label: str = ""


class RoyaltyBody(BaseModel):
    source: str
    period: str
    royalty_date: Optional[str] = None
    title: str
    author: str = ""
    product_id: str = ""
    marketplace: str = ""
    format: str = ""
    royalty_type: str = ""
    transaction_type: str = ""
    units_sold: Optional[int] = None
    units_refunded: Optional[int] = None
    net_units: Optional[int] = None
    kenp: Optional[int] = None
    amount_cents: Optional[int] = None
    currency: str = "USD"
    list_price_cents: Optional[int] = None
    offer_price_cents: Optional[int] = None
    wholesale_price_cents: Optional[int] = None
    print_cost_cents: Optional[int] = None
    notes: str = ""


class TitleBody(BaseModel):
    name: str
    notes: str = ""


class ReceiveBody(BaseModel):
    title_id: int
    location_id: int
    quantity: int = Field(gt=0)
    happened_on: str
    notes: str = ""


class MoveBody(BaseModel):
    title_id: int
    from_location_id: int
    to_location_id: int
    quantity: int = Field(gt=0)
    happened_on: str
    notes: str = ""


class SaleBody(BaseModel):
    title_id: int
    from_location_id: int
    channel_location_id: int
    quantity: int = Field(gt=0)
    happened_on: str
    unit_price_cents: Optional[int] = None
    currency: str = "USD"
    notes: str = ""


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(400, str(exc))


@app.on_event("startup")
def startup() -> None:
    ensure_dirs()
    db.init_db()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _reveal_in_file_manager(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", str(path)], check=True)
    elif sys.platform == "win32":
        subprocess.run(["explorer", f"/select,{path}"], check=True)
    else:
        subprocess.run(["xdg-open", str(path.parent)], check=True)


def _expense_page() -> dict[str, Any]:
    return {
        "expenses": db.list_expenses(),
        "totals": db.expense_totals(),
        "vendors": db.list_expense_vendors(),
        "categories": db.list_expense_categories(),
        "books": db.list_expense_books(),
    }


@app.get("/api/expenses")
def get_expenses() -> dict[str, Any]:
    return _expense_page()


@app.get("/api/expenses/{expense_id}")
def get_expense(expense_id: int) -> dict[str, Any]:
    try:
        return db.get_expense(expense_id)
    except ValueError as exc:
        raise _bad(exc) from exc


@app.post("/api/expenses")
def post_expense(body: ExpenseBody) -> dict[str, Any]:
    try:
        return db.create_expense(body.model_dump())
    except ValueError as exc:
        raise _bad(exc) from exc


@app.patch("/api/expenses/{expense_id}")
def patch_expense(expense_id: int, body: ExpensePatch) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    try:
        return db.update_expense(expense_id, fields)
    except ValueError as exc:
        raise _bad(exc) from exc


@app.delete("/api/expenses/{expense_id}")
def remove_expense(expense_id: int) -> dict[str, bool]:
    try:
        db.delete_expense(expense_id)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {"ok": True}


@app.post("/api/expense-vendors")
def post_expense_vendor(body: ExpenseNameBody) -> dict[str, Any]:
    try:
        vendor = db.add_expense_vendor(body.name)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {**_expense_page(), "vendor": vendor}


@app.delete("/api/expense-vendors/{vendor_id}")
def remove_expense_vendor(vendor_id: int) -> dict[str, Any]:
    try:
        db.delete_expense_vendor(vendor_id)
    except ValueError as exc:
        raise _bad(exc) from exc
    return _expense_page()


@app.post("/api/expense-categories")
def post_expense_category(body: ExpenseCategoryBody) -> dict[str, Any]:
    try:
        category = db.add_expense_category(body.label)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {**_expense_page(), "category": category}


@app.delete("/api/expense-categories/{category_id}")
def remove_expense_category(category_id: int) -> dict[str, Any]:
    try:
        db.delete_expense_category(category_id)
    except ValueError as exc:
        raise _bad(exc) from exc
    return _expense_page()


@app.post("/api/expense-books")
def post_expense_book(body: ExpenseNameBody) -> dict[str, Any]:
    try:
        book = db.add_expense_book(body.name)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {**_expense_page(), "book": book}


@app.post("/api/expenses/{expense_id}/attachments")
async def upload_expense_receipts(
    expense_id: int,
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    last: Optional[dict[str, Any]] = None
    saved = 0
    try:
        for upload in files:
            filename = upload.filename or "receipt.bin"
            suffix = Path(filename).suffix
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                shutil.copyfileobj(upload.file, tmp)
                tmp_path = Path(tmp.name)
            try:
                last = db.add_attachment(expense_id, tmp_path, filename, upload.content_type or "")
                saved += 1
            finally:
                tmp_path.unlink(missing_ok=True)
    except ValueError as exc:
        raise _bad(exc) from exc
    if not saved:
        raise _bad(ValueError("Attach at least one receipt or invoice."))
    return last or db.get_expense(expense_id)


@app.get("/api/expense-receipts/{attachment_id}")
def download_expense_receipt(attachment_id: int) -> FileResponse:
    try:
        att = db.get_attachment(attachment_id)
    except ValueError as exc:
        raise _bad(exc) from exc
    path = att["path"]
    if not path.is_file():
        raise HTTPException(404, "Receipt file is missing.")
    return FileResponse(
        path,
        filename=att["original_name"],
        media_type=att["mime_type"] or None,
        content_disposition_type="inline",
    )


@app.delete("/api/expense-receipts/{attachment_id}")
def remove_expense_receipt(attachment_id: int) -> dict[str, Any]:
    try:
        return db.delete_attachment(attachment_id)
    except ValueError as exc:
        raise _bad(exc) from exc


@app.post("/api/expense-receipts/{attachment_id}/reveal")
def reveal_expense_receipt(attachment_id: int) -> dict[str, Any]:
    try:
        att = db.get_attachment(attachment_id)
    except ValueError as exc:
        raise _bad(exc) from exc
    path = att["path"]
    if not path.is_file():
        raise HTTPException(404, "Receipt file is missing.")
    try:
        _reveal_in_file_manager(path)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HTTPException(500, f"Could not open Finder: {exc}") from exc
    return {"ok": True, "path": str(path)}


@app.get("/api/royalties")
def get_royalties(source: Optional[str] = None) -> dict[str, Any]:
    if source and source not in royalties.SOURCES:
        raise HTTPException(400, "Source must be kdp or ingramspark.")
    return {"entries": db.list_royalties(source), "totals": db.royalty_totals(source)}


@app.post("/api/royalties")
def post_royalty(body: RoyaltyBody) -> dict[str, Any]:
    try:
        return db.create_royalty(body.model_dump())
    except ValueError as exc:
        raise _bad(exc) from exc


@app.post("/api/royalties/import")
async def post_royalty_import(
    source: str = Form(...),
    period: str = Form(""),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "The file is empty.")
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(400, "File is larger than 20 MB.")
    try:
        rows = royalties.parse_report(raw, filename=file.filename or "", source=source, period=period)
        result = db.import_royalties(rows)
    except (ValueError, royalties.ImportError_) as exc:
        raise _bad(exc) from exc
    result["source"] = source
    return result


@app.delete("/api/royalties/batches/{batch_id}")
def remove_royalty_batch(batch_id: str) -> dict[str, int]:
    try:
        removed = db.delete_royalty_batch(batch_id)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {"removed": removed}


@app.delete("/api/royalties/{entry_id}")
def remove_royalty(entry_id: int) -> dict[str, bool]:
    try:
        db.delete_royalty(entry_id)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {"ok": True}


@app.get("/api/titles")
def get_titles() -> list[dict[str, Any]]:
    return db.list_titles()


@app.post("/api/titles")
def post_title(body: TitleBody) -> dict[str, Any]:
    try:
        return db.create_title(body.name, body.notes)
    except ValueError as exc:
        raise _bad(exc) from exc


@app.get("/api/locations")
def get_locations() -> list[dict[str, Any]]:
    return db.list_locations()


@app.get("/api/inventory")
def get_inventory() -> dict[str, Any]:
    return {
        "on_hand": db.inventory_snapshot(),
        "events": db.list_events(),
        "sales": db.sales_totals(),
        "titles": db.list_titles(),
        "locations": db.list_locations(),
    }


@app.post("/api/inventory/receive")
def post_receive(body: ReceiveBody) -> dict[str, Any]:
    try:
        return db.receive_copies(body.title_id, body.location_id, body.quantity, body.happened_on, body.notes)
    except ValueError as exc:
        raise _bad(exc) from exc


@app.post("/api/inventory/move")
def post_move(body: MoveBody) -> dict[str, Any]:
    try:
        return db.move_copies(
            body.title_id,
            body.from_location_id,
            body.to_location_id,
            body.quantity,
            body.happened_on,
            body.notes,
        )
    except ValueError as exc:
        raise _bad(exc) from exc


@app.post("/api/inventory/sale")
def post_sale(body: SaleBody) -> dict[str, Any]:
    try:
        return db.sell_copies(
            body.title_id,
            body.from_location_id,
            body.channel_location_id,
            body.quantity,
            body.happened_on,
            body.unit_price_cents,
            body.currency,
            body.notes,
        )
    except ValueError as exc:
        raise _bad(exc) from exc


@app.delete("/api/inventory/events/{event_id}")
def remove_event(event_id: int) -> dict[str, bool]:
    try:
        db.delete_event(event_id)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {"ok": True}


STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
