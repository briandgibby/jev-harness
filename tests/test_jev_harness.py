"""Bounded, offline verification of the Jev Harness contract.

All integration data is generated in temporary directories. Provider tests use
local mocks; no test makes a network request or reads a credential value.
"""

from __future__ import annotations

import copy
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, Mock, patch

import jev_harness as harness


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "jev_harness.py"


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="jev-harness-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.demo = self.root / "demo"
        self.invoke("init", "--directory", self.demo)

    def invoke(self, *arguments, expected=0, remove_env=()):
        environment = os.environ.copy()
        for name in remove_env:
            environment.pop(name, None)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *(str(value) for value in arguments)],
            cwd=self.root,
            env=environment,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        if expected == 0:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def read_json(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def new_json(self, name, value):
        path = self.demo / name
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, allow_nan=False)
        return path

    def new_text(self, name, value):
        path = self.demo / name
        with path.open("x", encoding="utf-8") as handle:
            handle.write(value)
        return path

    def fixture_run(self, *, config=None, input_path=None, expected=0):
        return self.invoke(
            "run", "--config", config or self.demo / "config.json",
            "--input", input_path or self.demo / "input.json",
            "--mode", "fixture", expected=expected,
        )

    def test_bootstrap_creates_complete_first_run_state(self):
        for name in ("config.json", "input.json", "dataset.json"):
            with self.subTest(name=name):
                self.assertTrue((self.demo / name).is_file())
                self.read_json(self.demo / name)

    def test_second_bootstrap_refuses_to_overwrite_any_file(self):
        before = {
            path.relative_to(self.demo): path.read_bytes()
            for path in self.demo.rglob("*")
            if path.is_file()
        }
        self.invoke("init", "--directory", self.demo, expected=1)
        after = {
            path.relative_to(self.demo): path.read_bytes()
            for path in self.demo.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)

    def test_cli_help_documents_all_commands(self):
        result = self.invoke("--help")
        for command in ("init", "run", "replay", "evaluate"):
            self.assertIn(command, result.stdout)

    def test_unknown_configuration_setting_is_rejected(self):
        config = self.read_json(self.demo / "config.json")
        config["unrecognized_setting"] = True
        result = self.fixture_run(
            config=self.new_json("unknown-config.json", config), expected=1,
        )
        self.assertIn("unrecognized_setting", result.stdout + result.stderr)

    def test_missing_schema_version_is_rejected(self):
        config = self.read_json(self.demo / "config.json")
        del config["schema_version"]
        self.fixture_run(
            config=self.new_json("missing-version.json", config), expected=1,
        )

    def test_duplicate_configuration_keys_are_rejected(self):
        config = (self.demo / "config.json").read_text(encoding="utf-8")
        malformed = config.rstrip()[:-1] + ', "schema_version": 1}'
        self.fixture_run(
            config=self.new_text("duplicate-config.json", malformed), expected=1,
        )

    def test_malformed_json_input_is_rejected_without_traceback(self):
        result = self.fixture_run(
            input_path=self.new_text("malformed-input.json", '{"state":'),
            expected=1,
        )
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_nonobject_input_is_rejected(self):
        self.fixture_run(
            input_path=self.new_json("array-input.json", ["record"]), expected=1,
        )

    def test_unknown_input_fields_are_rejected(self):
        value = self.read_json(self.demo / "input.json")
        value["unexpected_input_field"] = "untrusted"
        self.fixture_run(
            input_path=self.new_json("unknown-input.json", value), expected=1,
        )

    def test_duplicate_input_keys_are_rejected(self):
        value = self.read_json(self.demo / "input.json")
        field = next(iter(value))
        malformed = json.dumps(value)[:-1] + ", " + json.dumps(field) + ': null}'
        self.fixture_run(
            input_path=self.new_text("duplicate-input.json", malformed), expected=1,
        )

    def test_fixture_run_and_replay_match_and_identify_synthetic_provenance(self):
        run = json.loads(self.fixture_run().stdout)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["mode"], "fixture")
        self.assertIn("Synthetic", run["notice"])
        self.assertTrue(run["decision"]["recommendation_only"])
        record = Path(run["audit_path"])
        self.assertTrue(record.is_file())
        events = [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([event["event"] for event in events], ["started", "completed"])
        replay = json.loads(self.invoke("replay", "--record", record).stdout)
        self.assertEqual(replay["decision"], run["decision"])
        self.assertEqual(replay["request_hash"], run["request_hash"])
        self.assertEqual(replay["response_hash"], run["response_hash"])
        self.assertFalse(replay["network_called"])
        self.assertEqual(replay["operation"], "historical_replay")

    def test_missing_live_credential_is_nonzero_and_names_environment_setting(self):
        config = self.read_json(self.demo / "config.json")
        name = config["api_key_env"]
        result = self.invoke(
            "run", "--config", self.demo / "config.json",
            "--input", self.demo / "input.json", "--mode", "live",
            expected=1, remove_env=(name,),
        )
        self.assertEqual(result.stdout, "")
        report = json.loads(result.stderr)
        self.assertEqual(report["code"], "missing_credential")
        self.assertIn(name, report["message"])
        self.assertTrue(report["next_action"])
        events = [json.loads(line) for line in Path(report["audit_path"]).read_text(encoding="utf-8").splitlines()]
        self.assertEqual([event["event"] for event in events], ["started", "failed"])

    def test_evaluation_reports_accuracy_coverage_and_confusion(self):
        result = self.invoke(
            "evaluate", "--config", self.demo / "config.json",
            "--dataset", self.demo / "dataset.json", "--mode", "fixture",
        )
        report = json.loads(result.stdout)
        dataset = self.read_json(self.demo / "dataset.json")
        self.assertEqual(report["count"], len(dataset["items"]))
        self.assertEqual(report["accuracy"], 1)
        self.assertEqual(report["accepted_accuracy"], 1)
        self.assertGreater(report["review_count"], 0)
        self.assertAlmostEqual(report["accepted_coverage"], (report["count"] - report["review_count"]) / report["count"])
        self.assertEqual(sum(sum(row.values()) for row in report["confusion"].values()), report["count"])
        self.assertEqual(report["mode"], "fixture")
        self.assertIn("Synthetic", report["notice"])

    def test_corrupted_record_is_rejected_by_cli(self):
        run = json.loads(self.fixture_run().stdout)
        record = Path(run["audit_path"])
        events = [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]
        events[1]["decision"]["status"] = "altered"
        altered = self.new_text("altered-record.jsonl", "\n".join(json.dumps(event) for event in events) + "\n")
        result = self.invoke("replay", "--record", altered, expected=1)
        self.assertEqual(json.loads(result.stderr)["code"], "record_integrity_failed")


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="jev-policy-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        harness.initialize(self.base)
        self.config = harness.load_json(self.base / "config.json")
        self.input = harness.load_json(self.base / "input.json")
        self.dataset = harness.load_json(self.base / "dataset.json")
        self.fixtures = harness.load_json(self.base / self.config["fixture_file"])
        self.response = copy.deepcopy(self.fixtures[self.input["id"]])
        self.request = harness.build_request(self.config, self.input)
        self.labels = list(self.config["question"]["criteria"])
        self.accept_label = next(label for label in self.labels if label not in self.config["policy"]["review_labels"])
        self.review_label = self.config["policy"]["review_labels"][0]
        self.synthetic_key = "synthetic-test-key-not-a-credential"

    def answer(self, response=None):
        return (response or self.response)["answers"][self.config["question"]["id"]]

    def make_response(self, probability=0.97, choice=None, confidence=0.01):
        choice = choice or self.accept_label
        other = next(label for label in self.labels if label != choice)
        response = copy.deepcopy(self.response)
        answer = self.answer(response)
        answer["choice"] = choice
        answer["probabilities"] = {label: 0 for label in self.labels}
        answer["probabilities"].update({choice: probability, other: 1 - probability})
        answer["confidence"] = confidence
        harness.validate_response(response, self.request)
        return response

    def decide(self, response):
        harness.validate_config(self.config)
        harness.validate_response(response, self.request)
        return harness.decide(response, self.config)

    def write_new(self, name, value):
        path = self.base / name
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, allow_nan=False)
        return path

    def write_record(self, name, events):
        path = self.base / name
        with path.open("x", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, allow_nan=False) + "\n")
        return path

    def run_fixture(self):
        return harness.run_one(self.config, self.base, self.input, "fixture")

    def test_probability_and_margin_thresholds_are_inclusive(self):
        self.config["policy"].update(min_probability=0.75, min_margin=0.5)
        result = self.decide(self.make_response(0.75))
        self.assertEqual(result["status"], "accept")
        self.assertEqual(result["reasons"], [])
        self.assertTrue(result["recommendation_only"])

    def test_decimal_margin_boundary_is_not_rejected_by_binary_roundoff(self):
        self.config["policy"].update(min_probability=0.6, min_margin=0.2)
        result = self.decide(self.make_response(0.6))
        self.assertEqual(result["status"], "accept")

    def test_probability_below_threshold_requires_review(self):
        self.config["policy"].update(min_probability=0.75001, min_margin=0)
        result = self.decide(self.make_response(0.75))
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["reasons"], ["below_min_probability"])

    def test_margin_below_threshold_requires_review(self):
        self.config["policy"].update(min_probability=0, min_margin=0.50001)
        result = self.decide(self.make_response(0.75))
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["reasons"], ["below_min_margin"])

    def test_ties_always_require_review_even_with_zero_thresholds(self):
        self.config["policy"].update(min_probability=0, min_margin=0)
        result = self.decide(self.make_response(0.5))
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["reasons"], ["tied_top_probability"])

    def test_review_label_is_reviewed_despite_high_probability(self):
        result = self.decide(self.make_response(0.99, self.review_label))
        self.assertEqual(result["status"], "review")
        self.assertIn("label_requires_review", result["reasons"])

    def test_provider_confidence_is_not_selected_label_probability(self):
        result = self.decide(self.make_response(0.99, confidence=0.001))
        self.assertEqual(result["status"], "accept")
        self.assertEqual(result["probability"], 0.99)
        self.assertEqual(result["confidence"], 0.001)

    def test_config_bounds_types_pins_and_paths_are_enforced(self):
        cases = [
            ("schema_version", True), ("schema_version", 2),
            ("timeout_seconds", 0), ("timeout_seconds", 121), ("timeout_seconds", True),
            ("max_input_bytes", 0), ("max_input_bytes", 1_000_001), ("max_input_bytes", 1.5),
            ("model", "jev-latest"), ("model", "jev-1.13"),
            ("endpoint", "http://api.typesafe.ai/v1/systemone"),
            ("endpoint", "https://example.invalid/v1/systemone"),
            ("endpoint", "https://api.typesafe.ai/v1/systemone?credential=anything"),
            ("endpoint", "https://user:password@api.typesafe.ai/v1/systemone"),
            ("api_key_env", "lowercase"), ("audit_dir", "../outside"),
            ("fixture_file", "..\\outside.json"), ("fixture_file", "C:\\outside.json"),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                config = copy.deepcopy(self.config)
                config[field] = value
                with self.assertRaises(harness.HarnessError) as raised:
                    harness.validate_config(config)
                self.assertIn(field, raised.exception.message)

    def test_huge_integer_setting_is_named_in_validation_error(self):
        config = copy.deepcopy(self.config)
        config["timeout_seconds"] = 10 ** 400
        with self.assertRaises(harness.HarnessError) as raised:
            harness.validate_config(config)
        self.assertIn("timeout_seconds", raised.exception.message)

    def test_policy_rejects_invalid_thresholds_and_review_labels(self):
        cases = [
            ("min_probability", -0.01), ("min_probability", 1.01),
            ("min_margin", True), ("min_margin", float("nan")),
            ("review_labels", ["not-configured"]),
            ("review_labels", [self.review_label, self.review_label]),
            ("review_labels", self.review_label),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                config = copy.deepcopy(self.config)
                config["policy"][field] = value
                with self.assertRaises(harness.HarnessError):
                    harness.validate_config(config)

    def test_input_rejects_unsupported_types_and_empty_identifiers(self):
        for value in (
            None, [], {"id": "", "state": "text"}, {"id": "x", "state": 3},
            {"id": "x", "state": True}, {"id": "x", "state": {"score": float("inf")}},
        ):
            with self.subTest(value=value), self.assertRaises(harness.HarnessError):
                harness.validate_input(value)

    def test_invalid_unicode_in_configuration_is_rejected_before_audit_creation(self):
        self.config["question"]["instructions"] = "\ud800"
        with patch.object(harness, "Audit") as audit, \
             patch.object(harness, "_live_response") as live, \
             self.assertRaises(harness.HarnessError) as raised:
            harness.run_one(self.config, self.base, self.input, "live")
        self.assertEqual(raised.exception.code, "invalid_json")
        audit.assert_not_called()
        live.assert_not_called()
        self.assertFalse((self.base / self.config["audit_dir"]).exists())

    def test_invalid_unicode_in_nested_input_values_and_keys_prevents_side_effects(self):
        for state in ({"nested": ["\ud800"]}, {"\ud800": "value"}):
            with self.subTest(state=repr(state)), \
                 patch.object(harness, "Audit") as audit, \
                 patch.object(harness, "_live_response") as live, \
                 self.assertRaises(harness.HarnessError):
                harness.run_one(self.config, self.base, {"id": "invalid-unicode", "state": state}, "live")
            audit.assert_not_called()
            live.assert_not_called()

    def test_response_rejects_wrong_model_questions_and_usage(self):
        for field, value in (
            ("model", "jev-99.0.0"), ("answers", {}),
            ("usage", {"input_tokens": True, "output_tokens": 0}),
            ("usage", {"input_tokens": -1, "output_tokens": 0}),
            ("usage", {"input_tokens": 0, "output_tokens": 1.5}),
        ):
            with self.subTest(field=field, value=value):
                response = copy.deepcopy(self.response)
                response[field] = value
                with self.assertRaises(harness.HarnessError):
                    harness.validate_response(response, self.request)

    def test_response_rejects_malformed_choices_and_distributions(self):
        valid = self.make_response(0.75)
        for field, value in (
            ("type", "noul"), ("choice", "not-configured"),
            ("probabilities", {self.accept_label: 1}),
            ("probabilities", {label: 0 for label in self.labels}),
            ("probabilities", {label: 1 for label in self.labels}),
            ("confidence", True), ("confidence", 1.1),
        ):
            with self.subTest(field=field, value=value):
                response = copy.deepcopy(valid)
                self.answer(response)[field] = value
                with self.assertRaises(harness.HarnessError):
                    harness.validate_response(response, self.request)
        for probability in (True, -0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(probability=probability):
                response = copy.deepcopy(valid)
                self.answer(response)["probabilities"][self.accept_label] = probability
                with self.assertRaises(harness.HarnessError):
                    harness.validate_response(response, self.request)

    def test_selected_choice_must_have_maximum_probability(self):
        response = self.make_response(0.75)
        self.answer(response)["choice"] = next(label for label in self.labels if label != self.accept_label)
        with self.assertRaises(harness.HarnessError):
            harness.validate_response(response, self.request)

    def test_tolerated_probability_rounding_is_never_renormalized(self):
        response = self.make_response(0.75)
        other = next(label for label in self.labels if label != self.accept_label)
        self.answer(response)["probabilities"][other] = 0.2505
        before = copy.deepcopy(response)
        validated = harness.validate_response(response, self.request)
        self.assertEqual(validated, before)
        self.assertNotEqual(sum(self.answer(validated)["probabilities"].values()), 1)

    def test_canonical_request_hash_is_independent_of_mapping_order(self):
        first = {"state": {"b": 2, "a": 1}, "model": "jev-1.13.0"}
        second = {"model": "jev-1.13.0", "state": {"a": 1, "b": 2}}
        self.assertEqual(harness.canonical_hash(first), harness.canonical_hash(second))
        second["state"]["a"] = 3
        self.assertNotEqual(harness.canonical_hash(first), harness.canonical_hash(second))

    def test_live_adapter_makes_one_explicit_request_without_proxy_or_redirect(self):
        reply = MagicMock()
        reply.__enter__.return_value = reply
        reply.status = 200
        reply.read.return_value = json.dumps(self.response).encode("utf-8")
        opener = Mock()
        opener.open.return_value = reply
        with patch.dict(os.environ, {self.config["api_key_env"]: self.synthetic_key}, clear=True), \
             patch.object(harness.urllib.request, "build_opener", return_value=opener) as build, \
             patch.object(harness, "_fixture_response") as fixture:
            result = harness.run_one(self.config, self.base, self.input, "live")
        opener.open.assert_called_once()
        fixture.assert_not_called()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, self.config["endpoint"])
        self.assertEqual(json.loads(request.data), self.request)
        self.assertEqual(request.get_header("Authorization"), "Bearer " + self.synthetic_key)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], self.config["timeout_seconds"])
        handlers = build.call_args.args
        self.assertTrue(any(isinstance(handler, harness.urllib.request.ProxyHandler) and handler.proxies == {} for handler in handlers))
        redirect = next(handler for handler in handlers if isinstance(handler, harness.urllib.request.HTTPRedirectHandler))
        self.assertIsNone(redirect.redirect_request(request, None, 302, "redirect", {}, "https://example.invalid"))
        self.assertEqual(result["mode"], "live")
        self.assertNotIn(self.synthetic_key, json.dumps(result))
        self.assertNotIn(self.synthetic_key, Path(result["audit_path"]).read_text(encoding="utf-8"))

    def test_http_failures_do_not_retry_redirect_fallback_or_expose_body(self):
        for status in (302, 401, 429, 503):
            with self.subTest(status=status):
                failure = urllib.error.HTTPError(
                    self.config["endpoint"], status, self.synthetic_key, {},
                    io.BytesIO(self.synthetic_key.encode("utf-8")),
                )
                opener = Mock()
                opener.open.side_effect = failure
                with patch.dict(os.environ, {self.config["api_key_env"]: self.synthetic_key}, clear=True), \
                     patch.object(harness.urllib.request, "build_opener", return_value=opener), \
                     patch.object(harness, "_fixture_response") as fixture, \
                     self.assertRaises(harness.HarnessError) as raised:
                    harness.run_one(self.config, self.base, self.input, "live")
                opener.open.assert_called_once()
                fixture.assert_not_called()
                self.assertEqual(raised.exception.code, "http_error")
                self.assertIn(str(status), raised.exception.message)
                self.assertNotIn(self.synthetic_key, json.dumps(raised.exception.report()))
                audit_text = Path(raised.exception.audit_path).read_text(encoding="utf-8")
                self.assertNotIn(self.synthetic_key, audit_text)
                self.assertEqual([json.loads(line)["event"] for line in audit_text.splitlines()], ["started", "failed"])

    def test_transport_failure_is_single_attempt_and_safe(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.URLError(self.synthetic_key)
        with patch.dict(os.environ, {self.config["api_key_env"]: self.synthetic_key}, clear=True), \
             patch.object(harness.urllib.request, "build_opener", return_value=opener), \
             patch.object(harness, "_fixture_response") as fixture, \
             self.assertRaises(harness.HarnessError) as raised:
            harness.run_one(self.config, self.base, self.input, "live")
        opener.open.assert_called_once()
        fixture.assert_not_called()
        self.assertEqual(raised.exception.code, "transport_error")
        self.assertNotIn(self.synthetic_key, json.dumps(raised.exception.report()))

    def test_audit_creation_failure_prevents_any_provider_call(self):
        blocking_path = self.base / "blocked-audit"
        with blocking_path.open("x", encoding="utf-8") as handle:
            handle.write("Temporary test fixture blocking directory creation.")
        self.config["audit_dir"] = blocking_path.name
        with patch.object(harness, "_live_response") as live, \
             patch.object(harness, "_fixture_response") as fixture, \
             self.assertRaises(harness.HarnessError) as raised:
            harness.run_one(self.config, self.base, self.input, "live")
        self.assertEqual(raised.exception.code, "audit_failed")
        live.assert_not_called()
        fixture.assert_not_called()

    def test_first_audit_flush_failure_prevents_provider_call(self):
        with patch.object(harness.os, "fsync", side_effect=OSError("synthetic disk failure")), \
             patch.object(harness, "_live_response") as live, \
             self.assertRaises(harness.HarnessError) as raised:
            harness.run_one(self.config, self.base, self.input, "live")
        self.assertEqual(raised.exception.code, "audit_failed")
        live.assert_not_called()

    def test_replay_is_offline_and_uses_the_saved_policy(self):
        result = self.run_fixture()
        self.config["policy"]["review_labels"] = self.labels
        with patch.object(harness, "_live_response", side_effect=AssertionError("network forbidden")), \
             patch.object(harness, "_fixture_response", side_effect=AssertionError("fixture forbidden")):
            replay = harness.replay(result["audit_path"])
        self.assertEqual(replay["decision"], result["decision"])
        self.assertFalse(replay["network_called"])

    def test_replay_rejects_corrupted_response_config_policy_and_decision(self):
        result = self.run_fixture()
        original = [json.loads(line) for line in Path(result["audit_path"]).read_text(encoding="utf-8").splitlines()]
        for field in ("response", "config_snapshot", "policy", "decision"):
            with self.subTest(field=field):
                events = copy.deepcopy(original)
                events[1][field]["unexpected_corruption"] = True
                path = self.write_record("corrupt-" + field + ".jsonl", events)
                with self.assertRaises(harness.HarnessError) as raised:
                    harness.replay(path)
                self.assertEqual(raised.exception.code, "record_integrity_failed")

    def test_replay_rejects_rehashed_decision_that_policy_does_not_produce(self):
        result = self.run_fixture()
        events = [json.loads(line) for line in Path(result["audit_path"]).read_text(encoding="utf-8").splitlines()]
        events[1]["decision"]["status"] = "altered"
        events[1]["decision_hash"] = harness.canonical_hash(events[1]["decision"])
        path = self.write_record("rehashed-wrong-decision.jsonl", events)
        with self.assertRaises(harness.HarnessError) as raised:
            harness.replay(path)
        self.assertEqual(raised.exception.code, "record_integrity_failed")

    def test_replay_rejects_truncation_and_extra_events(self):
        result = self.run_fixture()
        events = [json.loads(line) for line in Path(result["audit_path"]).read_text(encoding="utf-8").splitlines()]
        for index, invalid in enumerate((events[:1], events + events[:1])):
            with self.subTest(index=index), self.assertRaises(harness.HarnessError):
                harness.replay(self.write_record(f"event-count-{index}.jsonl", invalid))

    def test_dataset_is_fully_validated_before_any_provider_or_audit_call(self):
        dataset = copy.deepcopy(self.dataset)
        dataset["items"][-1]["expected_label"] = "not-configured"
        with patch.object(harness, "run_one") as run, self.assertRaises(harness.HarnessError):
            harness.evaluate(self.config, self.base, dataset, "fixture")
        run.assert_not_called()
        self.assertFalse((self.base / self.config["audit_dir"]).exists())

    def test_dataset_rejects_duplicates_empty_and_more_than_twenty_rows(self):
        row = self.dataset["items"][0]
        for dataset in ({"items": []}, {"items": [row, row]}, {"items": [row] * 21}):
            with self.subTest(count=len(dataset["items"])), \
                 patch.object(harness, "run_one") as run, \
                 self.assertRaises(harness.HarnessError):
                harness.evaluate(self.config, self.base, dataset, "fixture")
            run.assert_not_called()

    def test_all_review_evaluation_has_zero_coverage_and_undefined_accepted_accuracy(self):
        self.config["policy"]["review_labels"] = self.labels
        report = harness.evaluate(self.config, self.base, self.dataset, "fixture")
        self.assertEqual(report["accepted_coverage"], 0)
        self.assertIsNone(report["accepted_accuracy"])
        self.assertEqual(report["review_count"], report["count"])

    def test_second_row_failure_reports_partial_progress_without_complete_metrics(self):
        fixtures = copy.deepcopy(self.fixtures)
        missing_id = self.dataset["items"][1]["id"]
        del fixtures[missing_id]
        path = self.write_new("partial-fixtures.json", fixtures)
        self.config["fixture_file"] = path.name
        with self.assertRaises(harness.HarnessError) as raised:
            harness.evaluate(self.config, self.base, self.dataset, "fixture")
        report = raised.exception.report()
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["completed_count"], 1)
        self.assertNotIn("accuracy", report)
        self.assertTrue(report["completed_audit_paths"])
        self.assertEqual(len(report["completed_audit_paths"]), 1)
        self.assertTrue(Path(report["completed_audit_paths"][0]).is_file())


if __name__ == "__main__":
    unittest.main()
