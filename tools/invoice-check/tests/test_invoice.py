from decimal import Decimal

import pytest

from invoice import Finding, InvalidInvoice, check_invoice, money


def good_invoice() -> dict:
    return {
        "lines": [
            {"quantity": 3, "unit_price": "12.50", "vat_rate": "0.21", "net": "37.50"},
            {"quantity": "1", "unit_price": "100", "vat_rate": "0", "net": "100.00"},
        ],
        "subtotal": "137.50",
        "vat": "7.88",
        "total": "145.38",
    }


def test_correct_invoice_has_no_findings():
    assert check_invoice(good_invoice()) == []


def test_wrong_line_net_is_reported_with_line_number():
    invoice = good_invoice()
    invoice["lines"][0]["net"] = "36.50"
    assert Finding(1, "net", "37.50", "36.50") in check_invoice(invoice)


def test_wrong_total_is_reported_on_invoice_level():
    invoice = good_invoice()
    invoice["total"] = "145.37"
    assert check_invoice(invoice) == [Finding(0, "total", "145.38", "145.37")]


def test_vat_is_rounded_per_line_half_up():
    # Per line: 0.50 * 0.21 = 0.105 -> 0.11 (half-up), three lines -> 0.33.
    # Rounding the total instead would give 1.50 * 0.21 = 0.315 -> 0.32,
    # and half-to-even per line would give 0.10 * 3 = 0.30.
    lines = [{"quantity": 1, "unit_price": "0.50", "vat_rate": "0.21"}] * 3
    assert check_invoice({"lines": lines, "vat": "0.33"}) == []
    assert check_invoice({"lines": lines, "vat": "0.32"}) == [Finding(0, "vat", "0.33", "0.32")]


def test_money_rounds_half_up_not_to_even():
    assert money(Decimal("0.005")) == Decimal("0.01")
    assert money(Decimal("0.015")) == Decimal("0.02")


def test_fields_left_out_are_not_checked():
    assert check_invoice({"lines": [{"quantity": 2, "unit_price": 5, "vat_rate": 0}]}) == []


def test_empty_invoice_must_total_zero():
    assert check_invoice({"lines": [], "total": "0"}) == []
    assert check_invoice({"lines": [], "total": "1"}) == [Finding(0, "total", "0", "1.00")]


@pytest.mark.parametrize(
    "invoice, message",
    [
        (None, "list of 'lines'"),
        ({"lines": "nope"}, "list of 'lines'"),
        ({"lines": ["nope"]}, "line 1: expected an object"),
        ({"lines": [{"quantity": 1, "unit_price": 1}]}, "missing 'vat_rate'"),
        ({"lines": [{"quantity": "x", "unit_price": 1, "vat_rate": 0}]}, "not a number"),
        ({"lines": [{"quantity": True, "unit_price": 1, "vat_rate": 0}]}, "expected a number"),
        ({"lines": [{"quantity": "NaN", "unit_price": 1, "vat_rate": 0}]}, "not a finite number"),
    ],
)
def test_invalid_input_is_rejected_with_a_reason(invoice, message):
    with pytest.raises(InvalidInvoice, match=message):
        check_invoice(invoice)


def test_finding_serialises_to_a_plain_dict():
    assert Finding(2, "net", "1.00", "2.00").as_dict() == {
        "line": 2,
        "field": "net",
        "expected": "1.00",
        "actual": "2.00",
    }
