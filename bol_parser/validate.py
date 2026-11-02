"""Validation rules that decide whether a parsed document is safe to ingest.

Errors block ingestion. Warnings are logged for a human to review but do not
block. The goal is that nothing incomplete reaches the database silently.
"""

from __future__ import annotations

REQUIRED_FIELDS = ("bol_number", "ship_date", "ship_to", "line_items")
REQUIRED_ADDRESS_FIELDS = ("name", "city", "state", "zip")
WEIGHT_TOLERANCE = 0.01  # 1% difference allowed between line items and stated total


def validate(record: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    for field in REQUIRED_FIELDS:
        if not record.get(field):
            errors.append(f"missing required field: {field}")

    ship_to = record.get("ship_to") or {}
    if ship_to:
        for field in REQUIRED_ADDRESS_FIELDS:
            if not ship_to.get(field):
                errors.append(f"ship_to missing {field}")

    if not record.get("ship_from"):
        warnings.append("ship_from not found")

    for i, item in enumerate(record.get("line_items") or [], start=1):
        if item["quantity"] <= 0:
            errors.append(f"line {i} ({item['product_code']}): quantity must be positive")
        if item["weight_lbs"] <= 0:
            errors.append(f"line {i} ({item['product_code']}): weight must be positive")

    items = record.get("line_items") or []
    stated = record.get("total_weight_lbs")
    if items and stated is None:
        warnings.append("no total weight stated; cannot cross-check line items")
    elif items and stated:
        summed = round(sum(item["weight_lbs"] for item in items), 2)
        if abs(summed - stated) > stated * WEIGHT_TOLERANCE:
            errors.append(
                f"weight mismatch: line items sum to {summed} lbs, document states {stated} lbs"
            )

    if record.get("hazmat") is None:
        warnings.append("hazmat flag not stated")

    return {"valid": not errors, "errors": errors, "warnings": warnings}
