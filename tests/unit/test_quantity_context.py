"""Cited numeric roles survive prose and formatting without invented dimensions."""

from copy import deepcopy

import pytest

from digest.llm.schemas import Claim
from digest.llm.validator import EvidencePackage, ValidationError, validate
from digest.report.model import EvidenceEntry


def package(excerpt):
    e = EvidenceEntry(
        "ev_source",
        "p",
        "task_note",
        "TEST-01",
        excerpt,
        "2026-11-09T12:00:00+00:00",
        None,
        "observed",
        {},
    )
    return EvidencePackage({e.id: e}, {"p"})


def check(source, claim):
    value = package(source)
    before = deepcopy(value)
    validate(Claim(text=claim, evidence=["ev_source"]), value)
    assert value == before


@pytest.mark.parametrize(
    "source,claim",
    [
        ("Completo, 12 de 12 (1ABC_A terminó).", "Completo, 12 de 12 (1ABC_A terminó)."),
        ("Se registraron 3 `partial`.", "Se registraron 3 `partial`."),
        ("Semillas 1-5 con el protocolo A.", "Semillas 1-5 mediante el protocolo A."),
        (
            "Cobertura 12 de 20 pares; 11 al incluir el control.",
            "Cobertura 12 de 20 pares; 11 si se incluye el control.",
        ),
        ("El lote 1 quedó archivado.", "El lote 1 quedó archivado."),
        ("Se registraron 199 from_scratch.", "Se registraron 199 `from_scratch`."),
        ("RMSD **1.4** *Å*.", "RMSD `1.4` Å."),
        ("Energía 1.4 kJ/mol.", "Energía **1.4** k**J**/mol."),
        ("Densidad 1.4 kg m^-3.", "Densidad 1.4 **kg** m^-3."),
        ("Semillas 1–5.", "Semillas 1-5."),
        ("Se completaron 12/12.", "Se completaron 12 de 12."),
    ],
)
def test_supported_prose_uses_a_common_numeric_view(source, claim):
    check(source, claim)


@pytest.mark.parametrize(
    "claim",
    [
        "RMSD: 1.4 / 12 (1ABC_A).",
        "RMSD: 1.4 * 12 (1ABC_A).",
        "RMSD: 1.4 + 12 (1ABC_A).",
        "RMSD: 12 (1ABC_A) nm.",
        "RMSD: 12 (1ABC_A nm).",
        "RMSD: 12 (1ABC_A) (nm).",
        "RMSD: 12 (1ABC_A) / nm.",
        "RMSD: 1.4*(1ABC_A).",
        "RMSD: 1.4 / `1ABC_A`.",
        "RMSD: 1.4 Å/**1ABC_A**.",
        "RMSD: 1.4 1ABC_A.",
        "Se declara 13 de 12 (1ABC_A terminó).",
        "Se declara 12 de 12 (1ABC_B terminó).",
    ],
)
def test_parenthetical_identity_preserves_operators_and_dimensions(claim):
    with pytest.raises(ValidationError):
        check("Completo, 12 de 12 (1ABC_A terminó). RMSD 1.4 Å.", claim)


