from pathlib import Path

from pydantic import BaseModel
from crewai.flow import Flow, listen, start

from test_suite_crew.crews.qa_crew.qa_crew import QACrew

DEFAULT_STORY = (
    "As a registered user, I want to reset my password via a secure email link "
    "so that I can regain access to my account if I forget my credentials."
)
MIN_STORY_LENGTH = 10
MAX_STORY_LENGTH = 8000


class TestSuiteState(BaseModel):
    user_story: str = ""
    test_suite_json: str = ""


def _validate_user_story(story: str) -> str:
    story = story.strip()
    if len(story) < MIN_STORY_LENGTH:
        raise ValueError(
            "User story is too short. Minimum "
            f"{MIN_STORY_LENGTH} characters required; got {len(story)}."
        )
    if len(story) > MAX_STORY_LENGTH:
        raise ValueError(
            "User story exceeds maximum length of "
            f"{MAX_STORY_LENGTH} characters; got {len(story)}."
        )
    return story


class TestSuiteFlow(Flow[TestSuiteState]):
    @start()
    def ingest_story(self, crewai_trigger_payload: dict = None):
        print("Ingesting user story")
        if crewai_trigger_payload:
            raw_story = crewai_trigger_payload.get("user_story", DEFAULT_STORY)
            print(f"Using trigger payload: {crewai_trigger_payload}")
        else:
            raw_story = DEFAULT_STORY
        self.state.user_story = _validate_user_story(raw_story)
        print(f"Story ({len(self.state.user_story)} chars) accepted.")

    @listen(ingest_story)
    def generate_suite(self):
        print("Generating test suite via QACrew")
        result = QACrew().crew().kickoff(inputs={"user_story": self.state.user_story})
        self.state.test_suite_json = result.raw
        print("Test suite generated")

    @listen(generate_suite)
    def save_suite(self):
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        path = output_dir / "test_suite.json"
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.state.test_suite_json)
        print(f"Test suite saved to {path}")


def kickoff():
    flow = TestSuiteFlow()
    flow.kickoff()


def plot():
    flow = TestSuiteFlow()
    flow.plot()


def run_with_trigger():
    """Run the flow with a JSON trigger payload (e.g. {"user_story": "..."})."""
    import json
    import sys

    if len(sys.argv) < 2:
        raise Exception(
            "No trigger payload provided. Please provide JSON payload as argument."
        )
    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    try:
        flow = TestSuiteFlow()
        return flow.kickoff(inputs={"crewai_trigger_payload": trigger_payload})
    except Exception as e:
        raise Exception(f"An error occurred while running the flow with trigger: {e}")


if __name__ == "__main__":
    kickoff()
