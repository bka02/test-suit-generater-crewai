"""Unit tests for test_suite_generator.py (stdlib unittest, no network)."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest

# Load the top-level script as a module regardless of the test runner used.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "test_suite_generator", os.path.join(ROOT, "test_suite_generator.py")
)
tsg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tsg)


def make_case(**overrides):
    case = {
        "title": "Valid login",
        "category": "happy_path",
        "priority": "critical",
        "description": "user logs in",
        "preconditions": ["account exists"],
        "steps": [{"step_number": 1, "action": "enter creds", "expected_result": "ok"}],
        "expected_outcome": "logged in",
        "tags": ["auth"],
    }
    case.update(overrides)
    return case


class TestValidateUserStory(unittest.TestCase):
    def test_valid_story_is_stripped(self):
        self.assertEqual(tsg.validate_user_story("  hello world story  "), "hello world story")

    def test_too_short_raises(self):
        with self.assertRaises(ValueError):
            tsg.validate_user_story("short")

    def test_too_long_raises(self):
        with self.assertRaises(ValueError):
            tsg.validate_user_story("x" * (tsg.MAX_STORY_LENGTH + 1))


class TestModels(unittest.TestCase):
    def test_testcase_default_id_prefix(self):
        tc = tsg.TestCase(**make_case())
        self.assertTrue(tc.id.startswith("TC-"))

    def test_empty_title_rejected(self):
        with self.assertRaises(Exception):
            tsg.TestCase(**make_case(title="   "))

    def test_teststep_fields(self):
        step = tsg.TestStep(step_number=1, action="a", expected_result="b")
        self.assertEqual(step.step_number, 1)


class TestParseLLMResponse(unittest.TestCase):
    def _payload(self, cases):
        return json.dumps({"story_summary": "s", "test_cases": cases})

    def test_counts_by_category(self):
        cases = [
            make_case(category="happy_path"),
            make_case(category="boundary_edge_case"),
            make_case(category="security_validation"),
        ]
        suite = tsg.parse_llm_response(self._payload(cases), "story", "gpt-x")
        self.assertEqual(suite.metadata.total_test_cases, 3)
        self.assertEqual(suite.metadata.happy_path_count, 1)
        self.assertEqual(suite.metadata.boundary_edge_case_count, 1)
        self.assertEqual(suite.metadata.security_validation_count, 1)

    def test_invalid_case_is_skipped(self):
        cases = [make_case(), make_case(category="not_real")]
        suite = tsg.parse_llm_response(self._payload(cases), "story", "gpt-x")
        self.assertEqual(suite.metadata.total_test_cases, 1)

    def test_no_test_cases_raises(self):
        with self.assertRaises(ValueError):
            tsg.parse_llm_response(self._payload([]), "story", "gpt-x")

    def test_invalid_json_raises(self):
        with self.assertRaises(ValueError):
            tsg.parse_llm_response("{not json", "story", "gpt-x")

    def test_all_invalid_raises(self):
        cases = [make_case(category="bad1"), make_case(category="bad2")]
        with self.assertRaises(ValueError):
            tsg.parse_llm_response(self._payload(cases), "story", "gpt-x")


class TestArgParser(unittest.TestCase):
    def test_story_and_defaults(self):
        args = tsg.build_arg_parser().parse_args(["--story", "hello world"])
        self.assertEqual(args.story, "hello world")
        self.assertEqual(args.model, tsg.DEFAULT_MODEL)
        self.assertEqual(args.temperature, tsg.DEFAULT_TEMPERATURE)

    def test_requires_input_source(self):
        with self.assertRaises(SystemExit):
            tsg.build_arg_parser().parse_args([])

    def test_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            tsg.build_arg_parser().parse_args(["--story", "x", "--stdin"])


class TestResolveStory(unittest.TestCase):
    def test_from_story(self):
        args = tsg.build_arg_parser().parse_args(["--story", "my story text"])
        self.assertEqual(tsg.resolve_story(args), "my story text")

    def test_from_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("story from file")
            path = fh.name
        try:
            args = tsg.build_arg_parser().parse_args(["--file", path])
            self.assertEqual(tsg.resolve_story(args), "story from file")
        finally:
            os.unlink(path)

    def test_missing_file_raises(self):
        args = tsg.build_arg_parser().parse_args(["--file", "/no/such/file.txt"])
        with self.assertRaises(FileNotFoundError):
            tsg.resolve_story(args)


class TestWriteOutputAndClient(unittest.TestCase):
    def test_write_output_to_file(self):
        payload = json.dumps({"story_summary": "s", "test_cases": [make_case()]})
        suite = tsg.parse_llm_response(payload, "story", "gpt-x")
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "suite.json")
            tsg.write_output(suite, out)
            with open(out, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["metadata"]["total_test_cases"], 1)

    def test_build_client_requires_key(self):
        saved = {k: os.environ.pop(k, None) for k in ("OPENAI_API_KEY", "OPENAI_BASE_URL")}
        try:
            with self.assertRaises(EnvironmentError):
                tsg.build_openai_client()
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main(verbosity=2)
