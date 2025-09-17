from praeparo.dax import build_matrix_query
from praeparo.models import MatrixConfig, MatrixValueConfig, MatrixTotals
from praeparo.templating import FieldReference


def test_build_matrix_query_constructs_summarizecolumns() -> None:
    config = MatrixConfig(
        type="matrix",
        rows=["{{dim.City}}"],
        values=[MatrixValueConfig(id="Total Sales", label="Sales")],
        totals=MatrixTotals.OFF,
    )

    row_fields = [FieldReference(expression="dim.City", table="dim", column="City")]

    plan = build_matrix_query(config, row_fields)

    assert "SUMMARIZECOLUMNS" in plan.statement
    assert "dim[City]" in plan.statement
    assert '"Sales", [Total Sales]' in plan.statement
