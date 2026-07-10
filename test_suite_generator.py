#!/usr/bin/env python3
"""
test_suite_generator.py

Production-ready script that connects to an LLM API, accepts a user story in
plain text, and automatically generates a structured test suite in JSON format
covering: Happy Paths, Boundary Edge Cases, and Security/Validation scenarios.

Usage:
    python test_suite_generator.py --story "As a user, I want to log in..."
    python test_suite_generator.py --file story.txt --output test_suite.json
    echo "story text" | python test_suite_generator.py --stdin

Requirements:
    pip install openai pydantic tenacity rich python-dotenv
"""

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI, APIConnectionError, APIStatusError, RateLimitError
from pydantic import BaseModel, Field, field_validator
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

# ─── Logging Setup ────────────────────────────────────────────────────────────

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        RichHandler(
            rich_tracebacks=True,
            show_time=True,
            show_path=True,
            markup=True,
        )
    ],
)
logger = logging.getLogger("test_suite_generator")
console = Console()


# ─── Enums & Constants ────────────────────────────────────────────────────────

class TestCategory(str, Enum):
    HAPPY_PATH = "happy_path"
    BOUNDARY_EDGE_CASE = "boundary_edge_case"
    SECURITY_VALIDATION = "security_validation"


class TestPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TestStatus(str, Enum):
    GENERATED = "generated"
    PENDING_REVIEW = "pending_review"


DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 4096
MIN_STORY_LENGTH = 10
MAX_STORY_LENGTH = 8000
RETRY_ATTEMPTS = 3


# ─── Pydantic Models ──────────────────────────────────────────────────────────

class TestStep(BaseModel):
    step_number: int
    action: str
    expected_result: str


class TestCase(BaseModel):
    id: str = Field(default_factory=lambda: f"TC-{uuid.uuid4().hex[:8].upper()}")
    title: str
    category: TestCategory
    priority: TestPriority
    description: str
    preconditions: list[str]
    steps: list[TestStep]
    expected_outcome: str
    tags: list[str] = Field(default_factory=list)
    notes: Optional[str] = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Test case title must not be empty.")
        return v


class TestSuiteMetadata(BaseModel):
    suite_id: str = Field(default_factory=lambda: f"TS-{uuid.uuid4().hex[:8].upper()}")
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    model_used: str
    story_summary: str
    total_test_cases: int
    happy_path_count: int
    boundary_edge_case_count: int
    security_validation_count: int


class TestSuite(BaseModel):
    metadata: TestSuiteMetadata
    user_story: str
    test_cases: list[TestCase]

    def summary(self) -> str:
        lines = [
            f"\n[bold cyan]Test Suite:[/bold cyan] {self.metadata.suite_id}",
            f"[bold]Total Cases:[/bold] {self.metadata.total_test_cases}",
            f"  ✅ Happy Paths:        {self.metadata.happy_path_count}",
            f"  ⚠️  Boundary/Edge:      {self.metadata.boundary_edge_case_count}",
            f"  🔒 Security/Validation:{self.metadata.security_validation_count}",
        ]
        return "\n".join(lines)


# ─── System Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a senior QA Architect with deep expertise in software testing, \
security testing, and edge-case analysis. Your role is to generate \
comprehensive, structured test suites from user stories.

Given a user story, generate a complete test suite as a single valid JSON \
object (no markdown, no explanation, raw JSON only) that strictly matches \
this structure:

{
  "story_summary": "<one-sentence summary of the story>",
  "test_cases": [
    {
      "title": "<concise test case title>",
      "category": "<happy_path | boundary_edge_case | security_validation>",
      "priority": "<critical | high | medium | low>",
      "description": "<what this test verifies>",
      "preconditions": ["<precondition 1>", "..."],
      "steps": [
        {
          "step_number": 1,
          "action": "<what the user/system does>",
          "expected_result": "<what should happen>"
        }
      ],
      "expected_outcome": "<overall expected outcome>",
      "tags": ["<tag1>", "<tag2>"],
      "notes": "<optional additional notes or null>"
    }
  ]
}

Rules you MUST follow:
1. Generate at least 3 happy path cases covering the primary success flow and \
   common variations.