@pytest.mark.parametrize(
    "source,claim",
    [
        ("Semillas 1-5.", "Se dispone de 5 semillas."),
        ("Semillas 1-5; semillas 6-10.", "Semillas 1-10."),
        ("Cobertura 12/20 pares y 3/8 muestras.", "Cobertura 12/8 muestras."),
        ("Valor 1.4. Recuento 12.", "Valor 1.4 * 12."),
        ("Valor 1.4. Recuento 12.", "Valor 1.4 (12)."),
        ("Se midió 1.4 (0.2 Å). También 0.2 nm.", "Se midió 1.4 (0.2 nm)."),
        ("RMSD 1.4 Å.", "RMSD 1.4 `nm`."),
        ("RMSD 1.4 Å.", "RMSD **1.4** n**m**."),
        ("RMSD 1.4 Å.", "RMSD __1.4__ nm."),
        ("RMSD 1.4 Å.", "RMSD -1.4 Å."),
        ("RMSD 1.4 Å.", "RMSD 1.4*nm."),
        ("RMSD 1.4 Å.", "RMSD 1.4 Å*kg."),
        ("RMSD 1.4 Å.", "RMSD 1.4 Å / kg."),
        ("RMSD 1.4 Å.", "RMSD 1.4 _nm."),
        ("Valor 1.4 m_s.", "Valor 1.4 ms."),
        ("Valor 1.4 ms.", "Valor 1.4 m_s."),
        ("Se registraron 3 `partial`.", "Se registraron 3 `from_scratch`."),
        ("Concentración 1.4 M.", "Concentración 1.4 m."),
        ("Semillas 1-5.", "Semillas 1-5 nm."),
    ],
)
def test_numeric_associations_cannot_be_recombined_or_relabelled(source, claim):
    with pytest.raises(ValidationError):
        check(source, claim)


def test_other_evidence_cannot_supply_an_operand_or_dimension():
    value = package("Semillas 1-5. RMSD 1.4 Å.")
    other = deepcopy(value.evidence["ev_source"])
    other.id = "ev_other"
    other.excerpt = "Semillas 6-10. RMSD 1.4 nm."
    value.evidence[other.id] = other
    for claim in ["Semillas 1-10.", "RMSD 1.4 nm."]:
        with pytest.raises(ValidationError):
            validate(Claim(text=claim, evidence=["ev_source"]), value)
    # Even citing both sources cannot turn independent ranges into a new range.
    with pytest.raises(ValidationError):
        validate(Claim(text="Semillas 1-10.", evidence=["ev_source", "ev_other"]), value)


@pytest.mark.parametrize(
    "claim",
    [
        "RMSD 1.4 Å * kg.",
        "RMSD 1.4 Å / 2.",
        "RMSD 1.4 Å/2.",
        "RMSD 1.4 Å **/** 2.",
        "RMSD 1.4 Å + 2.",
        "RMSD 1.4 Å ^ 2.",
        "RMSD 1.4 Å · 2.",
    ],
)
def test_a_unit_cannot_hide_a_new_operation_or_operand(claim):
    with pytest.raises(ValidationError):
        check("RMSD 1.4 Å. Se conservan 2 estructuras.", claim)


def test_every_count_in_a_slash_separated_inventory_is_checked():
    check("51 estructuras, 30 pares.", "51 estructuras/30 pares.")
    with pytest.raises(ValidationError):
        check("51 estructuras, 30 pares.", "51 estructuras/999 pares.")


@pytest.mark.parametrize("operator", ["÷", "=", "<", ">", "≤", "≥", "!=", "≈", "por", "entre"])
def test_a_new_relation_between_independently_cited_values_is_rejected(operator):
    with pytest.raises(ValidationError):
        check("Valor 1.4. Recuento 12.", "Valor 1.4 " + operator + " 12.")


@pytest.mark.parametrize("operator", ["/", "*", "+", "÷"])
def test_operator_inside_annotation_cannot_hide_a_dimension(operator):
    with pytest.raises(ValidationError):
        check(
            "Completo, 12 de 12 (1ABC_A terminó).",
            "Completo, 12 de 12 (1ABC_A " + operator + " nm).",
        )


@pytest.mark.parametrize(
    "source,claim",
    [
        ("Valor 123.", "Valor 1*2*3."),
        ("Valor 123.", "Valor 1 *2* 3."),
        ("Valor 14.", "Valor 1_4."),
        ("Valor 1.4 m2_s.", "Valor 1.4 m2s."),
        ("Valor 1.4 m2s.", "Valor 1.4 m2_s."),
    ],
)
def test_formatting_cannot_concatenate_values_or_dimensions(source, claim):
    with pytest.raises(ValidationError):
        check(source, claim)


