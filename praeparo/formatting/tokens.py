"""Parse and apply Praeparo formatting tokens.

Praeparo uses compact, YAML-friendly format tokens (for example `percent:0` or
`number:2`) across visuals and pack templating. This module centralises parsing
and conversion so token behaviour stays consistent everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast


FormatKind = Literal["number", "percent", "currency"]


@dataclass(frozen=True, slots=True)
class FormatSpec:
    kind: FormatKind
    precision: int


def parse_format_token(token: str) -> FormatSpec:
    """Parse a format token like `number:0` into a concrete spec.

    Supported tokens (Phase 8):
    - `number[:N]` (default N=0)
    - `percent[:N]` (default N=0, expects 0–1 input values)
    - `currency[:N]` (default N=2, symbol handling deferred)
    """

    cleaned = token.strip().lower()
    if not cleaned:
        raise ValueError("format token cannot be empty")

    kind, raw_precision = (cleaned.split(":", 1) + [""])[:2]
    if kind not in {"number", "percent", "currency"}:
        raise ValueError(
            "format token must start with one of ['currency', 'number', 'percent'] "
            "and may include an optional precision suffix like 'percent:2'"
        )

    if not raw_precision.strip():
        default_precision = 2 if kind == "currency" else 0
        return FormatSpec(kind=cast(FormatKind, kind), precision=default_precision)

    try:
        precision_float = float(raw_precision.strip())
    except ValueError as exc:
        raise ValueError(f"format precision must be numeric (got '{raw_precision.strip()}')") from exc

    return FormatSpec(kind=cast(FormatKind, kind), precision=max(0, int(precision_float)))


def format_value(value: float | int | None, token: str | None) -> str:
    """Render *value* according to a Praeparo format token.

    This is primarily intended for display surfaces (PPTX text, YAML-authored
    narrative blocks). Execution surfaces should continue to use raw numeric
    values.
    """

    if value is None:
        return ""

    if token is None or not token.strip():
        return str(value)

    spec = parse_format_token(token)
    precision = spec.precision

    if spec.kind == "percent":
        return f"{float(value):.{precision}%}"
    if spec.kind == "number":
        return f"{float(value):.{precision}f}"
    if spec.kind == "currency":
        # Symbol handling is intentionally deferred; still keep fixed precision.
        return f"{float(value):,.{precision}f}"

    return str(value)


def plotly_text_template(format_token: str | None) -> str:
    """Convert a format token into a Plotly `texttemplate` snippet."""

    token = (format_token or "").strip()
    if not token:
        return "%{text}"

    try:
        spec = parse_format_token(token)
    except ValueError:
        return "%{text}"
    if spec.kind == "percent":
        return f"%{{text:.{spec.precision}%}}"
    if spec.kind == "number":
        return f"%{{text:.{spec.precision}f}}"
    if spec.kind == "currency":
        # Plotly currency symbols are out of scope; prefer a fixed-point number.
        return f"%{{text:,.{spec.precision}f}}"
    return "%{text}"


def plotly_tickformat(format_token: str | None) -> str | None:
    """Convert a format token into a Plotly `tickformat` directive."""

    if not format_token:
        return None

    token = format_token.strip()
    if not token:
        return None

    try:
        spec = parse_format_token(token)
    except ValueError:
        return None
    if spec.kind == "percent":
        return f".{spec.precision}%"
    if spec.kind in {"number", "currency"}:
        return f",.{spec.precision}f"
    return None
