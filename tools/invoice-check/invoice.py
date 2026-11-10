"""Recompute invoice totals and report every line that doesn't add up.

Money is Decimal, never float, and is rounded half-up to whole cents per line,
which is how the invoices this checks are made.
"""

from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")


class InvalidInvoice(ValueError):
    """The input is not an invoice we can check."""


@dataclass(frozen=True)
class Finding:
    line: int  # 0 means the invoice as a whole
    field: str
    expected: str
    actual: str

    def as_dict(self) -> dict:
        return asdict(self)


def money(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def number(value: object, where: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise InvalidInvoice(f"{where}: expected a number, got {value!r}")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise InvalidInvoice(f"{where}: {value!r} is not a number") from exc
    if not result.is_finite():
        raise InvalidInvoice(f"{where}: {value!r} is not a finite number")
    return result


def check_invoice(invoice: dict) -> list[Finding]:
    """Every difference between what the invoice says and what it should say."""
    if not isinstance(invoice, dict) or not isinstance(invoice.get("lines"), list):
        raise InvalidInvoice("an invoice is an object with a list of 'lines'")

    findings: list[Finding] = []
    subtotal = Decimal(0)
    vat_total = Decimal(0)

    for i, line in enumerate(invoice["lines"], start=1):
        if not isinstance(line, dict):
            raise InvalidInvoice(f"line {i}: expected an object")
        try:
            quantity = number(line["quantity"], f"line {i} quantity")
            unit_price = number(line["unit_price"], f"line {i} unit_price")
            vat_rate = number(line["vat_rate"], f"line {i} vat_rate")
        except KeyError as exc:
            raise InvalidInvoice(f"line {i}: missing {exc.args[0]!r}") from exc

        net = money(quantity * unit_price)
        if "net" in line:
            stated = money(number(line["net"], f"line {i} net"))
            if stated != net:
                findings.append(Finding(i, "net", str(net), str(stated)))

        subtotal += net
        vat_total += money(net * vat_rate)

    expected = {"subtotal": subtotal, "vat": vat_total, "total": subtotal + vat_total}
    for field, amount in expected.items():
        if field in invoice:
            stated = money(number(invoice[field], field))
            if stated != amount:
                findings.append(Finding(0, field, str(amount), str(stated)))

    return findings