@pytest.mark.parametrize("claim", ["Valor 1*&#50;*3.", "Valor 1&#42;2&#42;3."])
def test_encoded_markers_cannot_join_numeric_fragments(claim):
    with pytest.raises(ValidationError):
        check("Valor 123.", claim)


def test_an_internal_identity_marker_cannot_be_supplied_by_a_model():
    with pytest.raises(ValidationError):
        check(
            "Completo, 12 de 12 (1ABC_A terminó).", "Completo, 12 de 12 (PDBTOKEN1ABC_A terminó)."
        )


@pytest.mark.parametrize("operand", ["+2", "-2", "+ 2", "- 2", "+.2", "-.2"])
def test_binary_sign_cannot_be_hidden_in_the_next_operand(operand):
    with pytest.raises(ValidationError):
        check("RMSD 1.4 Å. Recuento 2. Otra medida 0.2.", "RMSD 1.4 Å " + operand + ".")


@pytest.mark.parametrize(
    "source,claim",
    [
        ("Valor 1.4 / nm.", "Valor 1.4 / kg."),
        ("Valor 1.4 : nm.", "Valor 1.4 : kg."),
        ("Recuento 12. Otro valor 20.", "Razón 12:20."),
        ("Valor 12 (nota abierta", "Valor 12 (nm"),
    ],
)
def test_unsupported_syntax_cannot_erase_a_dimension_or_relation(source, claim):
    with pytest.raises(ValidationError):
        check(source, claim)


@pytest.mark.parametrize(
    "range_text",
    ["1 a 12", "1 hasta 12", "entre 1 y 12", "1..12", "1...12", "1…12", "1..999", "1...999"],
)
def test_a_range_cannot_be_built_from_independent_scalars(range_text):
    with pytest.raises(ValidationError):
        check("Semilla 1. Semilla 12.", "Semillas " + range_text + ".")


@pytest.mark.parametrize("claim", ["Valor 1.2.999.", "Valor 1,2.999."])
def test_malformed_numeric_runs_cannot_hide_a_suffix(claim):
    with pytest.raises(ValidationError):
        check("Valor 1.2.", claim)


def test_annotations_are_bound_for_every_operand_in_one_source():
    value = package("Valor 1 (control A) + 2 (control B).")
    other = deepcopy(value.evidence["ev_source"])
    other.id = "ev_other"
    other.excerpt = "Valor 1 (control C) + 2 (control D)."
    value.evidence[other.id] = other
    with pytest.raises(ValidationError):
        validate(
            Claim(text="Valor 1 (control A) + 2 (control D).", evidence=["ev_source", "ev_other"]),
            value,
        )


def test_encoded_range_markers_do_not_hide_an_endpoint():
    with pytest.raises(ValidationError):
        check("Valor 1.", "Intervalo 1&#46;&#46;999.")


@pytest.mark.parametrize("operator", ["≡", "∝", "≅"])
def test_unknown_math_relations_fail_closed(operator):
    with pytest.raises(ValidationError):
        check("Valor 1.4. Recuento 12.", "Valor 1.4 " + operator + " 12.")


def test_grouping_cannot_hide_a_binary_sign():
    with pytest.raises(ValidationError):
        check("Valor 1.4. Recuento 12.", "Valor (1.4) +12.")


@pytest.mark.parametrize("claim", ["RMSD 1.4 Å (nm).", "RMSD 1.4 Å = nm.", "RMSD 1.4 Å ∝ nm."])
def test_dimensions_cannot_be_hidden_after_an_existing_dimension(claim):
    with pytest.raises(ValidationError):
        check("RMSD 1.4 Å.", claim)


def test_a_second_annotation_is_not_ignored():
    with pytest.raises(ValidationError):
        check("RMSD 1.4 Å (control).", "RMSD 1.4 Å (control) (nm).")
