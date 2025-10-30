from __future__ import annotations

from praeparo.visuals.dax import MeasurePlan, VisualPlan, render_visual_plan


def test_render_visual_plan_formats_define_and_measures() -> None:
    measures = (
        MeasurePlan(
            reference="documents_sent",
            measure_name="msa_dashboard_documents_sent",
            expression="SUM('fact_documents'[DocumentsSent])",
            display_name="Documents sent",
        ),
        MeasurePlan(
            reference="documents_sent.manual",
            measure_name="msa_dashboard_documents_sent_manual",
            expression="SUM('fact_documents'[DocumentsSent])",
            display_name="Manual documents sent",
            group_filters=("KEEPFILTERS('fact_documents'[IsManual] = TRUE())",),
        ),
    )

    plan = VisualPlan(
        slug="dashboard",
        measures=measures,
        grain_columns=("'dim_calendar'[Month]",),
        define_blocks=("MEASURE 'adhoc'[Existing] = 1",),
        global_filters=("KEEPFILTERS('dim_lender'[LenderId] = 201)",),
    )

    dax = render_visual_plan(
        plan,
        define_blocks=("MEASURE 'adhoc'[Another] = 2",),
    )

    assert dax.startswith("DEFINE\n  TABLE 'adhoc' = { { BLANK() } }")
    assert "MEASURE 'adhoc'[msa_dashboard_documents_sent] =" in dax
    assert "MEASURE 'adhoc'[msa_dashboard_documents_sent_manual] =" in dax
    assert "MEASURE 'adhoc'[Existing] = 1" in dax
    assert "MEASURE 'adhoc'[Another] = 2" in dax

    assert "EVALUATE\nCALCULATETABLE(" in dax
    assert "SUMMARIZECOLUMNS(" in dax
    assert "'dim_calendar'[Month]" in dax

    manual_binding = (
        '"msa_dashboard_documents_sent_manual", CALCULATE(\n'
        "            'adhoc'[msa_dashboard_documents_sent_manual],\n"
        "            KEEPFILTERS('fact_documents'[IsManual] = TRUE())\n"
        "        )"
    )
    assert manual_binding in dax

    assert "CALCULATETABLE(" in dax
    assert "KEEPFILTERS('dim_lender'[LenderId] = 201)" in dax


def test_render_visual_plan_applies_extra_filters() -> None:
    plan = VisualPlan(
        slug="dashboard",
        measures=(
            MeasurePlan(
                reference="documents_sent",
                measure_name="msa_dashboard_documents_sent",
                expression="SUM('fact_documents'[DocumentsSent])",
                display_name="Documents sent",
            ),
        ),
        grain_columns=("'dim_calendar'[Month]",),
        global_filters=("KEEPFILTERS('dim_lender'[LenderId] = 201)",),
    )

    dax = render_visual_plan(
        plan,
        extra_filters=("KEEPFILTERS('dim_calendar'[Month] >= DATE(2025, 1, 1))",),
    )

    assert "KEEPFILTERS('dim_lender'[LenderId] = 201)" in dax
    assert "KEEPFILTERS('dim_calendar'[Month] >= DATE(2025, 1, 1))" in dax


def test_render_visual_plan_allows_summarize_override() -> None:
    plan = VisualPlan(
        slug="dashboard",
        measures=(
            MeasurePlan(
                reference="documents_sent",
                measure_name="msa_dashboard_documents_sent",
                expression="SUM('fact_documents'[DocumentsSent])",
                display_name="Documents sent",
            ),
        ),
        grain_columns=("'dim_calendar'[Month]",),
    )

    dax = render_visual_plan(
        plan,
        summarize_columns=("'dim_branch'[Region]",),
    )

    assert "'dim_branch'[Region]" in dax
    assert "'dim_calendar'[Month]" not in dax
