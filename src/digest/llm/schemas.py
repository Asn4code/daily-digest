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
    summary: Claim
    observations: list[Claim] = Field(max_length=100)
    interpretations: list[Interpretation] = Field(max_length=100)
    controls: list[Claim] = Field(max_length=100)
    limitations: list[Claim] = Field(max_length=100)
    open_questions: list[Claim] = Field(max_length=100)


class ResultFiche(Output):
    result_id: Text
    sources: list[SourceFindings] = Field(min_length=1, max_length=1000)


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


class CompactClaim(Claim):
    text: Annotated[str, Field(min_length=1, max_length=600)]
    evidence: Annotated[list[Text], Field(min_length=1, max_length=8)]


class CompactInterpretation(CompactClaim):
    confidence: Literal["low", "medium", "high"]


class ResultExplanation(Output):
    result_id: Text
    question: Claim | None
    observations: list[Claim] = Field(min_length=1, max_length=5)
    meaning: Interpretation | None
    controls: list[Claim] = Field(max_length=5)
    limits: list[Claim] = Field(min_length=1, max_length=5)
    decision_impact: Claim | None
    next_question: Claim | None


class ProjectDigest(Output):
    project_id: Text
    explanation: Claim
    importance: Interpretation
    known_now: list[Claim] = Field(max_length=5)
    still_unknown: list[Claim] = Field(max_length=5)
    decisions_changed: list[Claim] = Field(max_length=5)
    no_new_conclusion: bool
    reading_conditions: list[CompactClaim] = Field(max_length=2)
    results: list[ResultExplanation] = Field(min_length=1, max_length=1000)


class DailyHighlight(Output):
    project_id: Text
    result_ids: list[Text] = Field(min_length=1, max_length=100)
    observation: CompactClaim
    meaning: CompactInterpretation
    decisive_limit: CompactClaim


class DailyOverview(Output):
    highlights: list[DailyHighlight] = Field(max_length=3)
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


class DailyMission(PlanItem):
    action: Annotated[str, Field(min_length=1, max_length=350)]
    done_criterion: Annotated[str, Field(min_length=1, max_length=350)]
    reason: Annotated[str, Field(min_length=1, max_length=600)]
    dependency: Annotated[str, Field(min_length=1, max_length=240)] | None
    project_id: Text
    priority_basis: list[
        Literal[
            "scientific_value", "decision", "control", "dependency", "human_commitment", "kanvas"
        ]
    ] = Field(min_length=1, max_length=6)
    decision_unlocked: Annotated[str, Field(min_length=1, max_length=300)] | None
    uncertainty_addressed: CompactClaim | None
    human_plan_id: int | None


class DailyWarmup(PlanItem):
    project_id: Text


class TomorrowPlan(Output):
    mission: DailyMission | None
    warmups: list[DailyWarmup] = Field(max_length=2)
    carry_forward_id: int | None
    change_reason: Claim | None
    no_mission_reason: Claim | None


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


class Prediction(Output):
    alternative_index: Annotated[int, Field(ge=0, le=3)]
    expected_observation: Text


class AnalysisProposal(Output):
    question: Text
    alternatives: list[Text] = Field(min_length=2, max_length=4)
    required_data: Text
    control: Text
    predictions: list[Prediction] = Field(min_length=2, max_length=4)
    decision_criterion: Text
    dependency: Text | None
    evidence: References


class ConclusionCheck(Output):
    conclusion_id: Text
    new_evidence: References
    outcome: Literal["reinforces", "qualifies", "challenges", "inconclusive", "no_material_change"]
    comparable: bool
    comparability: Claim
    assessment: CompactInterpretation
    decisive_limit: CompactClaim
    alternative_explanations: list[Claim] = Field(max_length=5)
    analyses: list[AnalysisProposal] = Field(max_length=3)
    focus_implication: CompactClaim


class WeeklyCritical(Output):
    project_id: Text
    progress_vs_objective: list[Claim] = Field(min_length=1, max_length=6)
    decisions: list[Claim] = Field(max_length=6)
    hypotheses_changed: list[Interpretation] = Field(max_length=6)
    checks: list[ConclusionCheck] = Field(max_length=20)
    no_comparison_reason: Claim | None


class WeeklyObjective(PlanItem):
    project_id: Text
    critical_ids: list[Text] = Field(max_length=20)


class ReviewSummary(Output):
    completed: list[Text] = Field(max_length=1000)
    pending: list[Text] = Field(max_length=1000)
    doubts: list[Claim] = Field(max_length=100)


class WeeklyReport(Output):
    projects: list[WeeklyProject] = Field(max_length=100)
    patterns: list[Claim] = Field(max_length=100)
    key_figures: list[Text] = Field(max_length=6)
    review_status: ReviewSummary
    next_week: list[WeeklyObjective] = Field(min_length=3, max_length=4)
    critical_highlights: list[Text] = Field(max_length=3)


class GroundingIssue(Output):
    rule: Literal[
        "unsupported_claim", "missing_condition", "certainty_overstated", "unhelpful_focus"
    ]
    field: list[str | int] = Field(max_length=8)
    evidence: Annotated[list[Text], Field(min_length=1, max_length=8)]
    source_quote: Annotated[str, Field(min_length=1, max_length=600)]


class GroundingAudit(Output):
    approved: bool
    issues: list[GroundingIssue] = Field(max_length=5)
