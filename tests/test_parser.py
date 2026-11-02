import json
from pathlib import Path

import pytest

from bol_parser import parse
from bol_parser.__main__ import main
from bol_parser.extract import extract_address, parse_date

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def load(name: str) -> dict:
    return parse((SAMPLES / name).read_text())


class TestCompleteBol:
    record = load("bol_complete.txt")

    def test_header_fields(self):
        assert self.record["bol_number"] == "BOL-2026-004812"
        assert self.record["ship_date"] == "2026-10-14"
        assert self.record["carrier"] == "Gulf Coast Freight LLC"
        assert self.record["scac"] == "GCFL"
        assert self.record["po_number"] == "PO-778134"

    def test_ship_to_address(self):
        assert self.record["ship_to"] == {
            "name": "Acme Industrial Supply",
            "street": "4500 Commerce St, Suite 210",
            "city": "Dallas",
            "state": "TX",
            "zip": "75226",
        }

    def test_line_items_and_weights(self):
        codes = [item["product_code"] for item in self.record["line_items"]]
        assert codes == ["PC-10432", "PC-20981"]
        assert self.record["total_weight_lbs"] == 23450

    def test_instructions_and_hazmat(self):
        assert self.record["hazmat"] is False
        assert self.record["special_instructions"].startswith("Deliver to dock 4")

    def test_passes_validation(self):
        assert self.record["validation"] == {"valid": True, "errors": [], "warnings": []}


class TestEmailConfirmation:
    """Lowercase labels, label aliases, kg units, and a spelled-out date."""

    record = load("shipping_confirmation_email.txt")

    def test_aliases_resolve(self):
        assert self.record["bol_number"] == "LSL-88213"
        assert self.record["ship_from"]["name"] == "Channelview Terminal"
        assert self.record["ship_to"]["city"] == "Laredo"

    def test_kg_converted_to_lbs(self):
        first = self.record["line_items"][0]
        assert first["weight_unit"] == "kg"
        assert first["weight_lbs"] == pytest.approx(1600 * 2.20462, rel=1e-4)

    def test_date_normalized(self):
        assert self.record["ship_date"] == "2026-10-22"

    def test_hazmat_yes(self):
        assert self.record["hazmat"] is True

    def test_valid(self):
        assert self.record["validation"]["valid"]


class TestIncompleteBol:
    record = load("bol_incomplete.txt")

    def test_rejected(self):
        assert not self.record["validation"]["valid"]

    def test_flags_every_problem(self):
        errors = " | ".join(self.record["validation"]["errors"])
        assert "ship_to missing zip" in errors
        assert "ship_to missing city" not in errors  # city/state still parsed
        assert "quantity must be positive" in errors
        assert "weight mismatch" in errors

    def test_warnings_do_not_block_alone(self):
        warnings = self.record["validation"]["warnings"]
        assert "ship_from not found" in warnings
        assert "hazmat flag not stated" in warnings


def test_empty_document_is_rejected():
    record = parse("")
    assert not record["validation"]["valid"]
    assert "missing required field: bol_number" in record["validation"]["errors"]


@pytest.mark.parametrize(
    "raw, expected",
    [("10/14/2026", "2026-10-14"), ("2026-10-14", "2026-10-14"),
     ("Oct 14, 2026", "2026-10-14"), ("14 Oct 2026", "2026-10-14"), ("not a date", None)],
)
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_address_without_label_returns_none():
    assert extract_address("nothing here", r"ship\s*to") is None


def test_cli_sorts_documents(tmp_path):
    exit_code = main([str(SAMPLES), "--out", str(tmp_path)])
    assert exit_code == 1  # one sample is intentionally bad
    summary = json.loads((tmp_path / "run_summary.json").read_text())
    assert summary["rejected"] == ["bol_incomplete.txt"]
    assert len(summary["accepted"]) == 2
    assert "weight mismatch" in (tmp_path / "errors.log").read_text()