2. Generate at least 4 boundary/edge cases (empty inputs, max length, invalid \
   formats, null values, concurrent access, etc.).
3. Generate at least 4 security/validation cases (SQL injection, XSS, CSRF, \
   auth bypass, privilege escalation, rate limiting, oversized payloads, etc.).
4. Assign realistic priorities. Critical = system-breaking failures. \
   High = major feature failures. Medium = degraded experience. Low = cosmetic.
5. Each test step must be atomic and independently verifiable.
6. Preconditions must describe the exact system state before the test.
7. Tags must be lowercase, hyphen-separated strings (e.g. "auth", "sql-injection").
8. Output ONLY valid JSON. No markdown code fences, no preamble, no commentary.
"""


# ─── Input Validation ────────────────────────────────────────────────────────

def validate_user_story(story: str) -> str:
    """Validate and sanitize the input user story."""
    story = story.strip()

    if len(story) < MIN_STORY_LENGTH:
        raise ValueError(
            f"User story is too short. Minimum {MIN_STORY_LENGTH} characters required; "
            f"got {len(story)}."
        )

    if len(story) > MAX_STORY_LENGTH:
        raise ValueError(
            f"User story exceeds maximum length of {MAX_STORY_LENGTH} characters; "
            f"got {len(story)}. Please shorten or split the story."
        )

    logger.debug("User story validation passed (%d characters).", len(story))
    return story


# ─── LLM Client ───────────────────────────────────────────────────────────────

def build_openai_client() -> OpenAI:
    """Build and return an OpenAI client from environment variables."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY environment variable is not set. "
            "Set it in your shell or in a .env file."
        )
    base_url = os.getenv("OPENAI_BASE_URL")  # Supports Azure / proxies
    client_kwargs: dict = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
        logger.info("Using custom LLM base URL: %s", base_url)
    return OpenAI(**client_kwargs)


@retry(
    retry=retry_if_exception_type((APIConnectionError, RateLimitError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(RETRY_ATTEMPTS),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def call_llm(client: OpenAI, story: str, model: str, temperature: float) -> str:
    """
    Call the LLM API with retry logic for transient errors.
    Returns the raw JSON string from the model.
    """
    logger.info("Calling LLM model [bold]%s[/bold] …", model)
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=DEFAULT_MAX_TOKENS,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Generate a complete test suite for the following user story:\n\n"
                    f"{story}"
                ),
            },
        ],
    )

    finish_reason = response.choices[0].finish_reason
    if finish_reason != "stop":
        logger.warning(
            "Unexpected finish_reason from LLM: '%s'. Output may be truncated.",
            finish_reason,
        )

    raw = response.choices[0].message.content
    if not raw:
        raise ValueError("LLM returned an empty response.")

    logger.debug(
        "LLM response received. Tokens used: prompt=%d, completion=%d, total=%d",
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
        response.usage.total_tokens,
    )
    return raw


# ─── Parsing & Validation ────────────────────────────────────────────────────

def parse_llm_response(raw_json: str, story: str, model: str) -> TestSuite:
    """
    Parse the raw LLM JSON string into a validated TestSuite Pydantic model.
    """
    logger.info("Parsing and validating LLM response …")

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM returned invalid JSON. JSONDecodeError: {exc}\n"
            f"Raw output (first 500 chars): {raw_json[:500]}"
        ) from exc

    # Validate all test cases through Pydantic
    raw_cases = data.get("test_cases", [])
    if not raw_cases:
        raise ValueError("LLM response contains no test cases.")

    test_cases: list[TestCase] = []
    parse_errors: list[str] = []

    for i, tc in enumerate(raw_cases):
        try:
            test_cases.append(TestCase(**tc))
        except Exception as exc:  # noqa: BLE001
            parse_errors.append(f"  Test case #{i + 1} skipped — {exc}")

    if parse_errors:
        logger.warning(
            "Some test cases failed schema validation and were skipped:\n%s",
            "\n".join(parse_errors),
        )

    if not test_cases:
        raise ValueError("No valid test cases could be parsed from the LLM response.")

    # Build metadata
    happy = sum(1 for tc in test_cases if tc.category == TestCategory.HAPPY_PATH)
    boundary = sum(
        1 for tc in test_cases if tc.category == TestCategory.BOUNDARY_EDGE_CASE
    )
    security = sum(
        1 for tc in test_cases if tc.category == TestCategory.SECURITY_VALIDATION
    )

    metadata = TestSuiteMetadata(
        model_used=model,
        story_summary=data.get("story_summary", "N/A"),
        total_test_cases=len(test_cases),
        happy_path_count=happy,
        boundary_edge_case_count=boundary,
        security_validation_count=security,
    )

    return TestSuite(
        metadata=metadata,
        user_story=story,
        test_cases=test_cases,
    )


