"""Read a receipt, invoice, or bank screenshot into expense fields.

Unreadable fields stay blank. Nothing in this module writes an expense.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff", ".heic"}

FIELD_NAMES = (
    "spent_on",
    "payee",
    "amount",
    "currency",
    "category",
    "description",
    "payment_method",
    "title",
    "notes",
)

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_CATEGORY_HINTS = (
    ("Advertising", ("facebook ad", "instagram ad", "google ad", "meta ad", "advertising", " ads")),
    ("Software", ("software", "subscription", "adobe", "cursor", "photoshop", "saas")),
    ("Internet", ("internet", "spectrum", "cox", "broadband")),
    ("Mobile Phone", ("mobile phone", "cell phone", "verizon", "wireless")),
    ("Domain / web", ("domain", "cloudflare", "web hosting", "website hosting")),
    ("Printing", ("printing", "print job", "sticker")),
    ("Publishing", ("isbn", "bowker", "ingram", "publishing")),
    ("Shipping", ("shipping", "postage", "ups", "fedex", "usps")),
    ("Supplies", ("supplies", "office depot")),
    ("Utilities", ("electric", "utility", "utilities", "energy bill")),
    ("Professional services", ("consulting", "professional services", "reedsy", "editing")),
)

_BANKS = re.compile(
    r"\b(chase|bank of america|wells fargo|capital one|citibank|citi|pnc|truist)\b",
    re.IGNORECASE,
)
_HEADER = re.compile(
    r"^(receipt|invoice|statement|transaction|purchase|payment confirmation|thank you.*|page \d+.*)$",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_MDY_DATE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")
_MONTH_DATE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b",
    re.IGNORECASE,
)
_DMY_MONTH = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?,?\s+"
    r"(20\d{2})\b",
    re.IGNORECASE,
)
_MONEY = re.compile(
    r"(?P<sign>[-−(])?\s*"
    r"(?P<prefix>[$€£]|USD|EUR|GBP|CAD)?\s*"
    r"(?P<num>\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2})\)?\s*"
    r"(?P<suffix>USD|EUR|GBP|CAD)?",
    re.IGNORECASE,
)
_LABELED_PAYEE = re.compile(
    r"(?:merchant|payee|vendor|sold by|paid to)\s*[:\-]\s*(.+)",
    re.IGNORECASE,
)
_LABELED_DESCRIPTION = re.compile(
    r"(?:description|memo|item|product|details|for)\s*[:\-]\s*(.+)",
    re.IGNORECASE,
)
_NOTE = re.compile(
    r"\b((?:invoice|order|confirmation|reference|transaction(?:\s+id)?)"
    r"\s*(?:#|no\.?|number|code|id)?\s*[:#]?\s*[A-Z0-9][A-Z0-9-]{2,})\b",
    re.IGNORECASE,
)
_DATE_LINE = re.compile(r"\b(date|posted|transaction date|purchased)\b", re.IGNORECASE)
_TOTAL_LINE = re.compile(r"\btotal\b", re.IGNORECASE)
_SUBTOTAL_LINE = re.compile(r"\b(subtotal|tax|tip|fee)\b", re.IGNORECASE)
_AMOUNT_LINE = re.compile(
    r"\b(amount paid|amount due|amount|charged|you paid|debit|payment)\b",
    re.IGNORECASE,
)
_CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP"}


def empty_fields() -> dict[str, str]:
    return {name: "" for name in FIELD_NAMES}


def parse_receipt_text(
    text: str,
    *,
    vendors: list[str] | tuple[str, ...] = (),
    categories: list[str] | tuple[str, ...] = (),
    books: list[str] | tuple[str, ...] = (),
) -> dict[str, object]:
    """Turn OCR text into expense fields. Missing values are empty strings."""
    fields = empty_fields()
    cleaned = text.replace("\x00", " ")
    lines = [_clean_line(line) for line in cleaned.splitlines()]
    lines = [line for line in lines if line]
    if not lines and not cleaned.strip():
        return _with_filled(fields, recognized=False)

    fields["spent_on"] = _date(lines)
    amount, currency = _amount(lines)
    fields["amount"] = amount
    fields["currency"] = currency
    fields["payee"] = _payee(lines, vendors)
    fields["category"] = _category(cleaned, categories)
    fields["payment_method"] = _payment(lines)
    fields["title"] = _book(cleaned, books)
    fields["description"] = _description(lines, fields["payee"], fields["title"])
    fields["notes"] = _notes(cleaned)
    return _with_filled(fields, recognized=True)


def read_image(
    path: Path,
    *,
    vendors: list[str] | tuple[str, ...] = (),
    categories: list[str] | tuple[str, ...] = (),
    books: list[str] | tuple[str, ...] = (),
) -> dict[str, object]:
    text = ocr_image(path)
    if not text.strip():
        return _with_filled(empty_fields(), recognized=False)
    return parse_receipt_text(text, vendors=vendors, categories=categories, books=books)


def ocr_available() -> bool:
    return _ocr_binary() is not None and shutil.which("xcrun") is not None


def ocr_image(path: Path) -> str:
    binary = _ocr_binary()
    if binary is None:
        return ""
    try:
        result = subprocess.run(
            [str(binary), str(path)],
            capture_output=True,
            text=True,
            timeout=40,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout


def render_receipt_image(path: Path, text: str) -> None:
    binary = _ocr_binary()
    if binary is None:
        raise RuntimeError("Receipt OCR is not available on this computer.")
    result = subprocess.run(
        [str(binary), "--render", str(path), text],
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    if result.returncode != 0 or not path.is_file():
        raise RuntimeError(result.stderr.strip() or "Could not draw the receipt image.")


def _ocr_binary() -> Path | None:
    source = Path(__file__).with_name("ocr_receipt.swift")
    compiler = shutil.which("xcrun")
    if compiler is None or not source.is_file():
        return None
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    dest = Path(tempfile.gettempdir()) / "whb-finances" / f"ocr-receipt-{digest}"
    if dest.is_file():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    compiled = subprocess.run(
        ["xcrun", "swiftc", "-o", str(dest), str(source)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if compiled.returncode != 0 or not dest.is_file():
        return None
    return dest


def _with_filled(fields: dict[str, str], *, recognized: bool) -> dict[str, object]:
    filled = [name for name in FIELD_NAMES if fields[name]]
    return {**fields, "filled": filled, "recognized": recognized}


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _date(lines: list[str]) -> str:
    labeled = [line for line in lines if _DATE_LINE.search(line)]
    for line in labeled + lines:
        found = _date_in(line)
        if found:
            return found
    return ""


def _date_in(line: str) -> str:
    iso = _ISO_DATE.search(line)
    if iso:
        return _valid_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    month = _MONTH_DATE.search(line)
    if month:
        return _valid_date(int(month.group(3)), _MONTHS[month.group(1).lower()], int(month.group(2)))
    dmy = _DMY_MONTH.search(line)
    if dmy:
        return _valid_date(int(dmy.group(3)), _MONTHS[dmy.group(2).lower()], int(dmy.group(1)))
    numeric = _MDY_DATE.search(line)
    if numeric:
        month_n, day, year = int(numeric.group(1)), int(numeric.group(2)), int(numeric.group(3))
        if year < 100:
            year += 2000
        return _valid_date(year, month_n, day)
    return ""


def _valid_date(year: int, month: int, day: int) -> str:
    if year < 1990 or year > 2100 or not 1 <= month <= 12 or not 1 <= day <= 31:
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def _amount(lines: list[str]) -> tuple[str, str]:
    totals = [
        line
        for line in lines
        if _TOTAL_LINE.search(line) and not _SUBTOTAL_LINE.search(line)
    ]
    labeled = [
        line
        for line in lines
        if _AMOUNT_LINE.search(line) and not _SUBTOTAL_LINE.search(line)
    ]
    fallback = [
        line
        for line in reversed(lines)
        if not _SUBTOTAL_LINE.search(line)
    ]
    chosen = ""
    currency = ""
    for group in (totals, labeled, fallback):
        for line in group:
            match = _best_money(line)
            if match is None:
                continue
            chosen = _money_number(match)
            currency = _money_currency(match)
            if chosen:
                break
        if chosen:
            break
    if chosen and not currency:
        currency = _document_currency(lines)
    return chosen, currency


def _best_money(line: str) -> re.Match[str] | None:
    matches = list(_MONEY.finditer(line))
    return matches[-1] if matches else None


def _money_number(match: re.Match[str]) -> str:
    number = match.group("num").replace(",", "")
    if "." not in number:
        return ""
    whole, cents = number.split(".", 1)
    if not whole.isdigit() or len(cents) != 2:
        return ""
    return f"{int(whole)}.{cents}"


def _money_currency(match: re.Match[str]) -> str:
    prefix = (match.group("prefix") or "").upper()
    suffix = (match.group("suffix") or "").upper()
    if prefix in _CURRENCY:
        return _CURRENCY[prefix]
    if prefix in {"USD", "EUR", "GBP", "CAD"}:
        return prefix
    if suffix in {"USD", "EUR", "GBP", "CAD"}:
        return suffix
    return ""


def _document_currency(lines: list[str]) -> str:
    seen: list[str] = []
    for line in lines:
        for match in _MONEY.finditer(line):
            code = _money_currency(match)
            if code and code not in seen:
                seen.append(code)
        if "$" in line and "USD" not in seen:
            seen.append("USD")
        if "€" in line and "EUR" not in seen:
            seen.append("EUR")
        if "£" in line and "GBP" not in seen:
            seen.append("GBP")
    if len(seen) == 1:
        return seen[0]
    return ""


def _payee(lines: list[str], vendors: list[str] | tuple[str, ...]) -> str:
    blob = "\n".join(lines)
    known = [name.strip() for name in vendors if _contains_name(blob, name.strip())]
    if known:
        return max(known, key=len)
    for line in lines:
        labeled = _LABELED_PAYEE.search(line)
        if labeled:
            value = labeled.group(1).strip(" -:")
            if _looks_like_name(value):
                return value[:80]
    if not any(_date_in(line) or _best_money(line) for line in lines):
        return ""
    for line in lines:
        if _skip_payee_line(line):
            continue
        if _looks_like_name(line):
            return line[:80]
    return ""


def _contains_name(text: str, name: str) -> bool:
    if len(name) < 4:
        return False
    if len(name) < 6:
        return re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE) is not None
    return name.casefold() in text.casefold()


def _looks_like_name(line: str) -> bool:
    if _HEADER.match(line) or _date_in(line) or _best_money(line):
        return False
    letters = sum(character.isalpha() for character in line)
    return 2 <= len(line) <= 80 and letters >= 2


def _skip_payee_line(line: str) -> bool:
    if _HEADER.match(line) or _DATE_LINE.search(line) or _TOTAL_LINE.search(line):
        return True
    if _AMOUNT_LINE.search(line) or _SUBTOTAL_LINE.search(line) or _BANKS.search(line):
        return True
    if _LABELED_DESCRIPTION.search(line) or _NOTE.search(line) or _payment_line(line):
        return True
    return False


def _category(text: str, categories: list[str] | tuple[str, ...]) -> str:
    labels = [label.strip() for label in categories if label.strip()]
    folded = f" {text.casefold()} "
    for label, keys in _CATEGORY_HINTS:
        if label not in labels:
            continue
        if any(key in folded for key in keys):
            return label
    for label in labels:
        if label.casefold() == "other":
            continue
        if _contains_name(text, label):
            return label
    return ""


def _description(lines: list[str], payee: str, title: str) -> str:
    for line in lines:
        labeled = _LABELED_DESCRIPTION.search(line)
        if not labeled:
            continue
        value = labeled.group(1).strip()
        if value and value.casefold() not in {payee.casefold(), title.casefold()}:
            return value[:140]
    if not any(_date_in(line) or _best_money(line) for line in lines):
        return ""
    for line in lines:
        if _skip_payee_line(line) or not _looks_like_name(line):
            continue
        if payee and payee.casefold() in line.casefold():
            continue
        if title and line.casefold() == title.casefold():
            continue
        return line[:140]
    return ""


def _payment(lines: list[str]) -> str:
    for line in lines:
        if _payment_line(line) and len(line) <= 60:
            return line
    return ""


def _payment_line(line: str) -> bool:
    return re.search(
        r"\b(visa|mastercard|master\s*card|amex|american express|discover|"
        r"paypal|apple pay|google pay|venmo|debit|credit card|checking|ach)\b",
        line,
        re.IGNORECASE,
    ) is not None


def _book(text: str, books: list[str] | tuple[str, ...]) -> str:
    hits = [name.strip() for name in books if _contains_name(text, name.strip())]
    hits = [name for name in hits if name.casefold() != "general"]
    if not hits:
        return ""
    return max(hits, key=len)


def _notes(text: str) -> str:
    match = _NOTE.search(text)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()[:160]
