from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from .paths import DATA_DIR, ROOT, ensure_dirs, db_path

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spent_on TEXT NOT NULL,
    payee TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    title TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS royalty_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL CHECK(source IN ('kdp', 'ingramspark')),
    period TEXT NOT NULL,
    royalty_date TEXT,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    product_id TEXT NOT NULL DEFAULT '',
    marketplace TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT '',
    royalty_type TEXT NOT NULL DEFAULT '',
    transaction_type TEXT NOT NULL DEFAULT '',
    units_sold INTEGER,
    units_refunded INTEGER,
    net_units INTEGER,
    kenp INTEGER,
    amount_cents INTEGER,
    currency TEXT NOT NULL DEFAULT 'USD',
    list_price_cents INTEGER,
    offer_price_cents INTEGER,
    wholesale_price_cents INTEGER,
    print_cost_cents INTEGER,
    notes TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'manual',
    batch_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS titles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'store',
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS inventory_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title_id INTEGER NOT NULL REFERENCES titles(id),
    kind TEXT NOT NULL CHECK(kind IN ('receive', 'move', 'sale')),
    from_location_id INTEGER REFERENCES locations(id),
    to_location_id INTEGER REFERENCES locations(id),
    channel_location_id INTEGER REFERENCES locations(id),
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    happened_on TEXT NOT NULL,
    unit_price_cents INTEGER,
    currency TEXT NOT NULL DEFAULT 'USD',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_royalties_source ON royalty_entries(source, period);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(spent_on);
CREATE INDEX IF NOT EXISTS idx_events_title ON inventory_events(title_id, happened_on);
"""

SEEDED_LOCATIONS = (
    ("Home", "home", 0),
    ("InkFish Books", "store", 1),
    ("Barrington Books", "store", 2),
    ("TikTok Shop", "shop", 3),
)


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    ensure_dirs()
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        for name, kind, sort_order in SEEDED_LOCATIONS:
            conn.execute(
                """
                INSERT INTO locations (name, kind, sort_order)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET kind = excluded.kind, sort_order = excluded.sort_order
                """,
                (name, kind, sort_order),
            )
    _load_expense_seed_if_empty()


def _require_currency(currency: str) -> str:
    code = (currency or "USD").strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError("Currency must be a 3-letter code such as USD.")
    return code


def _require_date(value: str, label: str) -> str:
    text = (value or "").strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD.") from exc
    return text


def _require_period(value: str) -> str:
    text = (value or "").strip()
    try:
        datetime.strptime(text + "-01", "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Period must be YYYY-MM.") from exc
    return text


# --- Expenses ---


def list_expenses() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM expenses ORDER BY spent_on DESC, id DESC").fetchall()
        return [_row(row) for row in rows]


def expense_totals() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT currency, SUM(amount_cents) AS amount_cents, COUNT(*) AS count
            FROM expenses
            GROUP BY currency
            ORDER BY currency
            """
        ).fetchall()
        return [_row(row) for row in rows]


