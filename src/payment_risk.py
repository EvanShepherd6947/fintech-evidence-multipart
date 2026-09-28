from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class UploadDecision:
    action: Literal["multipart_upload", "manual_review"]
    reason: str


def decide_upload(
    risk_level: Literal["low", "medium", "high"], amount_minor: int
) -> UploadDecision:
    if risk_level == "high" or amount_minor >= 1_000_000:
        return UploadDecision(
            "manual_review", "risk policy requires approval before media intake"
        )
    return UploadDecision(
        "multipart_upload", "payment evidence may enter controlled storage"
    )
