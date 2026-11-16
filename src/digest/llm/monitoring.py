"""Small scientific context pieces for hierarchical monitoring, never human states."""

from typing import Annotated

from pydantic import Field

from digest.llm.schemas import Output, Text


class MonitoringClaim(Output):
    text: Annotated[str, Field(min_length=1, max_length=600)]
    evidence: Annotated[list[Text], Field(min_length=1, max_length=8)]


class MonitoringContext(Output):
    observations: list[MonitoringClaim] = Field(max_length=4)
    interpretations: list[MonitoringClaim] = Field(max_length=2)
    controls: list[MonitoringClaim] = Field(max_length=3)
    limits: list[MonitoringClaim] = Field(min_length=1, max_length=3)
    open_questions: list[MonitoringClaim] = Field(max_length=2)
