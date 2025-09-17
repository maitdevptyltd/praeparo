from praeparo.templating import FieldReference, extract_field_references


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
