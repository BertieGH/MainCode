"""The evaluation contract: a verdict that has to say what is wrong.

`evaluation` carries a database constraint — a `warn` or `fail` with no issues
recorded is rejected outright. That constraint exists because a verdict nobody
can act on is worse than no verdict: it stops the pipeline and tells the rep
nothing, so the rep learns to override it, and then the check is decoration.

This contract enforces the same rule one layer earlier, where the model can
still be told to try again, rather than as an IntegrityError at flush time.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Verdict = Literal["pass", "warn", "fail"]
#: Mirrors the `subject_type_valid` check on the table.
SubjectType = Literal[
    "research", "signal", "qualification", "strategy",
    "outreach_sequence", "draft", "sales_prep", "execution",
]


class EvaluationIssue(BaseModel):
    """One specific, locatable problem."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    #: Written for the rep who has to decide, not for a log.
    detail: str = Field(min_length=1)
    severity: Literal["warn", "fail"] = "warn"
    #: Where in the subject — a step number, a thread, a dimension name.
    locus: str | None = None
    #: What would fix it. Optional, because sometimes nothing would.
    suggestion: str | None = None


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    issues: list[EvaluationIssue] = Field(default_factory=list)
    #: Per-criterion 0–1 scores, free-form by criterion name. Stored to
    #: `evaluation.scores` so drift in a single criterion is visible before
    #: the overall verdict flips.
    scores: dict[str, Annotated[float, Field(ge=0.0, le=1.0)]] = Field(
        default_factory=dict
    )
    summary: str | None = None

    @model_validator(mode="after")
    def _a_non_pass_says_what_is_wrong(self) -> EvaluationResult:
        if self.verdict != "pass" and not self.issues:
            raise ValueError(
                f"verdict {self.verdict!r} with no issues: the database rejects this, "
                "and a rep cannot act on it"
            )
        if self.verdict == "pass" and any(i.severity == "fail" for i in self.issues):
            raise ValueError("verdict 'pass' cannot carry an issue of severity 'fail'")
        if self.verdict == "warn" and any(i.severity == "fail" for i in self.issues):
            raise ValueError(
                "verdict 'warn' cannot carry an issue of severity 'fail' — "
                "a failing issue makes the verdict 'fail'"
            )
        return self

    @property
    def blocking(self) -> list[EvaluationIssue]:
        return [i for i in self.issues if i.severity == "fail"]
