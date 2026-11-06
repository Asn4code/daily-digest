"""Keep every validated source finding in a result fiche, without a summary cutoff."""

from digest.llm.schemas import ResultFiche, SourceFindings

VERSION = "3"


def assemble(result_id: str, findings: list[SourceFindings]) -> ResultFiche:
    return ResultFiche(result_id=result_id, sources=findings)
