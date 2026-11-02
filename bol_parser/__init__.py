"""Shipping document and bill of lading parser."""

from .extract import extract
from .validate import validate


def parse(text: str) -> dict:
    """Extract fields and attach a validation result."""
    record = extract(text)
    record["validation"] = validate(record)
    return record


__all__ = ["extract", "validate", "parse"]
