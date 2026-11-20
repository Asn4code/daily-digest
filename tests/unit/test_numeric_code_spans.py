"""Literal code cannot disable numeric formatting checks for the whole source."""

import pytest

from digest.llm.quantities import quantities, view
from digest.llm.validator import ValidationError
from tests.unit.test_quantity_context import check


@pytest.mark.parametrize("delimiter", ["`", "``"])
@pytest.mark.parametrize("literal", ["SRR123_456", "1_2", "1*2", "1**2", "1__2"])
def test_literal_code_keeps_other_cited_markdown_readable(delimiter, literal):
    source = f"Identificador {delimiter}{literal}{delimiter}. Se registraron 3 `partial`."
    check(source, "Se registraron 3 `partial`.")
    check(source, "Se registraron 3 partial.")


@pytest.mark.parametrize(
    "text,invented",
    [
        ("**85**96 y `1_2`.", 8596),
        ("`85_96` y **85**96.", 8596),
        ("**85**&#57;&#54; y `85_96`.", 8596),
        ("1*&#50;*3 y `SRR123_456`.", 123),
        ("1*2*3 y `&#1*2;`.", 123),
        ("1*2*3 y `&#01*2;`.", 123),
        ("1*2*3 y `&#x1*2;`.", 123),
    ],
)
def test_code_occurrences_do_not_cover_a_numeric_join_outside_code(text, invented):
    assert all(quantity.value != invented for quantity in quantities(view(text)))


@pytest.mark.parametrize("assertion", ["RMSD 1.4 nm.", "Se registraron 4 partial."])
def test_literal_code_does_not_authorize_other_dimensions_or_counts(assertion):
    source = "Identificador `SRR123_456`. RMSD **1.4** *Å*. Se registraron 3 `partial`."
    with pytest.raises(ValidationError):
        check(source, assertion)


@pytest.mark.parametrize("control", ["\x00", "\x01", "\x0b", "\x0c", "\x1f", "\x7f", "\u200b"])
def test_markdown_cannot_replace_a_control_to_hide_an_added_unit(control):
    with pytest.raises(ValidationError):
        check("Valor 12.", "Valor 12" + control + "nm.")
