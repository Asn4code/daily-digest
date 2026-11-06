"""Strict, bounded scientific outputs; human review states are never generated."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(min_length=1, max_length=4000)]
Texts = Annotated[list[Text], Field(max_length=100)]
References = Annotated[list[Text], Field(min_length=1, max_length=100)]


class Output(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, allow_inf_nan=False, hide_input_in_errors=True
    )


class Claim(Output):
    text: Text
    evidence: References


class Number(Output):
    name: Text
    value: float
    unit: Text | None
    evidence: Text


class Interpretation(Claim):
    confidence: Literal["low", "medium", "high"]


class ResultExtraction(Output):
    result_id: Text
    summary: Text
    facts: list[Claim] = Field(max_length=100)
    numbers: list[Number] = Field(max_length=100)
    interpretations: list[Interpretation] = Field(max_length=100)
    uncertainties: Texts
    controls_and_parameters: list[Claim] = Field(max_length=100)
    failures_or_blockers: list[Claim] = Field(max_length=100)
    open_threads: list[Claim] = Field(max_length=100)


class SourceFindings(Output):
    result_id: Text
    summary: Text
    observations: list[Claim] = Field(max_length=100)
    interpretations: list[Interpretation] = Field(max_length=100)
    controls: list[Claim] = Field(max_length=100)
    limitations: Texts
    open_questions: list[Claim] = Field(max_length=100)


class ProjectBalance(Output):
    project_id: Text
    known_now: list[Claim] = Field(max_length=100)
    still_unknown: Texts
    decisions_changed: list[Claim] = Field(max_length=100)
    no_new_conclusion: bool


class ReviewCandidate(Output):
    result_id: Text
    why: Text
    evidence: References


class DailySynthesis(Output):
    highlights: list[Claim] = Field(max_length=3)
    projects: list[ProjectBalance] = Field(max_length=100)
    review_candidate: ReviewCandidate | None


class PlanItem(Output):
    kind: Literal["mission", "warmup"]
    action: Text
    done_criterion: Text
    dependency: Text | None
    reason: Text
    origin: Literal["kanvas", "model", "review"]
    kanvas_task_id: Text | None
    evidence: References


class TomorrowPlan(Output):
    mission: PlanItem
    warmups: list[PlanItem] = Field(max_length=2)


class ClaimWhy(Output):
    text: Text
    why: Text


class Contrast(Output):
    supported: list[Claim] = Field(max_length=100)
    omissions: list[Claim] = Field(max_length=100)
    unsupported: list[ClaimWhy] = Field(max_length=100)
    unverifiable: list[ClaimWhy] = Field(max_length=100)
    summary_errors: list[Claim] = Field(max_length=100)


class WeeklyProject(Output):
    project_id: Text
    progress_vs_objective: list[Claim] = Field(max_length=100)
    decisions: list[Claim] = Field(max_length=100)
    hypotheses_changed: list[Interpretation] = Field(max_length=100)


class ReviewSummary(Output):
    completed: list[Text] = Field(max_length=1000)
    pending: list[Text] = Field(max_length=1000)
    doubts: list[Claim] = Field(max_length=100)


class WeeklyReport(Output):
    projects: list[WeeklyProject] = Field(max_length=100)
    patterns: list[Claim] = Field(max_length=100)
    key_figures: list[Text] = Field(max_length=6)
    review_status: ReviewSummary
    next_week: list[PlanItem] = Field(min_length=3, max_length=4)
