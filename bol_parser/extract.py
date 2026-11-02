"""Rule-based extraction of structured fields from unformatted shipping text.

Shipping confirmations and bills of lading arrive as PDFs-turned-text, email
bodies, or EDI printouts. Labels vary ("Ship To" vs "Consignee"), units vary
(lbs vs kg), and dates come in several formats. This module normalizes all of
that into one predictable dictionary.
"""

from __future__ import annotations

import re
from datetime import datetime

# Label aliases seen across carriers and shippers.
SHIP_TO_LABELS = r"(?:ship\s*to|consignee|deliver\s*to)"
SHIP_FROM_LABELS = r"(?:ship\s*from|shipper|origin)"
# Any label that ends an address block.
BLOCK_END = re.compile(
    r"^\s*(?:ship\s*to|ship\s*from|consignee|shipper|origin|deliver\s*to|"
    r"po\s*(?:number|no|#)|items|product\s*code|total|hazmat|special|carrier|"
    r"bol|bill\s+of\s+lading|ship(?:ping)?\s*date)\b",
    re.IGNORECASE,
)

KG_TO_LBS = 2.20462

DATE_FORMATS = ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%d %b %Y")

CITY_STATE_ZIP = re.compile(
    r"^(?P<city>[A-Za-z .'-]+),\s*(?P<state>[A-Z]{2})(?:\s+(?P<zip>\d{5}(?:-\d{4})?))?\s*$"
)

LINE_ITEM = re.compile(
    r"^\s*(?P<code>[A-Z]{2,4}-\d{3,6})\s+(?P<desc>.+?)\s+(?P<qty>\d+)\s+"
    r"(?P<weight>[\d,]+(?:\.\d+)?)\s*(?P<unit>lbs?|kgs?)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _search(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else None


def _to_number(raw: str) -> float:
    return float(raw.replace(",", ""))


def _to_lbs(value: float, unit: str) -> float:
    return round(value * KG_TO_LBS, 2) if unit.lower().startswith("kg") else round(value, 2)


def parse_date(raw: str | None) -> str | None:
    """Return an ISO date (YYYY-MM-DD) or None if the format is unrecognized."""
    if not raw:
        return None
    cleaned = raw.strip().rstrip(".")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def extract_address(text: str, label_pattern: str) -> dict | None:
    """Collect the lines under an address label until a blank line or new label."""
    lines = text.splitlines()
    header = re.compile(rf"^\s*{label_pattern}\s*:?\s*(?P<rest>.*)$", re.IGNORECASE)
    for i, line in enumerate(lines):
        match = header.match(line)
        if not match:
            continue
        block = [match.group("rest").strip()] if match.group("rest").strip() else []
        for follow in lines[i + 1:]:
            if not follow.strip() or BLOCK_END.match(follow):
                break
            block.append(follow.strip())
        if not block:
            return None
        address = {"name": block[0], "street": None, "city": None, "state": None, "zip": None}
        if len(block) > 2:
            address["street"] = ", ".join(block[1:-1])
        last = CITY_STATE_ZIP.match(block[-1]) if len(block) > 1 else None
        if last:
            address.update(city=last["city"].strip(), state=last["state"], zip=last["zip"])
        elif len(block) > 1:
            address["street"] = ", ".join(block[1:])
        return address
    return None


def extract_line_items(text: str) -> list[dict]:
    items = []
    for m in LINE_ITEM.finditer(text):
        weight = _to_number(m["weight"])
        items.append(
            {
                "product_code": m["code"].upper(),
                "description": m["desc"].strip(),
                "quantity": int(m["qty"]),
                "weight": weight,
                "weight_unit": "kg" if m["unit"].lower().startswith("kg") else "lbs",
                "weight_lbs": _to_lbs(weight, m["unit"]),
            }
        )
    return items


def extract_total_weight(text: str) -> float | None:
    match = re.search(
        r"total\s+(?:gross\s+)?weight\s*:?\s*([\d,]+(?:\.\d+)?)\s*(lbs?|kgs?)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return _to_lbs(_to_number(match.group(1)), match.group(2))


def extract(text: str) -> dict:
    """Extract every supported field. Missing fields come back as None."""
    hazmat_raw = _search(r"^\s*hazmat\s*:?\s*(yes|no|y|n)\b", text)
    return {
        "bol_number": _search(
            r"(?:b/?l|bol|bill\s+of\s+lading)\s*(?:no\.?|number|#)\s*:?\s*([A-Z0-9][A-Z0-9-]{3,})",
            text,
        ),
        "ship_date": parse_date(_search(r"ship(?:ping)?\s*date\s*:?\s*([^\n]+)", text)),
        "carrier": _search(r"^\s*carrier\s*:?\s*(.+?)(?:\s{2,}|\s*scac|$)", text),
        "scac": _search(r"scac\s*:?\s*([A-Z]{2,4})\b", text),
        "po_number": _search(r"po\s*(?:number|no\.?|#)\s*:?\s*([A-Z0-9-]+)", text),
        "ship_from": extract_address(text, SHIP_FROM_LABELS),
        "ship_to": extract_address(text, SHIP_TO_LABELS),
        "line_items": extract_line_items(text),
        "total_weight_lbs": extract_total_weight(text),
        "hazmat": None if hazmat_raw is None else hazmat_raw.lower().startswith("y"),
        "special_instructions": _search(r"special\s+instructions\s*:?\s*([^\n]+)", text),
    }