# ─── Output ───────────────────────────────────────────────────────────────────

def write_output(suite: TestSuite, output_path: Optional[str]) -> None:
    """Write the test suite JSON to a file or stdout."""
    json_str = suite.model_dump_json(indent=2)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(json_str)
        logger.info("Test suite written to [bold green]%s[/bold green]", output_path)
    else:
        # Write raw JSON to stdout so it's pipe-friendly
        sys.stdout.write(json_str + "\n")


# ─── Orchestrator ────────────────────────────────────────────────────────────

def generate_test_suite(
    story: str,
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    output_path: Optional[str] = None,
) -> TestSuite:
    """
    Main orchestration function:
    1. Validate the story
    2. Build LLM client
    3. Call the LLM with retry
    4. Parse and validate response
    5. Write output
    """
    story = validate_user_story(story)

    client = build_openai_client()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task(
            description="[cyan]Generating test suite via LLM…", total=None
        )
        raw_json = call_llm(client, story, model, temperature)

    suite = parse_llm_response(raw_json, story, model)

    console.print(suite.summary())
    write_output(suite, output_path)

    return suite


# ─── CLI ──────────────────────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate structured QA test suites from user stories using an LLM.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_suite_generator.py --story "As a user, I want to log in with email and password."
  python test_suite_generator.py --file story.txt --output suite.json
  python test_suite_generator.py --file story.txt --model gpt-4-turbo --temperature 0.1
  cat story.txt | python test_suite_generator.py --stdin
        """,
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--story", "-s", type=str, help="User story as a plain-text string."
    )
    input_group.add_argument(
        "--file", "-f", type=str, help="Path to a text file containing the user story."
    )
    input_group.add_argument(
        "--stdin", action="store_true", help="Read the user story from stdin."
    )

    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="Path to write the JSON output. Defaults to stdout.",
    )
    parser.add_argument(
        "--model", "-m", type=str, default=DEFAULT_MODEL,
        help=f"OpenAI model to use (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--temperature", "-t", type=float, default=DEFAULT_TEMPERATURE,
        help=f"LLM temperature (0.0–1.0, default: {DEFAULT_TEMPERATURE}).",
    )
    parser.add_argument(
        "--log-level", type=str, default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    return parser


def resolve_story(args: argparse.Namespace) -> str:
    """Resolve the user story from the chosen input source."""
    if args.story:
        return args.story

    if args.stdin:
        logger.info("Reading user story from stdin …")
        return sys.stdin.read()

    if args.file:
        path = args.file
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Story file not found: {path!r}")
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        logger.info("Read user story from file: %s", path)
        return content

    raise ValueError("No input source specified.")  # Should never reach here


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    # Apply log level
    logging.getLogger().setLevel(args.log_level)
    logger.setLevel(args.log_level)

    try:
        story = resolve_story(args)
        generate_test_suite(
            story=story,
            model=args.model,
            temperature=args.temperature,
            output_path=args.output,
        )
    except FileNotFoundError as exc:
        logger.error("File error: %s", exc)
        sys.exit(2)
    except EnvironmentError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(3)
    except ValueError as exc:
        logger.error("Validation error: %s", exc)
        sys.exit(4)
    except APIStatusError as exc:
        logger.error(
            "LLM API error (HTTP %d): %s", exc.status_code, exc.message
        )
        sys.exit(5)
    except APIConnectionError as exc:
        logger.error("LLM connection error: %s", exc)
        sys.exit(6)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()