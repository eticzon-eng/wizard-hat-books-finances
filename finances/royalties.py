"""Parse Amazon KDP and IngramSpark royalty exports.

KDP downloads are either a CSV or the Royalties Estimator workbook. The
workbook's Combined Sales sheet is the one that already merges formats.
IngramSpark compensation emails and the sales-by-region CSV are both
accepted. The caller names the source; a file that looks like the other
platform is rejected so the two ledgers cannot be mixed by a mis-click.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Any, Iterable, Optional

SOURCES = ("kdp", "ingramspark")

KDP_HINTS = {
    "royalty date",
    "total earnings",
    "asin/isbn",
    "marketplace",
    "royalty type",
    "net units sold",
    "royalty",
}
INGRAM_HINTS = {
    "net compensation",
    "publisher compensation",
    "cost of printing",
    "printing cost",
    "quantity shipped",
    "compensation",
}


class ImportError_(ValueError):
    """A file cannot be imported. Named to avoid shadowing the builtin."""


def norm_header(value: str) -> str:
    text = value.replace("\ufeff", "").strip().lower().replace(".", "")
    text = text.replace("_", " ")
    return re.sub(r"\s+", " ", text)


def clean_product_id(value: str) -> str:
    text = value.strip()
    if text.lower().startswith("isbn"):
        text = text[4:].lstrip(" :")
    if text.startswith("="):
        text = text[1:].strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    if text.startswith("="):
        text = text[1:].strip().strip('"').strip("'")
    digits = re.sub(r"[^0-9Xx]", "", text)
    if len(digits) in (10, 13) and digits[:-1].isdigit():
        return digits.upper()
    return re.sub(r"\s+", "", text)


def parse_money_to_cents(value: str) -> Optional[int]:
    text = value.strip()
    if text == "" or text in {"-", "—", "–", "n/a", "N/A"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if text.startswith("-"):
        negative = True
    text = text.strip("()").lstrip("-").strip()
    text = text.replace("$", "").replace("£", "").replace("€", "").replace(",", "").strip()
    if text == "":
        return None
    cents = int(round(float(text) * 100))
    return -cents if negative else cents


def parse_int(value: str) -> Optional[int]:
    text = value.strip()
    if text == "" or text in {"-", "—", "–"}:
        return None
    number = float(text.replace(",", ""))
    if not number.is_integer():
        raise ImportError_(f"Expected a whole number of units, got {value!r}")
    return int(number)


def parse_iso_date(value: str) -> Optional[str]:
    text = value.strip()
    if text == "":
        return None
    formats = ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%m/%d/%y", "%d %b %Y", "%b %d, %Y", "%B %d, %Y")
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    # Excel sometimes stringifies datetimes as "2026-09-18 00:00:00"
    if len(text) >= 10 and re.match(r"\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    raise ImportError_(f"Could not read date {value!r}")


def parse_period(value: str) -> Optional[str]:
    text = value.strip()
    if text == "":
        return None
    month_match = re.fullmatch(r"(20\d{2})[-/](\d{1,2})", text)
    if month_match:
        month = int(month_match.group(2))
        if 1 <= month <= 12:
            return f"{month_match.group(1)}-{month:02d}"
    named = re.fullmatch(r"([A-Za-z]+)\s+(20\d{2})", text)
    if named:
        try:
            parsed = datetime.strptime(named.group(1)[:3] + " " + named.group(2), "%b %Y")
            return f"{parsed.year:04d}-{parsed.month:02d}"
        except ValueError as exc:
            raise ImportError_(f"Could not read period {value!r}") from exc
    try:
        iso = parse_iso_date(text)
    except ImportError_:
        iso = None
    if iso:
        return iso[:7]
    raise ImportError_(f"Could not read period {value!r}. Use YYYY-MM.")


def period_from_filename(name: str) -> Optional[str]:
    match = re.search(r"(20\d{2})[-_](\d{2})", name)
    if match and 1 <= int(match.group(2)) <= 12:
        return f"{match.group(1)}-{match.group(2)}"
    return None


def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.10f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return str(value)
    return str(value).strip()


def decode_csv_bytes(raw: bytes) -> str:
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff") or b"\x00" in raw[:200]:
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def _rows_from_csv(text: str) -> list[list[str]]:
    sample = text[:2000]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [row for row in reader if any(cell.strip() for cell in row)]


def _rows_from_xlsx(raw: bytes, source: str) -> list[list[str]]:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
    try:
        sheets = list(workbook.worksheets)
        if source == "kdp":
            for sheet in sheets:
                if sheet.title.strip().lower() == "combined sales":
                    return _sheet_rows(sheet)
        for sheet in sheets:
            rows = _sheet_rows(sheet)
            if rows and any(norm_header(cell) == "title" for cell in rows[0]):
                return rows
        return []
    finally:
        workbook.close()


def _sheet_rows(sheet: Any) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in sheet.iter_rows(values_only=True):
        cells = [_cell_str(cell) for cell in row]
        if any(cells):
            rows.append(cells)
    return rows


def load_table(raw: bytes, filename: str, source: str) -> list[list[str]]:
    lower = filename.lower()
    if lower.endswith(".xlsx") or raw[:2] == b"PK":
        return _rows_from_xlsx(raw, source)
    if lower.endswith(".xls"):
        raise ImportError_("This file is an old Excel .xls workbook. Save it as CSV or .xlsx and import that.")
    return _rows_from_csv(decode_csv_bytes(raw))


def _header_index(header: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for index, cell in enumerate(header):
        key = norm_header(cell)
        if key and key not in found:
            found[key] = index
    return found


def _get(row: list[str], index: dict[str, int], *names: str) -> str:
    for name in names:
        position = index.get(name)
        if position is not None and position < len(row):
            return row[position].strip()
    return ""


def looks_like_kdp(headers: Iterable[str]) -> bool:
    return bool(set(headers) & KDP_HINTS)


def looks_like_ingram(headers: Iterable[str]) -> bool:
    keys = set(headers)
    if keys & INGRAM_HINTS:
        return True
    return "isbn" in keys and "units sold" in keys and "royalty date" not in keys and "marketplace" not in keys


def parse_report(
    raw: bytes,
    *,
    filename: str,
    source: str,
    period: str = "",
) -> list[dict[str, Any]]:
    if source not in SOURCES:
        raise ImportError_("Source must be kdp or ingramspark.")
    rows = load_table(raw, filename, source)
    if not rows:
        raise ImportError_("The file has no rows.")
    header = _header_index(rows[0])
    if "title" not in header:
        raise ImportError_("No Title column found. Export the royalty or compensation report and try that file.")
    kdp = looks_like_kdp(header)
    ingram = looks_like_ingram(header)
    if source == "kdp" and ingram and not kdp:
        raise ImportError_("This file looks like an IngramSpark report. Import it on the IngramSpark side.")
    if source == "ingramspark" and kdp and not ingram:
        raise ImportError_("This file looks like an Amazon KDP report. Import it on the KDP side.")
    if source == "kdp" and not kdp:
        raise ImportError_(
            "This CSV does not look like a KDP royalty report. "
            "Use Royalties Estimator (Royalty Date, Title, Royalty) or Prior Month's Royalties (Total Earnings)."
        )
    if source == "ingramspark" and not ingram:
        raise ImportError_(
            "This CSV does not look like an IngramSpark report. "
            "Use the compensation report (Net Compensation) or sales by region (Title, ISBN, Units Sold)."
        )

    fallback_period = ""
    if period.strip():
        parsed = parse_period(period.strip())
        if not parsed:
            raise ImportError_("Report month must be YYYY-MM.")
        fallback_period = parsed
    elif period_from_filename(filename):
        fallback_period = period_from_filename(filename) or ""

    parsed_rows: list[dict[str, Any]] = []
    for line_number, row in enumerate(rows[1:], start=2):
        title = _get(row, header, "title", "book title")
        if title == "" or title.lower() in {"total", "totals", "grand total"}:
            continue
        try:
            parsed_rows.append(_parse_row(row, header, source, title, fallback_period))
        except ImportError_ as exc:
            raise ImportError_(f"Row {line_number}: {exc}") from exc
        except ValueError as exc:
            raise ImportError_(f"Row {line_number}: {exc}") from exc
    if not parsed_rows:
        raise ImportError_("The file has a header but no royalty rows.")
    return parsed_rows


def _infer_format(transaction_type: str, royalty_type: str, explicit: str) -> str:
    if explicit.strip():
        return explicit.strip()
    haystack = f"{transaction_type} {royalty_type}".lower()
    if "paperback" in haystack:
        return "Paperback"
    if "hardcover" in haystack or "hard cover" in haystack:
        return "Hardcover"
    if "audio" in haystack:
        return "Audiobook"
    if transaction_type.strip() or royalty_type.strip():
        return "Ebook"
    return ""


def _parse_row(
    row: list[str],
    header: dict[str, int],
    source: str,
    title: str,
    fallback_period: str,
) -> dict[str, Any]:
    royalty_date_raw = _get(row, header, "royalty date", "sale date", "order date", "date")
    royalty_date = parse_iso_date(royalty_date_raw) if royalty_date_raw else None
    period_raw = _get(row, header, "period", "sales period", "reporting period", "month")
    if period_raw:
        period = parse_period(period_raw)
    elif royalty_date:
        period = royalty_date[:7]
    elif fallback_period:
        period = fallback_period
    else:
        raise ImportError_("no date or period. Set the report month and import again.")
    if not period:
        raise ImportError_("no date or period. Set the report month and import again.")

    units_sold = parse_int(_get(row, header, "units sold", "quantity shipped", "qty shipped", "quantity"))
    units_refunded = parse_int(
        _get(row, header, "units refunded", "returns", "units returned", "quantity returned")
    )
    net_units = parse_int(_get(row, header, "net units sold", "net units", "net quantity"))
    if net_units is None and units_sold is not None:
        net_units = units_sold - (units_refunded or 0)

    if source == "kdp":
        amount_raw = _get(row, header, "royalty") or _get(row, header, "total earnings", "earnings", "estimated royalty")
    else:
        amount_raw = _get(
            row,
            header,
            "net compensation",
            "publisher compensation",
            "compensation",
            "net amount",
        )
    amount_cents = parse_money_to_cents(amount_raw) if amount_raw else None
    kenp = parse_int(_get(row, header, "kenp"))
    if net_units is None and amount_cents is None and kenp is None:
        raise ImportError_("no units, royalty, or compensation.")

    product_id = clean_product_id(
        _get(row, header, "asin/isbn", "asin", "isbn", "isbn-13", "isbn13", "ean")
    )
    transaction_type = _get(row, header, "transaction type")
    royalty_type = _get(row, header, "royalty type")
    explicit_format = _get(row, header, "format", "binding", "product type")
    marketplace = _get(row, header, "marketplace", "country", "market", "territory")
    currency = (_get(row, header, "currency") or "USD").upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ImportError_(f"currency {currency!r} is not a 3-letter code.")

    return {
        "source": source,
        "period": period,
        "royalty_date": royalty_date,
        "title": title,
        "author": _get(row, header, "author", "author name", "contributor", "contributors"),
        "product_id": product_id,
        "marketplace": marketplace,
        "format": _infer_format(transaction_type, royalty_type, explicit_format),
        "royalty_type": royalty_type,
        "transaction_type": transaction_type,
        "units_sold": units_sold,
        "units_refunded": units_refunded,
        "net_units": net_units,
        "kenp": kenp,
        "amount_cents": amount_cents,
        "currency": currency,
        "list_price_cents": _optional_money(row, header, "average list price without tax", "avg list price without tax"),
        "offer_price_cents": _optional_money(
            row, header, "average offer price without tax", "avg offer price without tax"
        ),
        "wholesale_price_cents": _optional_money(row, header, "wholesale price", "wholesale price of books sold"),
        "print_cost_cents": _optional_money(row, header, "print cost", "cost of printing", "printing cost", "manufacturing cost"),
    }


def _optional_money(row: list[str], header: dict[str, int], *names: str) -> Optional[int]:
    raw = _get(row, header, *names)
    if raw == "":
        return None
    return parse_money_to_cents(raw)