def _expense_from_fields(fields: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if not partial or "spent_on" in fields:
        data["spent_on"] = _require_date(str(fields.get("spent_on", "")), "Date")
    if not partial or "payee" in fields:
        payee = str(fields.get("payee", "")).strip()
        if not payee:
            raise ValueError("Payee is required.")
        data["payee"] = payee
    if not partial or "category" in fields:
        category = str(fields.get("category", "")).strip()
        if not category:
            raise ValueError("Category is required.")
        data["category"] = category
    if not partial or "description" in fields:
        data["description"] = str(fields.get("description", "") or "").strip()
    if not partial or "amount_cents" in fields:
        if fields.get("amount_cents") is None:
            raise ValueError("Amount is required.")
        data["amount_cents"] = int(fields["amount_cents"])
    if not partial or "currency" in fields:
        data["currency"] = _require_currency(str(fields.get("currency", "USD")))
    if not partial or "title" in fields:
        data["title"] = str(fields.get("title", "") or "").strip()
    if not partial or "notes" in fields:
        data["notes"] = str(fields.get("notes", "") or "").strip()
    return data


_EXPENSE_INSERT = """
INSERT INTO expenses (
    spent_on, payee, category, description, amount_cents, currency, title, notes, created_at
) VALUES (
    :spent_on, :payee, :category, :description, :amount_cents, :currency, :title, :notes, :created_at
)
"""


def _expense_seed_path():
    return ROOT / "seeds" / "expenses.json"


def create_expense(fields: dict[str, Any]) -> dict[str, Any]:
    return create_expenses([fields])[0]


def create_expenses(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared = []
    for fields in rows:
        data = _expense_from_fields(fields, partial=False)
        data["created_at"] = utcnow()
        prepared.append(data)
    created: list[dict[str, Any]] = []
    with connect() as conn:
        for data in prepared:
            cur = conn.execute(_EXPENSE_INSERT, data)
            row = conn.execute("SELECT * FROM expenses WHERE id = ?", (cur.lastrowid,)).fetchone()
            created.append(_row(row))
    return created


def _load_expense_seed_if_empty() -> None:
    """Load the committed library ledger into a new default database.

    Test databases and any FINANCES_DB override stay empty until records are entered.
    """
    if db_path().resolve() != (DATA_DIR / "finances.db").resolve():
        return
    seed_path = _expense_seed_path()
    if not seed_path.is_file():
        return
    with connect() as conn:
        existing = int(conn.execute("SELECT COUNT(*) AS n FROM expenses").fetchone()["n"])
    if existing:
        return
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        return
    create_expenses(payload)


def update_expense(expense_id: int, fields: dict[str, Any]) -> dict[str, Any]:
    data = _expense_from_fields(fields, partial=True)
    if not data:
        raise ValueError("Nothing to update.")
    assignments = ", ".join(f"{key} = :{key}" for key in data)
    data["id"] = expense_id
    with connect() as conn:
        cur = conn.execute(f"UPDATE expenses SET {assignments} WHERE id = :id", data)
        if cur.rowcount == 0:
            raise ValueError("Expense not found.")
        row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        return _row(row)


def delete_expense(expense_id: int) -> None:
    with connect() as conn:
        cur = conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        if cur.rowcount == 0:
            raise ValueError("Expense not found.")


# --- Royalties ---


def list_royalties(source: Optional[str] = None) -> list[dict[str, Any]]:
    with connect() as conn:
        if source:
            rows = conn.execute(
                "SELECT * FROM royalty_entries WHERE source = ? ORDER BY period DESC, royalty_date DESC, id DESC",
                (source,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM royalty_entries ORDER BY source, period DESC, royalty_date DESC, id DESC"
            ).fetchall()
        return [_row(row) for row in rows]


def royalty_totals(source: Optional[str] = None) -> dict[str, list[dict[str, Any]]]:
    where = ""
    params: tuple[Any, ...] = ()
    if source:
        where = "WHERE source = ?"
        params = (source,)
    with connect() as conn:
        by_source = conn.execute(
            f"""
            SELECT source, currency,
                   SUM(amount_cents) AS amount_cents,
                   SUM(net_units) AS net_units,
                   SUM(kenp) AS kenp,
                   COUNT(*) AS count,
                   SUM(CASE WHEN amount_cents IS NULL THEN 1 ELSE 0 END) AS missing_amount
            FROM royalty_entries
            {where}
            GROUP BY source, currency
            ORDER BY source, currency
            """,
            params,
        ).fetchall()
        by_title = conn.execute(
            f"""
            SELECT source, title, currency,
                   SUM(amount_cents) AS amount_cents,
                   SUM(net_units) AS net_units,
                   SUM(kenp) AS kenp,
                   COUNT(*) AS count
            FROM royalty_entries
            {where}
            GROUP BY source, title, currency
            ORDER BY source, title, currency
            """,
            params,
        ).fetchall()
        by_period = conn.execute(
            f"""
            SELECT source, period, currency,
                   SUM(amount_cents) AS amount_cents,
                   SUM(net_units) AS net_units,
                   SUM(kenp) AS kenp,
                   COUNT(*) AS count
            FROM royalty_entries
            {where}
            GROUP BY source, period, currency
            ORDER BY source, period DESC, currency
            """,
            params,
        ).fetchall()
    return {
        "by_source": [_row(row) for row in by_source],
        "by_title": [_row(row) for row in by_title],
        "by_period": [_row(row) for row in by_period],
    }


def _royalty_record(fields: dict[str, Any], *, origin: str, batch_id: Optional[str]) -> dict[str, Any]:
    source = str(fields.get("source", "")).strip()
    if source not in {"kdp", "ingramspark"}:
        raise ValueError("Source must be kdp or ingramspark.")
    title = str(fields.get("title", "")).strip()
    if not title:
        raise ValueError("Title is required.")
    period = _require_period(str(fields.get("period", "")))
    royalty_date = fields.get("royalty_date") or None
    if royalty_date:
        royalty_date = _require_date(str(royalty_date), "Royalty date")
    net_units = fields.get("net_units")
    amount = fields.get("amount_cents")
    kenp = fields.get("kenp")
    if net_units is None and amount is None and kenp is None:
        raise ValueError("Enter net units, a royalty amount, or both.")
    return {
        "source": source,
        "period": period,
        "royalty_date": royalty_date,
        "title": title,
        "author": str(fields.get("author") or "").strip(),
        "product_id": str(fields.get("product_id") or "").strip(),
        "marketplace": str(fields.get("marketplace") or "").strip(),
        "format": str(fields.get("format") or "").strip(),
        "royalty_type": str(fields.get("royalty_type") or "").strip(),
        "transaction_type": str(fields.get("transaction_type") or "").strip(),
        "units_sold": fields.get("units_sold"),
        "units_refunded": fields.get("units_refunded"),
        "net_units": net_units,
        "kenp": kenp,
        "amount_cents": amount,
        "currency": _require_currency(str(fields.get("currency") or "USD")),
        "list_price_cents": fields.get("list_price_cents"),
        "offer_price_cents": fields.get("offer_price_cents"),
        "wholesale_price_cents": fields.get("wholesale_price_cents"),
        "print_cost_cents": fields.get("print_cost_cents"),
        "notes": str(fields.get("notes") or "").strip(),
        "origin": origin,
        "batch_id": batch_id,
        "created_at": utcnow(),
    }


_ROYALTY_INSERT = """
INSERT INTO royalty_entries (
    source, period, royalty_date, title, author, product_id, marketplace, format,
    royalty_type, transaction_type, units_sold, units_refunded, net_units, kenp,
    amount_cents, currency, list_price_cents, offer_price_cents, wholesale_price_cents,
    print_cost_cents, notes, origin, batch_id, created_at
) VALUES (
    :source, :period, :royalty_date, :title, :author, :product_id, :marketplace, :format,
    :royalty_type, :transaction_type, :units_sold, :units_refunded, :net_units, :kenp,
    :amount_cents, :currency, :list_price_cents, :offer_price_cents, :wholesale_price_cents,
    :print_cost_cents, :notes, :origin, :batch_id, :created_at
)
"""


def create_royalty(fields: dict[str, Any]) -> dict[str, Any]:
    data = _royalty_record(fields, origin="manual", batch_id=None)
    with connect() as conn:
        cur = conn.execute(_ROYALTY_INSERT, data)
        row = conn.execute("SELECT * FROM royalty_entries WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row(row)


def import_royalties(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("Nothing to import.")
    batch_id = uuid.uuid4().hex
    records = [_royalty_record(row, origin="csv", batch_id=batch_id) for row in rows]
    with connect() as conn:
        ids: list[int] = []
        skipped = 0
        for record in records:
            existing = conn.execute(
                """
                SELECT id FROM royalty_entries
                WHERE source = :source AND period = :period AND title = :title
                  AND product_id = :product_id AND marketplace = :marketplace
                  AND currency = :currency AND format = :format
                  AND ifnull(transaction_type, '') = ifnull(:transaction_type, '')
                  AND ((royalty_date IS NULL AND :royalty_date IS NULL) OR royalty_date = :royalty_date)
                  AND ((net_units IS NULL AND :net_units IS NULL) OR net_units = :net_units)
                  AND ((amount_cents IS NULL AND :amount_cents IS NULL) OR amount_cents = :amount_cents)
                """,
                record,
            ).fetchone()
            if existing:
                skipped += 1
                continue
            cur = conn.execute(_ROYALTY_INSERT, record)
            ids.append(int(cur.lastrowid))
    return {"imported": len(ids), "skipped": skipped, "ids": ids, "batch_id": batch_id if ids else None}


def delete_royalty(entry_id: int) -> None:
    with connect() as conn:
        cur = conn.execute("DELETE FROM royalty_entries WHERE id = ?", (entry_id,))
        if cur.rowcount == 0:
            raise ValueError("Royalty entry not found.")


def delete_royalty_batch(batch_id: str) -> int:
    with connect() as conn:
        cur = conn.execute("DELETE FROM royalty_entries WHERE batch_id = ?", (batch_id,))
        if cur.rowcount == 0:
            raise ValueError("Import batch not found.")
        return int(cur.rowcount)


# --- Inventory ---


def list_locations() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM locations ORDER BY sort_order, name").fetchall()
        return [_row(row) for row in rows]


def list_titles() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM titles ORDER BY name").fetchall()
        return [_row(row) for row in rows]


def create_title(name: str, notes: str = "") -> dict[str, Any]:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Title is required.")
    with connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO titles (name, notes, created_at) VALUES (?, ?, ?)",
                (cleaned, notes.strip(), utcnow()),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"{cleaned} is already in the inventory.") from exc
        row = conn.execute("SELECT * FROM titles WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row(row)


def _location(conn: sqlite3.Connection, location_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM locations WHERE id = ?", (location_id,)).fetchone()
    if row is None:
        raise ValueError("Location not found.")
    return row


def _title(conn: sqlite3.Connection, title_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM titles WHERE id = ?", (title_id,)).fetchone()
    if row is None:
        raise ValueError("Title not found.")
    return row


def _events(conn: sqlite3.Connection, title_id: Optional[int] = None) -> list[sqlite3.Row]:
    if title_id is None:
        return list(conn.execute("SELECT * FROM inventory_events ORDER BY happened_on, id").fetchall())
    return list(
        conn.execute(
            "SELECT * FROM inventory_events WHERE title_id = ? ORDER BY happened_on, id",
            (title_id,),
        ).fetchall()
    )


def _apply_balances(events: list[dict[str, Any]], names: dict[int, str], title_names: dict[int, str]) -> dict[tuple[int, int], int]:
    balances: dict[tuple[int, int], int] = {}
    ordered = sorted(events, key=lambda event: (event["happened_on"], event["id"]))
    for event in ordered:
        title_id = int(event["title_id"])
        qty = int(event["quantity"])
        kind = event["kind"]
        if kind == "receive":
            key = (title_id, int(event["to_location_id"]))
            balances[key] = balances.get(key, 0) + qty
        elif kind == "move":
            source = (title_id, int(event["from_location_id"]))
            dest = (title_id, int(event["to_location_id"]))
            balances[source] = balances.get(source, 0) - qty
            balances[dest] = balances.get(dest, 0) + qty
        elif kind == "sale":
            source = (title_id, int(event["from_location_id"]))
            balances[source] = balances.get(source, 0) - qty
        else:
            raise ValueError(f"Unknown inventory event {kind}.")
        for (tid, loc_id), on_hand in balances.items():
            if on_hand < 0:
                raise ValueError(
                    f"Not enough copies of {title_names.get(tid, 'that title')} "
                    f"at {names.get(loc_id, 'that location')}."
                )
    return balances


def _project(conn: sqlite3.Connection, extra: Optional[dict[str, Any]] = None, skip_id: Optional[int] = None) -> None:
    titles = {int(row["id"]): row["name"] for row in conn.execute("SELECT id, name FROM titles")}
    locations = {int(row["id"]): row["name"] for row in conn.execute("SELECT id, name FROM locations")}
    events = [_row(row) for row in _events(conn) if skip_id is None or int(row["id"]) != skip_id]
    if extra is not None:
        events.append(extra)
    _apply_balances(events, locations, titles)


def inventory_snapshot() -> list[dict[str, Any]]:
    with connect() as conn:
        titles = list(conn.execute("SELECT * FROM titles ORDER BY name"))
        locations = list(conn.execute("SELECT * FROM locations ORDER BY sort_order, name"))
        events = [_row(row) for row in _events(conn)]
        title_names = {int(row["id"]): row["name"] for row in titles}
        location_names = {int(row["id"]): row["name"] for row in locations}
        balances = _apply_balances(events, location_names, title_names) if events else {}
        rows = []
        for title in titles:
            for location in locations:
                rows.append(
                    {
                        "title_id": title["id"],
                        "title": title["name"],
                        "location_id": location["id"],
                        "location": location["name"],
                        "quantity": balances.get((int(title["id"]), int(location["id"])), 0),
                    }
                )
        return rows


def sales_totals() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT l.name AS channel, e.currency,
                   SUM(e.quantity) AS quantity,
                   SUM(CASE WHEN e.unit_price_cents IS NULL THEN 0 ELSE e.quantity * e.unit_price_cents END) AS amount_cents,
                   SUM(CASE WHEN e.unit_price_cents IS NULL THEN 1 ELSE 0 END) AS missing_price
            FROM inventory_events e
            JOIN locations l ON l.id = e.channel_location_id
            WHERE e.kind = 'sale'
            GROUP BY l.name, e.currency
            ORDER BY l.sort_order, e.currency
            """
        ).fetchall()
        return [_row(row) for row in rows]


def list_events() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT e.*, t.name AS title,
                   src.name AS from_location,
                   dst.name AS to_location,
                   ch.name AS channel
            FROM inventory_events e
            JOIN titles t ON t.id = e.title_id
            LEFT JOIN locations src ON src.id = e.from_location_id
            LEFT JOIN locations dst ON dst.id = e.to_location_id
            LEFT JOIN locations ch ON ch.id = e.channel_location_id
            ORDER BY e.happened_on DESC, e.id DESC
            """
        ).fetchall()
        return [_row(row) for row in rows]


def _next_event_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT ifnull(MAX(id), 0) + 1 AS next_id FROM inventory_events").fetchone()
    return int(row["next_id"])


def receive_copies(title_id: int, location_id: int, quantity: int, happened_on: str, notes: str = "") -> dict[str, Any]:
    if quantity < 1:
        raise ValueError("Quantity must be at least 1.")
    happened_on = _require_date(happened_on, "Date")
    with connect() as conn:
        _title(conn, title_id)
        location = _location(conn, location_id)
        event = {
            "id": _next_event_id(conn),
            "title_id": title_id,
            "kind": "receive",
            "from_location_id": None,
            "to_location_id": location_id,
            "channel_location_id": None,
            "quantity": quantity,
            "happened_on": happened_on,
        }
        _project(conn, extra=event)
        cur = conn.execute(
            """
            INSERT INTO inventory_events (
                title_id, kind, to_location_id, quantity, happened_on, notes, currency, created_at
            ) VALUES (?, 'receive', ?, ?, ?, ?, 'USD', ?)
            """,
            (title_id, location_id, quantity, happened_on, notes.strip(), utcnow()),
        )
        return _event_by_id(conn, int(cur.lastrowid), received_at=location["name"])


def move_copies(
    title_id: int,
    from_location_id: int,
    to_location_id: int,
    quantity: int,
    happened_on: str,
    notes: str = "",
) -> dict[str, Any]:
    if quantity < 1:
        raise ValueError("Quantity must be at least 1.")
    if from_location_id == to_location_id:
        raise ValueError("Pick two different locations.")
    happened_on = _require_date(happened_on, "Date")
    with connect() as conn:
        _title(conn, title_id)
        _location(conn, from_location_id)
        _location(conn, to_location_id)
        event = {
            "id": _next_event_id(conn),
            "title_id": title_id,
            "kind": "move",
            "from_location_id": from_location_id,
            "to_location_id": to_location_id,
            "channel_location_id": None,
            "quantity": quantity,
            "happened_on": happened_on,
        }
        _project(conn, extra=event)
        cur = conn.execute(
            """
            INSERT INTO inventory_events (
                title_id, kind, from_location_id, to_location_id, quantity, happened_on, notes, currency, created_at
            ) VALUES (?, 'move', ?, ?, ?, ?, ?, 'USD', ?)
            """,
            (title_id, from_location_id, to_location_id, quantity, happened_on, notes.strip(), utcnow()),
        )
        return _event_by_id(conn, int(cur.lastrowid))


def sell_copies(
    title_id: int,
    from_location_id: int,
    channel_location_id: int,
    quantity: int,
    happened_on: str,
    unit_price_cents: Optional[int] = None,
    currency: str = "USD",
    notes: str = "",
) -> dict[str, Any]:
    if quantity < 1:
        raise ValueError("Quantity must be at least 1.")
    happened_on = _require_date(happened_on, "Date")
    currency = _require_currency(currency)
    with connect() as conn:
        _title(conn, title_id)
        _location(conn, from_location_id)
        _location(conn, channel_location_id)
        event = {
            "id": _next_event_id(conn),
            "title_id": title_id,
            "kind": "sale",
            "from_location_id": from_location_id,
            "to_location_id": None,
            "channel_location_id": channel_location_id,
            "quantity": quantity,
            "happened_on": happened_on,
        }
        _project(conn, extra=event)
        cur = conn.execute(
            """
            INSERT INTO inventory_events (
                title_id, kind, from_location_id, channel_location_id, quantity,
                happened_on, unit_price_cents, currency, notes, created_at
            ) VALUES (?, 'sale', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title_id,
                from_location_id,
                channel_location_id,
                quantity,
                happened_on,
                unit_price_cents,
                currency,
                notes.strip(),
                utcnow(),
            ),
        )
        return _event_by_id(conn, int(cur.lastrowid))


def _event_by_id(conn: sqlite3.Connection, event_id: int, received_at: str = "") -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT e.*, t.name AS title,
               src.name AS from_location,
               dst.name AS to_location,
               ch.name AS channel
        FROM inventory_events e
        JOIN titles t ON t.id = e.title_id
        LEFT JOIN locations src ON src.id = e.from_location_id
        LEFT JOIN locations dst ON dst.id = e.to_location_id
        LEFT JOIN locations ch ON ch.id = e.channel_location_id
        WHERE e.id = ?
        """,
        (event_id,),
    ).fetchone()
    data = _row(row)
    if received_at and not data.get("to_location"):
        data["to_location"] = received_at
    return data


def delete_event(event_id: int) -> None:
    with connect() as conn:
        row = conn.execute("SELECT id FROM inventory_events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            raise ValueError("Inventory event not found.")
        _project(conn, skip_id=event_id)
        conn.execute("DELETE FROM inventory_events WHERE id = ?", (event_id,))
