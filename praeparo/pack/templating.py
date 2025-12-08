"""Jinja utilities for pack templating."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from jinja2 import Environment, Undefined


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        for pattern in ("%Y-%m-%d", "%Y-%m", "%Y/%m/%d"):
            try:
                return datetime.strptime(value, pattern)
            except ValueError:
                continue
    raise TypeError(f"Unsupported date value: {value!r}")


def _shift_months(anchor: datetime, delta_months: int) -> datetime:
    total_months = (anchor.year * 12 + anchor.month - 1) + delta_months
    year, month_index = divmod(total_months, 12)
    month = month_index + 1
    # Clamp day within target month.
    day = min(anchor.day, _days_in_month(year, month))
    return anchor.replace(year=year, month=month, day=day)


def _days_in_month(year: int, month: int) -> int:
    if month in {1, 3, 5, 7, 8, 10, 12}:
        return 31
    if month in {4, 6, 9, 11}:
        return 30
    # February
    if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
        return 29
    return 28


def _odata_date(value: Any) -> str:
    """Format a date-like value as YYYY-MM-DD for OData predicates."""

    return _to_datetime(value).strftime("%Y-%m-%d")


def _odata_between(field: str, start: Any, end: Any, *, inclusive_end: bool = True) -> str:
    """Return an OData predicate covering the provided start/end dates."""

    op_end = "le" if inclusive_end else "lt"
    return f"{field} ge {_odata_date(start)} and {field} {op_end} {_odata_date(end)}"


def _odata_months_back_range(field: str, anchor: Any, months: int = 3, *, inclusive_end: bool = True) -> str:
    """Return a trailing-months OData predicate ending at *anchor* (inclusive by default)."""

    anchor_dt = _to_datetime(anchor).replace(day=1)
    start = _shift_months(anchor_dt, -(months - 1))
    return _odata_between(field, start, anchor_dt, inclusive_end=inclusive_end)


def _safe_relativedelta(value: Any, **kwargs) -> datetime:
    base = _to_datetime(value)
    months = int(kwargs.pop("months", 0))
    years = int(kwargs.pop("years", 0))
    base = base + timedelta(**kwargs)
    total_months = months + (years * 12)
    if total_months:
        base = _shift_months(base, total_months)
    return base


def _safe_strftime(value: Any, fmt: str) -> str:
    dt = _to_datetime(value)
    return dt.strftime(fmt)


def _increase_decrease_label(value: int | float | None | Undefined) -> str:
    if value is None or isinstance(value, Undefined):
        return ""
    return "increased" if value >= 0 else "decreased"


def create_pack_jinja_env() -> Environment:
    """Build a Jinja environment mirroring Data.Slick helpers."""

    env = Environment()
    env.globals.update(
        relativedelta=_safe_relativedelta,
        strftime=_safe_strftime,
        datetime=datetime,
        date=date,
        increase_decrease_label=_increase_decrease_label,
        abs=abs,
        round=round,
        odata_date=_odata_date,
        odata_between=_odata_between,
        odata_months_back_range=_odata_months_back_range,
    )
    return env


def render_value(value: Any, *, env: Environment, context: Mapping[str, Any]) -> Any:
    """Render templated strings within *value* using the supplied context."""

    if value is None:
        return None
    if isinstance(value, str):
        if "{{" not in value:
            return value
        template = env.from_string(value)
        return template.render(**context)
    if isinstance(value, Mapping):
        return {key: render_value(val, env=env, context=context) for key, val in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [render_value(item, env=env, context=context) for item in value]
    return value


__all__ = [
    "create_pack_jinja_env",
    "render_value",
]
