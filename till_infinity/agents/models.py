"""What an agent returns.

The output is a schema rather than prose because the consumer is code: an
alert is routed by `level`, deduped by `key`, and dropped below a confidence
floor. Free text would make all three guesswork.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator

#: Tool-call syntax, which a model quotes when asked to show its working and
#: which means nothing to the person a notification reaches.
TOOL_CALL = re.compile(r"\s*\(?\bfrom\s+[\w.]+\([^)]*\)\)?|\b[\w]+\.[\w]+\([^)]*\)")


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
        description=(
            "The specific figures and what they mean, in plain words. Not the"
            " tool calls that produced them - the reader gets a notification"
            " and cannot run them."
        ),
    )

    @field_validator("evidence", mode="after")
    @classmethod
    def _strip_calls(cls, values: list[str]) -> list[str]:
        """Take the plumbing out of the evidence.

        The prompt asks for figures and says not to cite the call, which the
        model mostly honours and did not here: it published
        `(from default_api.spreads(feed='btc'))` to the channel - a namespace
        belonging to how the model is wired to its tools, not to anything about
        the market. `default_api` is not even ours.

        A prompt is a request. This is the guarantee, and it lives on the model
        rather than at the alert so the journal gets the same treatment: an
        evidence string is read back by `facto` and by a person reviewing a
        call months later, and neither is helped by a function signature.
        """
        cleaned = []
        for value in values:
            text = TOOL_CALL.sub("", value).strip(" ;,")
            # Collapse the double spaces removing a clause leaves behind.
            text = re.sub(r"\s{2,}", " ", text)
            if text:
                cleaned.append(text)
        return cleaned

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
