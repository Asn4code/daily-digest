"""Cited opaque identities are not measurements or a licence for new units."""

import pytest

from digest.llm.schemas import Claim
from digest.llm.validator import EvidencePackage, ValidationError, validate
from digest.report.model import EvidenceEntry

SHA = "90eb888805a55528c8dee5ab313a739eddaccc80"


def scope(kind="commit", locator=SHA, excerpt="PMN: pendientes del lote 1. Resultado 3 Å."):
    entry = EvidenceEntry(
        "ev_git",
        "benchmark",
        kind,
        locator,
        excerpt,
        "2026-11-16T13:00:00+00:00",
        None,
        "observed",
        {},
    )
    return EvidencePackage({entry.id: entry}, {entry.project})


@pytest.mark.parametrize("label", ["commit", "identificador", "hash", "SHA-1"])
def test_cited_full_git_identity_with_provenance_label_is_accepted(label):
    validate(Claim(text=label + ': "' + SHA + '".', evidence=["ev_git"]), scope())


def test_diff_identity_is_supported_by_its_locator():
    validate(
        Claim(text="Commit " + SHA, evidence=["ev_git"]),
        scope(kind="diff", locator=SHA + ":file.md"),
    )


@pytest.mark.parametrize(
    "text",
    [
        "Resultado: 3 " + SHA,
        "El valor es " + SHA + " nm.",
        "Commit " + "80eb888805a55528c8dee5ab313a739eddaccc80",
        "Commit " + SHA + "; RMSD 999 Å.",
    ],
)
def test_identity_never_supports_a_measurement_or_another_object(text):
    with pytest.raises(ValidationError):
        validate(Claim(text=text, evidence=["ev_git"]), scope())


def test_numeric_git_identity_is_only_accepted_as_an_explicit_identity():
    ident = "1" * 40
    validate(Claim(text="Commit " + ident, evidence=["ev_git"]), scope(locator=ident))
    with pytest.raises(ValidationError):
        validate(Claim(text="Valor " + ident + " nm.", evidence=["ev_git"]), scope(locator=ident))


def test_lote_label_can_be_followed_by_normal_grammar_without_becoming_a_unit():
    validate(Claim(text="¿Se ha recuperado el lote 1 mencionado?", evidence=["ev_git"]), scope())
    with pytest.raises(ValidationError):
        validate(Claim(text="Resultado: 3 lote 1.", evidence=["ev_git"]), scope())


def test_scientific_decimal_cannot_be_removed_as_an_identifier_label():
    with pytest.raises(ValidationError):
        validate(Claim(text="El valor del lote 1.5 nm.", evidence=["ev_git"]), scope())


@pytest.mark.parametrize("prefix", ["Commit ", "Hash ", "El valor hash "])
def test_numeric_sha_followed_by_scientific_unit_cannot_hide_measurement(prefix):
    ident = "1" * 40
    with pytest.raises(ValidationError):
        validate(
            Claim(text=prefix + ident + " nm.", evidence=["ev_git"]),
            scope(locator=ident, excerpt="Nota sin cifras."),
        )


@pytest.mark.parametrize("label", ["SHA-1", "SHA1", "SHA-256", "SHA256"])
def test_hash_algorithm_label_is_not_itself_a_measurement(label):
    ident = "a1" * 32 if "256" in label else SHA
    validate(
        Claim(text=label + ": " + ident, evidence=["ev_git"]),
        scope(locator=ident, excerpt="Nota sin cifras."),
    )


def test_uncited_locator_does_not_support_identity():
    package = scope(excerpt="Nota sin cifras.")
    extra = scope(locator="2" * 40).evidence["ev_git"]
    extra.id = "ev_other"
    package.evidence[extra.id] = extra
    with pytest.raises(ValidationError):
        validate(Claim(text="Commit " + "2" * 40, evidence=["ev_git"]), package)


@pytest.mark.parametrize("label", ["lote 1", "batch 1"])
def test_batch_identifier_cannot_hide_an_unsupported_measurement(label):
    with pytest.raises(ValidationError):
        validate(
            Claim(text="Resultado: " + label + " nm.", evidence=["ev_git"]),
            scope(excerpt="Pendiente " + label + ". Resultado 3 Å."),
        )


@pytest.mark.parametrize("ident", ["f" * 40, "abcdef12" * 5, "a" * 64])
def test_unknown_full_hash_is_not_accepted_just_because_no_numeric_token_is_seen(ident):
    with pytest.raises(ValidationError):
        validate(
            Claim(text="Commit " + ident, evidence=["ev_git"]), scope(excerpt="Nota sin cifras.")
        )


def test_alpha_only_shortened_identity_is_not_exempted():
    ident = "abcdefabcdef" + "a" * 28
    with pytest.raises(ValidationError):
        validate(
            Claim(text="Commit " + ident[:12], evidence=["ev_git"]),
            scope(locator=ident, excerpt="Nota sin cifras."),
        )


@pytest.mark.parametrize("suffix", [" (nm)", " [nm]", " / nm", " = nm", "²nm", ".nm", " %"])
@pytest.mark.parametrize("identity", ["git", "batch"])
def test_delimited_measurement_cannot_hide_behind_a_cited_identity(suffix, identity):
    ident = "1" * 40
    text = "Hash " + ident if identity == "git" else "lote 1"
    with pytest.raises(ValidationError):
        validate(Claim(text=text + suffix, evidence=["ev_git"]), scope(locator=ident))


@pytest.mark.parametrize("ident", ["abcd", "abcde", "abcdef"])
def test_git_abbreviations_below_seven_characters_are_not_accepted(ident):
    with pytest.raises(ValidationError):
        validate(Claim(text="Commit " + ident, evidence=["ev_git"]), scope())
