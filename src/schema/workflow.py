from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class StepResult(BaseModel):
    name: str
    status: Literal["success", "failed"] = "success"
    duration_sec: float
    output: str


class WorkflowResult(BaseModel):
    workflow_id: str
    input_text: str
    steps: list[StepResult]
    summary: str
    keywords: list[str]
    started_at: datetime
    finished_at: datetime = Field(default_factory=datetime.now)

    @property
    def total_sec(self) -> float:
        return round(sum(s.duration_sec for s in self.steps), 2)
