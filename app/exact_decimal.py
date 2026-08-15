from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Numeric, Text
from sqlalchemy.types import TypeDecorator


def exact_decimal_text(
    value: Any,
    *,
    precision: int = 48,
    scale: int = 24,
) -> str:
    try:
        decimal_value = (
            value
            if isinstance(value, Decimal)
            else Decimal(str(value))
        )
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "Invalid exact decimal value"
        ) from exc

    if not decimal_value.is_finite():
        raise ValueError(
            "Exact decimal value must be finite"
        )

    text = format(decimal_value, "f")

    unsigned = text.lstrip("-")

    if "." in unsigned:
        integer_part, fractional_part = (
            unsigned.split(".", 1)
        )
    else:
        integer_part = unsigned
        fractional_part = ""

    integer_digits = len(
        integer_part.lstrip("0")
    )

    fractional_digits = len(
        fractional_part
    )

    # Zero has no meaningful integer-digit burden.
    if decimal_value == 0:
        integer_digits = 0

    if fractional_digits > scale:
        raise ValueError(
            "Exact decimal scale exceeds "
            f"{scale} digits"
        )

    if (
        integer_digits
        + fractional_digits
        > precision
    ):
        raise ValueError(
            "Exact decimal precision exceeds "
            f"{precision} digits"
        )

    return text


class ExactDecimal(TypeDecorator):
    """
    Exact Decimal persistence.

    SQLite NUMERIC affinity stores fractional values as
    binary floating point. For Treasury accounting that is
    unacceptable, so SQLite stores the canonical decimal
    representation as TEXT.

    Other SQL databases may use a native fixed-precision
    NUMERIC type.
    """

    impl = Text
    cache_ok = True

    def __init__(
        self,
        precision: int = 48,
        scale: int = 24,
    ) -> None:
        self.precision = int(precision)
        self.scale = int(scale)

        super().__init__()

    @property
    def python_type(self):
        return Decimal

    def load_dialect_impl(
        self,
        dialect,
    ):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(
                Text()
            )

        return dialect.type_descriptor(
            Numeric(
                self.precision,
                self.scale,
                asdecimal=True,
            )
        )

    def process_bind_param(
        self,
        value,
        dialect,
    ):
        if value is None:
            return None

        text = exact_decimal_text(
            value,
            precision=self.precision,
            scale=self.scale,
        )

        if dialect.name == "sqlite":
            return text

        return Decimal(text)

    def process_result_value(
        self,
        value,
        dialect,
    ):
        if value is None:
            return None

        text = exact_decimal_text(
            value,
            precision=self.precision,
            scale=self.scale,
        )

        return Decimal(text)
