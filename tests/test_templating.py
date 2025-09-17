from praeparo.templating import FieldReference, extract_field_references, render_template, label_from_template


def test_extract_field_references_deduplicates_in_order() -> None:
    templates = [
        "{{dim.Account}}",
        "{{fact.metric | default(0)}}",
        "{{dim.Account}}",
    ]

    references = extract_field_references(templates)

    assert references == [
        FieldReference(expression="dim.Account", table="dim", column="Account"),
        FieldReference(expression="fact.metric", table="fact", column="metric"),
    ]


def test_render_template_substitutes_placeholders() -> None:
    template = "{{dim.City}} / {{fact.metric}}"
    values = {"dim.City": "Seattle", "fact.metric": 42}

    result = render_template(template, values)

    assert result == "Seattle / 42"


def test_label_from_template_uses_column_names() -> None:
    template = "{{dim.City}} ({{dim.State}})"
    references = [
        FieldReference(expression="dim.City", table="dim", column="City"),
        FieldReference(expression="dim.State", table="dim", column="State"),
    ]

    label = label_from_template(template, references)

    assert label == "City (State)"
