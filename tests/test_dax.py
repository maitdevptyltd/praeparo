from praeparo.dax import build_matrix_query
from praeparo.models import MatrixConfig, MatrixFilterConfig, MatrixTotals, MatrixValueConfig
from praeparo.templating import FieldReference


def test_build_matrix_query_constructs_summarizecolumns(snapshot) -> None:
    config = MatrixConfig(
        type="matrix",
        rows=["{{dim.City}}"],
        values=[MatrixValueConfig(id="Total Sales", label="Sales")],
        totals=MatrixTotals.OFF,
    )

    row_fields = [FieldReference(expression="dim.City", table="dim", column="City")]

    plan = build_matrix_query(config, row_fields)

    assert plan.statement == snapshot
    assert plan.define is None


def test_build_matrix_query_includes_filters(snapshot) -> None:
    config = MatrixConfig(
        type="matrix",
        rows=["{{dim.City}}"],
        values=[MatrixValueConfig(id="Total Sales", label="Sales")],
        filters=[MatrixFilterConfig(field="dim.City", include=["Seattle", "Portland"])],
    )

    row_fields = [FieldReference(expression="dim.City", table="dim", column="City")]

    plan = build_matrix_query(config, row_fields)

    assert plan.statement == snapshot
    assert plan.define is None




def test_build_matrix_query_supports_expression_filter(snapshot) -> None:
    config = MatrixConfig(
        type="matrix",
        rows=["{{dim.City}}"],
        values=[MatrixValueConfig(id="Total Sales", label="Sales")],
        filters=[MatrixFilterConfig(expression='dim[City] <> "Unknown"')],
    )

    row_fields = [FieldReference(expression="dim.City", table="dim", column="City")]

    plan = build_matrix_query(config, row_fields)

    assert plan.statement == snapshot
    assert plan.define is None


def test_build_matrix_query_with_define(snapshot) -> None:
    config = MatrixConfig(
        type="matrix",
        define="MEASURE Sales[Total Sales] = SUM(Sales[Amount])",
        rows=["{{Sales.Region}}"],
        values=[MatrixValueConfig(id="Total Sales", label="Total Sales")],
    )

    row_fields = [FieldReference(expression="Sales.Region", table="Sales", column="Region")]

    plan = build_matrix_query(config, row_fields)

    assert plan.statement == snapshot
    assert plan.define == "MEASURE Sales[Total Sales] = SUM(Sales[Amount])"

