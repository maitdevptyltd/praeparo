"""Display wrappers for metric context values.

Phase 8 introduces a two-context approach:

- Raw context keeps numeric values for DAX/config templating and execution.
- Display context replaces metric-binding aliases with small wrapper objects that
  stringify using the binding's format token.
"""

from __future__ import annotations

from dataclasses import dataclass

from praeparo.formatting import format_value


@dataclass(frozen=True, slots=True)
class FormattedMetricValue:
    """Metric value wrapper that stringifies using a format token.

    Use `.value` in templates when you explicitly need the raw numeric value.
    """

    value: float | int | None
    format: str | None = None

    @property
    def raw(self) -> float | int | None:
        return self.value

    def __str__(self) -> str:
        return format_value(self.value, self.format)

