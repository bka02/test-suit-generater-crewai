"""Pydantic schema enforced on QACrew output via task.output_pydantic."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class TestCategory(str, Enum):
    HAPPY_PATH = "happy_path"
    BOUNDARY_EDGE_CASE = "boundary_edge_case"
    SECURITY_VALIDATION = "security_validation"


class TestPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TestStep(BaseModel):
    step_number: int
    action: str
    expected_result: str


class TestCase(BaseModel):
    id: str = Field(default_factory=lambda: "TC-" + uuid.uuid4().hex[:8].upper())
    title: str
    category: TestCategory
    priority: TestPriority
    description: str
    preconditions: list[str]
    steps: list[TestStep]
    expected_outcome: str
    tags: list[str]
    notes: Optional[str] = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Test case title must not be empty.")
        return v


class AssembledSuite(BaseModel):
    """Shape the QA reviewer must produce: story summary + list of test cases."""

    story_summary: str
    test_cases: list[TestCase]
