"""Exact numbers and labelled values for wallet intelligence (ADR 0045).

The rules follow the execution package's model (ADR 0043), re-implemented here because this
package may not import it:

- Money, prices and quantities are `Decimal`, built from `Decimal`, `int` or a plain numeric `str`.
  A `float` or `bool` is refused even when it looks round: its binary value is already inexact.
  NaN and infinity are refused.
- Arithmetic that matters runs in a trapping local context, so a result that would need rounding
  raises instead of being rounded silently. Rounding happens only where a caller names a step and a
  direction (`floor_to_step`).
- Statistics may use `float` (`stats.py`). A float never becomes a money value or a quantity.

`Basis` and `Labeled` mirror `research_economics.Basis` / `Labeled` value for value (a parity test
pins this). They are mirrored rather than imported because `research_economics` imports the
experiment registry, a protected-label owner this package must not reach.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Context, Decimal, Inexact, InvalidOperation, Rounded, localcontext
from enum import Enum
from typing import Iterable

# Native token quantities can carry 18 decimals (EVM), so the place limit is wider than the
# execution model's 8. The magnitude limit keeps every sum of a million values exact.
MAX_EXPONENT = 15
MAX_DECIMAL_PLACES = 18
_PRECISION = 2 * (MAX_EXPONENT + 1 + MAX_DECIMAL_PLACES) + 10
_PLAIN_DECIMAL = re.compile(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)")
ZERO = Decimal(0)


class ExactValueError(ValueError):
    """A value that is not an exact, finite number of the expected kind."""


def exact_context() -> Context:
    """A fresh trapping context: inexact or rounded results raise."""
    return Context(prec=_PRECISION, traps=[InvalidOperation, Inexact, Rounded])


def exact_decimal(value: object, *, name: str) -> Decimal:
    """`value` as a finite Decimal; refuses float, bool, NaN, infinity and non-numeric text."""
    if isinstance(value, (bool, float)):
        raise ExactValueError(f"{name} must be an exact Decimal, int or numeric string, not {type(value).__name__}")
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        if not _PLAIN_DECIMAL.fullmatch(text):
            raise ExactValueError(f"{name} is not a plain decimal string: {value!r}")
        d = Decimal(text)
    else:
        raise ExactValueError(f"{name} must be a Decimal, int or numeric string, not {type(value).__name__}")
    if not d.is_finite():
        raise ExactValueError(f"{name} must be finite, not {d}")
    if d != 0:
        if d.adjusted() > MAX_EXPONENT:
            raise ExactValueError(f"{name} is too large: {d}")
        exponent = d.as_tuple().exponent
        if isinstance(exponent, int) and exponent < 0 and len(decimal_text(d).partition(".")[2]) > MAX_DECIMAL_PLACES:
            raise ExactValueError(f"{name} has more than {MAX_DECIMAL_PLACES} decimal places: {d}")
    return d


def decimal_text(value: Decimal) -> str:
    """Canonical exponent-free text; equal values give equal text ("1.50" and "1.5" give "1.5")."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ExactValueError(f"not a finite Decimal: {value!r}")
    if value == 0:
        return "0"
    sign, digits, exponent = value.as_tuple()
    digit_list = list(digits)
    assert isinstance(exponent, int)
    while exponent < 0 and len(digit_list) > 1 and digit_list[-1] == 0:
        digit_list.pop()
        exponent += 1
    return format(Decimal((sign, tuple(digit_list), exponent)), "f")


def add(*values: Decimal) -> Decimal:
    with localcontext(exact_context()):
        total = ZERO
        for v in values:
            total = total + v
        return total


def total(values: Iterable[Decimal]) -> Decimal:
    return add(*tuple(values))


def sub(a: Decimal, b: Decimal) -> Decimal:
    with localcontext(exact_context()):
        return a - b


def mul(a: Decimal, b: Decimal) -> Decimal:
    with localcontext(exact_context()):
        return a * b


def div_floor(a: Decimal, b: Decimal, step: Decimal) -> Decimal:
    """a / b floored to a multiple of `step` (for sizing: never rounds a quantity up)."""
    if b == 0:
        raise ExactValueError("division by zero")
    with localcontext(Context(prec=_PRECISION)):
        raw = a / b
    return floor_to_step(raw, step)


def ratio(a: Decimal, b: Decimal) -> Decimal | None:
    """a / b for a reported ratio (not money); None when b is zero. Rounded at 1e-12."""
    if b == 0:
        return None
    with localcontext(Context(prec=_PRECISION)):
        return (a / b).quantize(Decimal("1e-12"))


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    """`value` rounded down to a multiple of `step` (step > 0)."""
    if step <= 0:
        raise ExactValueError("step must be positive")
    with localcontext(Context(prec=_PRECISION)):
        units = (value / step).to_integral_value(rounding=ROUND_FLOOR)
        return units * step


def on_step(value: Decimal, step: Decimal) -> bool:
    with localcontext(exact_context()):
        return value % step == 0


class Basis(str, Enum):
    """Evidential basis of a number. Values equal `research_economics.Basis` (parity-tested)."""

    OBSERVED = "OBSERVED"
    ESTIMATED = "ESTIMATED"
    OWNER_INPUT = "OWNER_INPUT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Labeled:
    """A number with its basis. UNKNOWN never carries a value, and a value is never UNKNOWN."""

    value: Decimal | None
    basis: Basis
    note: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.basis, Basis):
            raise ValueError("basis must be a Basis")
        if (self.value is None) != (self.basis is Basis.UNKNOWN):
            raise ValueError("UNKNOWN has no value, and a value needs a basis other than UNKNOWN")
        if self.value is not None and (not isinstance(self.value, Decimal) or not self.value.is_finite()):
            raise ValueError(f"value must be a finite Decimal, not {self.value!r}")

    @classmethod
    def unknown(cls, note: str = "") -> "Labeled":
        return cls(None, Basis.UNKNOWN, note)

    @classmethod
    def observed(cls, value: Decimal, note: str = "") -> "Labeled":
        return cls(value, Basis.OBSERVED, note)

    @property
    def known(self) -> bool:
        return self.basis is not Basis.UNKNOWN

    def to_dict(self) -> dict:
        return {"value": None if self.value is None else decimal_text(self.value), "basis": self.basis.value,
                "note": self.note}
