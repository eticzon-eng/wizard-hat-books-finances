"""Read a receipt, invoice, or bank screenshot into expense fields.

Unreadable fields stay blank. Nothing in this module writes an expense.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from datetime import date
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

_HIGHLIGHT = "[[highlight]]"
_HOMOGLYPHS = str.maketrans({
    "А": "A",
    "а": "a",
    "В": "B",
    "Е": "E",
    "е": "e",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "о": "o",
    "Р": "P",
    "р": "p",
    "С": "C",
    "с": "c",
    "Т": "T",
    "Х": "X",
    "х": "x",
    "у": "y",
})
_CATEGORY_HINTS = (
    ("Advertising", ("facebook", "facebk", "instagram", "tiktok", "tik tok", "google ad", "meta ad", "advertising", " ads")),
    ("Software", ("software", "subscription", "adobe", "cursor", "photoshop", "vellum", "prowriting", "techsmith")),
    ("Internet", ("internet", "spectrum", "cox", "broadband")),
    ("Mobile Phone", ("mobile phone", "cell phone", "verizon", "wireless")),
    ("Domain / web", ("domain", "cloudflare", "web hosting", "website hosting")),
    ("Printing", ("printing", "print job", "sticker")),
    ("Publishing", ("isbn", "bowker", "ingram", "publishing")),
    ("Shipping", ("shipping", "postage", "ups", "fedex", "usps")),
    ("Supplies", ("supplies", "office depot")),
    ("Utilities", ("electric", "utility", "utilities", "energy")),
    ("Professional services", ("consulting", "professional services", "reedsy", "editing")),
)
_VENDOR_ALIASES = (
    ("meta", ("facebook", "facebk")),
    ("cursor", ("cursor",)),
    ("tiktok", ("tiktok", "tik tok")),
    ("cox", ("cox communications", "spectrum")),
    ("verizon", ("verizon",)),
    ("prowriting", ("prowritingaid",)),
    ("paddle", ("paddle", "vellum")),
    ("reedsy", ("reedsy",)),
    ("cloudflare", ("cloudflare",)),
    ("amazon", ("amazon",)),
    ("sticker", ("sticker mule",)),
    ("bowker", ("bowker",)),
    ("zeely", ("zeely",)),
    ("techsmith", ("techsmith",)),
    ("ingram", ("ingram",)),
    ("goodreads", ("goodreads",)),
    ("revvue", ("revvue",)),
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
    r"(\d{1,2})(?:st|nd|rd|th)?,?\s*(20\d{2})\b",
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
    r"(?P<prefix>(?:US\s*)?[$€£]|USD|EUR|GBP|CAD)?\s*"
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
    r"\b((?:invoice|order|confirmation|reference|collaboration|transaction(?:\s+id)?)"
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
_SKIP_AMOUNT = re.compile(
    r"reward|cash back|you earned|subtotal|\btax\b|\bfee\b|\bbalance\b",
    re.IGNORECASE,
)
_PAYMENT_PHRASE = re.compile(
    r"\b(bill payment|electronic transfer|debit card(?: purchase)?|credit card|"
    r"apple pay|google pay|paypal|venmo|visa(?: debit)?|mastercard|american express|"
    r"purchase|merchandise|auto pay|ach)\b",
    re.IGNORECASE,
)
_STATEMENT_AS = re.compile(r"statement as:\s*(.+)", re.IGNORECASE)
_POSTED = re.compile(r"\bposted\b", re.IGNORECASE)
_BILLING = re.compile(r"\bbilling date\b", re.IGNORECASE)
_RECEIVED = re.compile(r"\bpayment received\b", re.IGNORECASE)
_STATEMENT_ENDING = re.compile(r"\bstatement ending\b", re.IGNORECASE)
_PURCHASED = re.compile(r"\bpurchased\b", re.IGNORECASE)
_TOTAL_LINE_WORD = re.compile(r"\btotal\b|your order", re.IGNORECASE)
_HEADER_LINE = re.compile(
    r"\b(date|description|amount|category|balance)\b",
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
    lines = [_clean_line(line.translate(_HOMOGLYPHS)) for line in text.replace("\x00", " ").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return _with_filled(empty_fields(), recognized=False, highlighted=False)
    lines = _join_visual_rows(lines)
    highlighted = [_plain_line(line) for line in lines if line.startswith(_HIGHLIGHT)]
    highlighted = [line for line in highlighted if line]
    if highlighted:
        # Date, payee, amount, and description all come from the highlighted row.
        # When a list marks more than one line, the highlighted transaction is the bottom one.
        with_money = [line for line in highlighted if _money_hits(_charge_text(line))]
        if with_money:
            chosen = with_money[-1]
            fields = _fields_from_lines(
                [chosen],
                vendors=vendors,
                categories=categories,
                books=books,
                year_lines=[chosen],
            )
            return _with_filled(fields, recognized=True, highlighted=True)
    plain = [_plain_line(line) for line in lines]
    plain = [line for line in plain if line]
    if _is_transaction_list(plain):
        fields = _fields_from_list(plain, vendors=vendors, categories=categories)
        return _with_filled(fields, recognized=True, highlighted=False)
    fields = _fields_from_lines(plain, vendors=vendors, categories=categories, books=books, year_lines=plain)
    return _with_filled(fields, recognized=True, highlighted=False)


def _plain_line(line: str) -> str:
    if line.startswith(_HIGHLIGHT):
        return _clean_line(line[len(_HIGHLIGHT):])
    return line


def _needs_day(line: str) -> bool:
    """A bank date cell prints the month above the day, sometimes beside the amount."""
    if not _month_name(line):
        return False
    stripped = _MONEY.sub(" ", line)
    stripped = re.sub(r"\b20\d{2}\b", " ", stripped)
    return re.search(r"\b\d{1,2}\b", stripped) is None


def _join_visual_rows(lines: list[str]) -> list[str]:
    """Join the two OCR lines of one bank row so its fields stay together."""
    joined: list[str] = []
    index = 0
    while index < len(lines):
        if index + 1 < len(lines) and _needs_day(_plain_line(lines[index])) and re.match(
            r"\d{1,2}\b", _plain_line(lines[index + 1])
        ):
            text = _clean_line(f"{_plain_line(lines[index])} {_plain_line(lines[index + 1])}")
            if lines[index].startswith(_HIGHLIGHT) or lines[index + 1].startswith(_HIGHLIGHT):
                text = _HIGHLIGHT + text
            joined.append(text)
            index += 2
            continue
        joined.append(lines[index])
        index += 1
    return joined


def read_image(
    path: Path,
    *,
    vendors: list[str] | tuple[str, ...] = (),
    categories: list[str] | tuple[str, ...] = (),
    books: list[str] | tuple[str, ...] = (),
) -> dict[str, object]:
    text = ocr_image(path)
    if not text.strip():
        return _with_filled(empty_fields(), recognized=False, highlighted=False)
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


def render_highlighted_list(path: Path) -> None:
    binary = _ocr_binary()
    if binary is None:
        raise RuntimeError("Receipt OCR is not available on this computer.")
    result = subprocess.run(
        [str(binary), "--render-list", str(path)],
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    if result.returncode != 0 or not path.is_file():
        raise RuntimeError(result.stderr.strip() or "Could not draw the highlighted list.")


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


def _with_filled(fields: dict[str, str], *, recognized: bool, highlighted: bool) -> dict[str, object]:
    filled = [name for name in FIELD_NAMES if fields[name]]
    return {**fields, "filled": filled, "recognized": recognized, "highlighted": highlighted}


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _fields_from_lines(
    lines: list[str],
    *,
    vendors: list[str] | tuple[str, ...],
    categories: list[str] | tuple[str, ...],
    books: list[str] | tuple[str, ...],
    year_lines: list[str],
) -> dict[str, str]:
    lines = _join_stacked_dates(lines)
    fields = empty_fields()
    blob = "\n".join(lines)
    fields["spent_on"] = _date(lines, year_lines)
    amount, currency = _amount(lines)
    fields["amount"] = amount
    fields["currency"] = currency
    fields["payee"] = _payee(lines, vendors)
    fields["category"] = _category(blob, categories)
    fields["payment_method"] = _payment(lines)
    fields["title"] = _book(blob, books)
    fields["description"] = _description(lines, fields["payee"], fields["title"])
    fields["notes"] = _notes(blob)
    return fields


def _join_stacked_dates(lines: list[str]) -> list[str]:
    """Join a month printed above its day, as bank lists often do."""
    joined: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        month_only = _month_name(line) and not re.search(r"\d", line)
        if month_only and index + 1 < len(lines) and re.match(r"\d{1,2}\b", lines[index + 1]):
            joined.append(_clean_line(f"{line} {lines[index + 1]}"))
            index += 2
            continue
        joined.append(line)
        index += 1
    return joined


def _fields_from_list(
    lines: list[str],
    *,
    vendors: list[str] | tuple[str, ...],
    categories: list[str] | tuple[str, ...],
) -> dict[str, str]:
    """A transaction list with no highlighted row. Fill only what every row shares."""
    fields = empty_fields()
    data_lines = [line for line in lines if not _is_header(line)]
    payees = [payee for line in data_lines if (payee := _catalog_payee(line, vendors))]
    unique = list(dict.fromkeys(payees))
    if len(unique) == 1:
        fields["payee"] = unique[0]
        fields["category"] = _category(unique[0] + "\n" + "\n".join(data_lines), categories)
    payments = [item for line in data_lines if (item := _payment_phrase(line))]
    unique_payments = list(dict.fromkeys(payments))
    if len(unique_payments) == 1:
        fields["payment_method"] = unique_payments[0]
    return fields


def _is_transaction_list(lines: list[str]) -> bool:
    if any(_POSTED.search(line) or _BILLING.search(line) or _RECEIVED.search(line) for line in lines):
        return False
    if any(_TOTAL_LINE_WORD.search(line) or _STATEMENT_AS.search(line) for line in lines):
        return False
    charges = [
        hit
        for line in lines
        if not _SKIP_AMOUNT.search(_charge_text(line))
        for hit in _money_hits(_charge_text(line))
    ]
    # Several charges and no chosen row: do not mix one row's description with another's amount.
    return len(charges) >= 2


def _is_header(line: str) -> bool:
    folded = line.casefold()
    words = ("date", "description", "amount", "category", "balance")
    return sum(word in folded for word in words) >= 3


def _date(lines: list[str], year_lines: list[str]) -> str:
    for pattern, group in (
        (_POSTED, None),
        (_BILLING, None),
        (_RECEIVED, None),
        (_DATE_LINE, None),
    ):
        for line in lines:
            if pattern is _DATE_LINE and (_POSTED.search(line) or _PURCHASED.search(line) or _STATEMENT_ENDING.search(line)):
                continue
            if pattern.search(line):
                found = _date_in(line) or _month_day(line, year_lines)
                if found:
                    return found
    for line in lines:
        if _PURCHASED.search(line) or _STATEMENT_ENDING.search(line):
            continue
        found = _date_in(line) or _month_day(line, year_lines)
        if found:
            return found
    for line in lines:
        found = _date_in(line) or _month_day(line, year_lines)
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


def _month_name(line: str) -> re.Match[str] | None:
    return re.search(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
        r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
        line,
        re.IGNORECASE,
    )


def _month_day(line: str, year_lines: list[str]) -> str:
    if _date_in(line):
        return ""
    month = _month_name(line)
    if not month:
        return ""
    key = month.group(1).lower()
    if key not in _MONTHS:
        return ""
    stripped = _MONEY.sub(" ", line)
    stripped = re.sub(r"\b20\d{2}\b", " ", stripped)
    day_match = re.search(r"\b(\d{1,2})\b", stripped)
    if not day_match:
        return ""
    day = int(day_match.group(1))
    year = _year_on(year_lines) or _inferred_year(_MONTHS[key], day)
    if not year:
        return ""
    return _valid_date(year, _MONTHS[key], day)


def _year_on(lines: list[str]) -> int:
    years = [int(match) for line in lines for match in re.findall(r"\b(20\d{2})\b", line)]
    unique = list(dict.fromkeys(years))
    if len(unique) == 1:
        return unique[0]
    return 0


def _inferred_year(month: int, day: int) -> int:
    today = date.today()
    try:
        candidate = date(today.year, month, day)
    except ValueError:
        return 0
    if candidate > today:
        return today.year - 1
    return today.year


def _charge_text(line: str) -> str:
    """Drop a reward clause so the charge on that same line still counts."""
    text = re.sub(r"you earned\s*[$€£]?\s*\d[\d,]*(?:\.\d+)?", " ", line, flags=re.IGNORECASE)
    text = re.sub(r"\d+(?:\.\d+)?%\s*cash back", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"rewards?\s*cash", " ", text, flags=re.IGNORECASE)
    return text


def _amount(lines: list[str]) -> tuple[str, str]:
    candidates: list[tuple[str, dict[str, object]]] = []
    for line in lines:
        text = _charge_text(line)
        if _SKIP_AMOUNT.search(text):
            continue
        for hit in _money_hits(text):
            candidates.append((line, hit))
    if not candidates:
        return "", ""
    totals = [item for item in candidates if _TOTAL_LINE_WORD.search(item[0]) and not _SUBTOTAL_LINE.search(item[0])]
    pool = totals or candidates
    negatives = [item for item in pool if item[1]["negative"]]
    chosen_line, hit = (negatives or pool)[0]
    currency = str(hit["currency"] or "") or _document_currency([chosen_line, *lines])
    return str(hit["amount"]), currency


def _money_hits(line: str) -> list[dict[str, object]]:
    hits = []
    for match in _MONEY.finditer(line):
        number = _money_number(match)
        if not number:
            continue
        hits.append(
            {
                "amount": number,
                "currency": _money_currency(match),
                "negative": bool(match.group("sign")),
            }
        )
    return hits


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
    if "$" in prefix:
        return "USD"
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
    catalog = _catalog_payee(blob, vendors)
    if catalog:
        return catalog
    for line in lines:
        labeled = _LABELED_PAYEE.search(line)
        if labeled:
            value = labeled.group(1).strip(" -:")
            if _looks_like_name(value):
                return value[:80]
    if not any(_date_in(line) or _money_hits(line) for line in lines):
        return ""
    for line in lines:
        if _skip_payee_line(line) or _is_header(line):
            continue
        if _looks_like_name(line):
            return line[:80]
    return ""


def _catalog_payee(text: str, vendors: list[str] | tuple[str, ...]) -> str:
    folded = text.casefold()
    names = [name.strip() for name in vendors if name.strip()]
    for needle, keys in _VENDOR_ALIASES:
        if not any(key in folded for key in keys):
            continue
        matches = [name for name in names if needle in name.casefold() or any(key in name.casefold() for key in keys)]
        if matches:
            return max(matches, key=len)
    known = [name for name in names if _contains_name(text, name)]
    if known:
        return max(known, key=len)
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
        stated = _STATEMENT_AS.search(line)
        if stated:
            value = stated.group(1).strip(" .")
            if value:
                return value[:140]
    for line in lines:
        labeled = _LABELED_DESCRIPTION.search(line)
        if not labeled:
            continue
        value = labeled.group(1).strip()
        if value and value.casefold() not in {payee.casefold(), title.casefold()}:
            return value[:140]
    for line in lines:
        service = re.search(r"\bservice\s+(?!provider\b|summary\b)(.+)", line, re.IGNORECASE)
        if service and service.group(1).strip():
            return service.group(1).strip()[:140]
    for line in lines:
        if not _money_hits(line):
            continue
        if _SKIP_AMOUNT.search(_charge_text(line)) or _TOTAL_LINE_WORD.search(line):
            continue
        item = _row_description(line)
        if item and not _mostly_payee(item, payee) and item.casefold() != title.casefold():
            return item[:140]
    if not any(_date_in(line) or _money_hits(line) or _month_name(line) for line in lines):
        return ""
    leftovers = []
    for line in lines:
        leftover = _row_description(line)
        if not leftover or leftover.casefold() in {payee.casefold(), title.casefold()}:
            continue
        leftovers.append(leftover)
    for leftover in leftovers:
        if _mostly_payee(leftover, payee):
            continue
        return leftover[:140]
    return leftovers[0][:140] if leftovers else ""


def _mostly_payee(text: str, payee: str) -> bool:
    if not payee:
        return False
    folded = re.sub(r"[^a-z0-9 ]", " ", text.casefold())
    name = re.sub(r"[^a-z0-9 ]", " ", payee.casefold())
    if name not in folded:
        return False
    words = [word for word in folded.replace(name, " ").split() if word]
    generic = {"platforms", "inc", "llc", "ltd", "com", "corp", "corporation", "communications"}
    return all(word in generic for word in words)


def _row_description(line: str) -> str:
    text = _MONEY.sub(" ", line)
    text = _PAYMENT_PHRASE.sub(" ", text)
    text = _MONTH_DATE.sub(" ", text)
    text = _MDY_DATE.sub(" ", text)
    text = re.sub(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
        r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b\d{1,2}\b", " ", text)
    text = re.sub(r"[^A-Za-z0-9&*'/., -]", " ", text)
    text = _clean_line(text).strip(" -*,.")
    if not text or _is_header(text) or _HEADER.match(text) or len(text) < 3:
        return ""
    if re.search(r"reward|you earned|report a problem|merchant website|cash back|professional services", text, re.IGNORECASE):
        return ""
    if re.match(r"(order|receipt|invoice|your order|payment)\b", text, re.IGNORECASE):
        return ""
    if re.match(r"edward\b", text, re.IGNORECASE):
        return ""
    if _BANKS.search(text) and len(text.split()) <= 4:
        return ""
    return text


def _payment(lines: list[str]) -> str:
    for line in lines:
        card = re.search(r"\b(?:card ending|ending)\s*(\d{4})\b", line, re.IGNORECASE)
        if card:
            return f"Card ending {card.group(1)}"
        masked = re.search(r"(?:mastercard|visa).{0,40}(\d{4})", line, re.IGNORECASE)
        if masked:
            brand = "Mastercard" if "mastercard" in line.casefold() else "Visa"
            return f"{brand} {masked.group(1)}"
        named = re.search(r"\b[A-Z]\.{2,}\s*(\d{4})\b", line)
        if named:
            return f"Card ending {named.group(1)}"
    for line in lines:
        phrase = _payment_phrase(line)
        if phrase:
            return phrase
    return ""


def _payment_phrase(line: str) -> str:
    match = _PAYMENT_PHRASE.search(line)
    if not match:
        return ""
    phrase = match.group(1)
    if phrase.casefold() == "visa debit":
        return "Visa debit"
    return phrase[:1].upper() + phrase[1:] if phrase.islower() or phrase[:1].islower() else phrase


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
    value = re.sub(r"\s+", " ", match.group(1)).strip()[:160]
    if not re.search(r"\d", value):
        return ""
    return value
