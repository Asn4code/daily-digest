"""A timestamp's timezone is provenance, not a second unsupported clock."""

import pytest

from digest.llm.schemas import Claim
from digest.llm.validator import EvidencePackage, ValidationError, validate
from digest.report.model import EvidenceEntry


def package(
    event="2026-11-09T10:04:32+00:00",
    observed="2026-11-16T13:08:23+00:00",
    excerpt="Nota sin medidas.",
):
    entry = EvidenceEntry(
        "ev_time", "benchmark", "task_note", "task#note", excerpt, observed, event, "event", {}
    )
    return EvidencePackage({entry.id: entry}, {"benchmark"})


@pytest.mark.parametrize(
    "stamp",
    [
        "2026-11-09T10:04:32+00:00",
        "2026-11-16T13:08:23+00:00",
        "2026-11-09T10:04:32Z",
        "2026-11-16T13:08:23Z",
        "2026-11-09t10:04:32z",
    ],
)
def test_exact_cited_event_or_observed_utc_stamp_is_accepted(stamp):
    validate(Claim(text="Fecha de procedencia: " + stamp, evidence=["ev_time"]), package())


def test_exact_fractional_timestamp_is_accepted_without_rounding():
    stamp = "2026-11-09T10:04:32.123456+00:00"
    validate(Claim(text="Fecha: " + stamp, evidence=["ev_time"]), package(event=stamp))


@pytest.mark.parametrize(
    "stamp",
    [
        "2026-11-09T13:08:23+00:00",  # Mixes the event date with the observed clock.
        "2026-11-16T10:04:32+00:00",  # Mixes the observed date with the event clock.
        "2026-11-09T10:04:33+00:00",
        "2026-11-09T10:04:32+01:00",
        "2026-11-09T11:04:32+01:00",
        "2026-11-09T10:04:32.123456+00:00",
        "2026-11-09t13:08:23Z",
        "2026-11-09T13:08:23",
        "2026-11-09T13:08:23Zobservada",
        "2026-11-09T10:04:32+00:00.RMSD999",
    ],
)
def test_unquoted_mixed_or_changed_timestamp_is_not_supported(stamp):
    with pytest.raises(ValidationError):
        validate(Claim(text="Fecha: " + stamp, evidence=["ev_time"]), package())


def test_accepting_provenance_does_not_accept_an_unrelated_measurement():
    with pytest.raises(ValidationError):
        validate(
            Claim(text="Fecha 2026-11-09T10:04:32+00:00; RMSD 999 Å.", evidence=["ev_time"]),
            package(),
        )


def test_timestamp_only_supported_by_a_different_uncited_entry_is_rejected():
    scope = package()
    scope.evidence["ev_other"] = EvidenceEntry(
        "ev_other",
        "benchmark",
        "task_note",
        "other",
        "Otra nota.",
        "2026-11-12T01:02:03+00:00",
        None,
        "observed",
        {},
    )
    with pytest.raises(ValidationError):
        validate(Claim(text="Fecha 2026-11-12T01:02:03+00:00.", evidence=["ev_time"]), scope)
