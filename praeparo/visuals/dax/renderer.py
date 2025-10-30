"""Render visual DAX plans into textual queries."""

from __future__ import annotations

from typing import Iterable, Sequence

from .planner_core import MeasurePlan, VisualPlan

DEFAULT_MEASURE_TABLE = "'adhoc'"


def render_visual_plan(
    plan: VisualPlan,
    *,
    measure_table: str = DEFAULT_MEASURE_TABLE,
    summarize_columns: Sequence[str] | None = None,
    extra_filters: Sequence[str] | None = None,
    define_blocks: Sequence[str] | None = None,
) -> str:
    """Return a DAX query for *plan* using the supplied rendering options."""

    summarize = tuple(summarize_columns) if summarize_columns is not None else plan.grain_columns

    define_lines = ["DEFINE"]
    define_body: list[str] = [f"  TABLE {measure_table} = {{ {{ BLANK() }} }}"]
    define_body.extend(_format_define_blocks(plan.define_blocks))
    if define_blocks:
        define_body.extend(_format_define_blocks(define_blocks))

    for measure in plan.measures:
        define_body.extend(_format_measure(measure, measure_table))

    evaluate_body = _format_evaluate(plan.measures, summarize, measure_table)

    combined_filters = _combine_filters(plan.global_filters, extra_filters)
    if combined_filters:
        evaluate_body = _wrap_with_filters(evaluate_body, combined_filters)

    define_text = "\n".join(define_lines + define_body)
    evaluate_text = "\n".join(["EVALUATE", evaluate_body])
    return f"{define_text}\n\n{evaluate_text}\n"


def _format_define_blocks(blocks: Iterable[str]) -> list[str]:
    formatted: list[str] = []
    for block in blocks:
        if not block:
            continue
        formatted.extend(_indent_lines(block.splitlines()))
    return formatted


def _indent_lines(lines: Iterable[str], indent: str = "  ") -> list[str]:
    return [f"{indent}{line.rstrip()}" for line in lines if line.strip()]


def _format_measure(measure: MeasurePlan, table: str) -> list[str]:
    header = f"  MEASURE {table}[{measure.measure_name}] ="
    expression_block = _indent_block(measure.expression.strip())
    return [header, expression_block]


def _format_evaluate(
    measures: Sequence[MeasurePlan],
    grain_columns: Sequence[str],
    table: str,
) -> str:
    arguments: list[str] = []
    arguments.extend(column.strip() for column in grain_columns if column and column.strip())

    for measure in measures:
        arguments.append(_format_measure_binding(measure, table))

    joined = ",\n    ".join(arguments)
    return "SUMMARIZECOLUMNS(\n    " + joined + "\n)"


def _indent_block(text: str, indent: str = "    ") -> str:
    lines = text.splitlines()
    if not lines:
        return indent
    return "\n".join(f"{indent}{line.rstrip()}" for line in lines)


def _combine_filters(
    plan_filters: Sequence[str],
    extra_filters: Sequence[str] | None,
) -> list[str]:
    combined: list[str] = []
    for source in (plan_filters, extra_filters or ()):
        for item in source:
            if not item:
                continue
            cleaned = item.strip()
            if cleaned:
                combined.append(cleaned)
    return combined


def _wrap_with_filters(body: str, filters: Sequence[str]) -> str:
    indented_body = _indent_block(body)
    filter_block = ",\n    ".join(filters)
    return "CALCULATETABLE(\n" + indented_body + ",\n    " + filter_block + "\n)"


def _format_measure_binding(measure: MeasurePlan, table: str) -> str:
    reference = f"{table}[{measure.measure_name}]"
    if not measure.group_filters:
        return f'"{measure.measure_name}", {reference}'

    filter_block = ",\n        ".join(measure.group_filters)
    return (
        f'"{measure.measure_name}", CALCULATE(\n'
        f'        {reference},\n'
        f'        {filter_block}\n'
        f'    )'
    )


__all__ = ["render_visual_plan", "DEFAULT_MEASURE_TABLE"]
