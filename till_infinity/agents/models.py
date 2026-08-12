"""What an agent returns.

The output is a schema rather than prose because the consumer is code: an
alert is routed by `level`, deduped by `key`, and dropped below a confidence
floor. Free text would make all three guesswork.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field


class Finding(BaseModel):
    """One thing worth saying, and how sure the model is that it is real."""

    title: str = Field(description="One line, specific. Name the instrument and the venue.")
    detail: str = Field(
        default="",
        description="What the numbers were, and why they matter. Two sentences at most.",
    )
    level: str = Field(
        default="info",
        description="info, warning or critical. critical means a human should look now.",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="How strongly the data supports this. Below 0.5 it will not be sent.",
    )
    instrument: str = Field(default="", description="feed name, e.g. gold, btc, eurusd")
    evidence: list[str] = Field(
        default_factory=list,
        description="The specific figures you relied on, so a human can check them.",
    )

    @property
    def key(self) -> tuple[str, str]:
        """What makes two findings 'the same alert' for deduplication.

        Whitespace is collapsed, not just stripped: the same observation from
        two runs is the same alert even when the model spaces it differently.
        """
        return (self.instrument.strip().lower(), " ".join(self.title.lower().split()))


class Analysis(BaseModel):
    """A full answer: the prose summary plus anything worth alerting on."""

    summary: str = Field(description="What is going on, in two or three sentences.")
    findings: list[Finding] = Field(
        default_factory=list,
        description="Only things the data actually supports. An empty list is a valid answer.",
    )


@dataclass(slots=True)
class Run:
    """One completed analysis, with what it cost."""

    analysis: Analysis
    role: str = ""
    model: str = ""
    elapsed: float = 0.0
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __str__(self) -> str:
        parts = [f"{len(self.analysis.findings)} finding(s)"]
        if self.tokens:
            parts.append(f"{self.tokens:,} tokens")
        parts.append(f"{self.elapsed:.1f}s")
        return ", ".join(parts)


@dataclass(slots=True)
class Trigger:
    """Why the watcher decided to wake the model.

    Kept as data rather than a log line because it is also the prompt: the
    model is told what changed, then goes and queries the detail itself.
    """

    reason: str
    topic: str
    payload: dict[str, object] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.reason
