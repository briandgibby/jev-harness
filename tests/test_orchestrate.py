"""Behavior and boundary tests for one-task orchestration."""

from __future__ import annotations

from contextlib import redirect_stderr
import gc
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import warnings

import local_model
import orchestrate as orch


ENDPOINT = "http://127.0.0.1:8000/v1/chat/completions"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def fake_verifier(exit_code=0, verdict=True):
    def verify(checkout, evaluator, image, timeout, max_bytes, run_dir):
        assert evaluator.is_file()
        assert image == orch.VERIFIER_IMAGE
        assert (checkout / "solution.py").is_file()
        stdout = run_dir / "verifier.stdout"
        stderr = run_dir / "verifier.stderr"
        stdout.write_text((json.dumps({"schema_version": 1, "tests_run": 3,
                                       "failures": 0, "errors": 0}) + "\n")
                          if verdict else "", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return {"command": ["synthetic-test-verifier"], "exit_code": exit_code,
                "stdout_path": str(stdout), "stderr_path": str(stderr),
                "stdout_sha256": orch.file_hash(stdout), "stderr_sha256": orch.file_hash(stderr),
                "elapsed_ms": 0}
    return verify


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="jev-orchestrate-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.case = self.root / "case"
        orch.initialize(self.case, ENDPOINT)

    def run_fixture(self, *, route_source="baseline"):
        with patch.object(orch, "_verify_docker", side_effect=fake_verifier()):
            return orch.run(self.case, "fixture", "fixture", route_source,
                            None, False, False)

    def set_jev_choice(self, choice: str) -> None:
        path = self.case / "route-fixtures.json"
        fixtures = read_json(path)
        answer = fixtures["fixture-add"]["answers"]["coding_route"]
        answer["choice"] = choice
        answer["probabilities"] = {label: (0.92 if label == choice else 0.04)
                                   for label in ("fast", "strong", "unclear")}
        save_json(path, fixtures)

    def assert_run_failure(self, code: str, **options) -> orch.OrchestrationError:
        with patch.object(orch, "_verify_docker", side_effect=fake_verifier()):
            with self.assertRaises(orch.OrchestrationError) as context:
                orch.run(self.case, "fixture", "fixture", options.get("route_source", "baseline"),
                         None, False, False)
        self.assertEqual(context.exception.code, code)
        self.assertIsNotNone(context.exception.run_dir)
        return context.exception

    def test_init_creates_complete_fixture_from_absent_directory(self):
        self.assertTrue((self.case / "fixture-repo" / "solution.py").is_file())
        self.assertTrue((self.case / "evaluator" / "test_solution.py").is_file())
        _, config, task, profile, repo, evaluator = orch.load_state(self.case)
        self.assertEqual(config["schema_version"], 1)
        self.assertEqual(profile["model"], "jev-1.13.0")
        self.assertEqual(orch._git(repo, "rev-parse", "HEAD"), task["base_commit"])
        self.assertEqual(orch.file_hash(evaluator), task["evaluator_sha256"])
        self.assertFalse((self.case / "runs").exists())

    def test_complex_fixture_generates_a_distinct_multicase_task(self):
        directory = self.root / "complex"
        orch.initialize(directory, ENDPOINT, fixture_complexity="complex")
        task = read_json(directory / "task.json")
        self.assertEqual(task["complexity"], "complex")
        self.assertEqual(task["id"], "fixture-merge-intervals")
        self.assertIn("merge_intervals", task["objective"])
        self.assertIn("merge_intervals", (directory / "fixture-repo" / "solution.py").read_text())
        evaluator = (directory / "evaluator" / "test_solution.py").read_text()
        self.assertIn("test_touching", evaluator)
        self.assertIn("test_unsorted", evaluator)
        route_fixture = read_json(directory / "route-fixtures.json")
        self.assertEqual(route_fixture[task["id"]]["answers"]["coding_route"]["choice"],
                         "strong")

    def test_init_records_separate_fast_and_strong_endpoints(self):
        directory = self.root / "two-endpoints"
        strong_endpoint = "http://127.0.0.1:8001/v1/chat/completions"
        orch.initialize(directory, ENDPOINT, strong_endpoint, "simple")
        models = read_json(directory / "orchestration.json")["models"]
        self.assertEqual(models["fast"]["endpoint"], ENDPOINT)
        self.assertEqual(models["strong"]["endpoint"], strong_endpoint)

    def test_init_uses_canonical_model_pin_registry(self):
        pins = read_json(Path(orch.__file__).with_name("model-pins.json"))
        pins["models"]["fast"]["id"] = "alternate-fast-model"
        pins["models"]["fast"]["provider_model"] = "alternate-fast-model"
        with patch.object(orch, "load_model_pins", return_value=pins, create=True):
            orch.initialize(self.root / "pins", ENDPOINT)
        configured = read_json(self.root / "pins" / "orchestration.json")
        self.assertEqual(configured["models"]["fast"]["id"], "alternate-fast-model")

    def test_init_base_commit_is_independent_of_ambient_git_dates(self):
        with patch.dict(orch.os.environ, {"GIT_AUTHOR_DATE": "2001-01-01T00:00:00+0000",
                                       "GIT_COMMITTER_DATE": "2001-01-01T00:00:00+0000"}):
            first = orch.initialize(self.root / "first", ENDPOINT)["base_commit"]
        with patch.dict(orch.os.environ, {"GIT_AUTHOR_DATE": "2002-01-01T00:00:00+0000",
                                       "GIT_COMMITTER_DATE": "2002-01-01T00:00:00+0000"}):
            second = orch.initialize(self.root / "second", ENDPOINT)["base_commit"]
        self.assertEqual(first, second)

    def test_init_accepts_empty_directory_and_refuses_nonempty(self):
        empty = self.root / "empty"
        empty.mkdir()
        self.assertEqual(orch.initialize(empty, ENDPOINT)["status"], "completed")
        occupied = self.root / "occupied"
        occupied.mkdir()
        sentinel = occupied / "keep.txt"
        sentinel.write_bytes(b"keep existing content")
        with self.assertRaises(orch.OrchestrationError) as context:
            orch.initialize(occupied, ENDPOINT)
        self.assertEqual(context.exception.code, "init_target_not_empty")
        self.assertEqual(sentinel.read_bytes(), b"keep existing content")
        self.assertEqual([p.name for p in occupied.iterdir()], ["keep.txt"])

    def test_dry_run_reports_scope_without_state_or_provider_calls(self):
        with (patch.object(orch.jev, "run_one", side_effect=AssertionError("Jev called")),
              patch.object(orch.local_model, "chat_completion", side_effect=AssertionError("model called")),
              patch.object(orch, "_verify_docker", side_effect=AssertionError("verifier called"))):
            result = orch.dry_run(self.case, "live", "live", "baseline")
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["effects"]["maximum_calls"],
                         {"jev": 1, "coding": 1, "verifier": 1})
        self.assertEqual(result["effects"]["allowed_files"], ["solution.py"])
        self.assertFalse((self.case / "runs").exists())
        self.assertFalse((self.case / "jev-audit").exists())

    def test_baseline_and_accepted_jev_can_select_different_eligible_models(self):
        baseline = self.run_fixture()
        self.assertEqual(baseline["route"], "fast")
        self.set_jev_choice("strong")
        jev_result = self.run_fixture(route_source="jev")
        self.assertEqual(jev_result["route"], "strong")
        self.assertTrue(jev_result["jev_audit_path"])
        self.assertEqual(orch.inspect(Path(jev_result["run_dir"]))["status"], "completed")

    def test_rules_baseline_can_run_and_replay_without_jev(self):
        with (patch.object(orch.jev, "run_one", side_effect=AssertionError("Jev called")),
              patch.object(orch, "_verify_docker", side_effect=fake_verifier())):
            scope = orch.dry_run(self.case, "fixture", "off", "baseline")
            self.assertEqual(scope["effects"]["maximum_calls"]["jev"], 0)
            result = orch.run(self.case, "fixture", "off", "baseline", None, False, False)
        self.assertEqual(result["route"], "fast")
        self.assertIsNone(result["jev_audit_path"])
        self.assertFalse((self.case / "jev-audit").exists())
        replayed = orch.replay(Path(result["run_dir"]))
        self.assertEqual(replayed["route"], "fast")
        self.assertIsNone(replayed["jev_audit_path"])

    def test_unclear_jev_result_requires_review_and_never_reaches_verifier(self):
        self.set_jev_choice("unclear")
        with (patch.object(orch, "_verify_docker", side_effect=AssertionError("verifier called")),
              patch.object(orch.local_model, "chat_completion", side_effect=AssertionError("coding model called"))):
            with self.assertRaises(orch.OrchestrationError) as context:
                orch.run(self.case, "fixture", "fixture", "jev", None, False, False)
        self.assertEqual(context.exception.code, "review_required")
        run_dir = Path(context.exception.run_dir)
        self.assertEqual(orch.inspect(run_dir)["status"], "review_required")
        self.assertNotIn("model_completed", [event["event"] for event in orch._events(run_dir)])
        self.assertFalse((run_dir / "checkout").exists())

    def test_accepted_but_ineligible_jev_route_requires_review(self):
        self.set_jev_choice("strong")
        config_path = self.case / "orchestration.json"
        config = read_json(config_path)
        config["models"]["strong"]["data_classes"] = ["local"]
        save_json(config_path, config)
        error = self.assert_run_failure("review_required", route_source="jev")
        run_dir = Path(error.run_dir)
        self.assertEqual(orch.inspect(run_dir)["status"], "review_required")
        self.assertNotIn("model_completed", [event["event"] for event in orch._events(run_dir)])

    def test_evaluator_cannot_be_the_writable_source_file(self):
        task_path = self.case / "task.json"
        task = read_json(task_path)
        task["evaluator_file"] = "fixture-repo/solution.py"
        task["evaluator_sha256"] = orch.file_hash(self.case / "fixture-repo" / "solution.py")
        save_json(task_path, task)
        with self.assertRaises(orch.OrchestrationError) as context:
            orch.dry_run(self.case, "fixture", "fixture", "baseline")
        self.assertEqual(context.exception.code, "invalid_field")
        self.assertIn("evaluator_file", context.exception.message)
        self.assertFalse((self.case / "runs").exists())

    def test_unhashable_model_data_class_gets_named_error(self):
        config_path = self.case / "orchestration.json"
        config = read_json(config_path)
        config["models"]["fast"]["data_classes"] = [["public"]]
        save_json(config_path, config)
        with self.assertRaises(orch.OrchestrationError) as context:
            orch.dry_run(self.case, "fixture", "fixture", "baseline")
        self.assertEqual(context.exception.code, "invalid_field")
        self.assertIn("models.fast.data_classes", context.exception.message)

    def test_unhashable_allowed_file_gets_named_error(self):
        task_path = self.case / "task.json"
        task = read_json(task_path)
        task["allowed_files"] = [["solution.py"]]
        save_json(task_path, task)
        with self.assertRaises(orch.OrchestrationError) as context:
            orch.dry_run(self.case, "fixture", "fixture", "baseline")
        self.assertEqual(context.exception.code, "invalid_field")
        self.assertIn("task.allowed_files", context.exception.message)

    def test_model_patch_cannot_write_undeclared_path(self):
        fixtures_path = self.case / "coding-fixtures.json"
        fixtures = read_json(fixtures_path)
        fixtures["fast"]["files"][0]["path"] = "../escape.py"
        save_json(fixtures_path, fixtures)
        original = (self.case / "fixture-repo" / "solution.py").read_bytes()
        error = self.assert_run_failure("invalid_patch")
        run_dir = Path(error.run_dir)
        self.assertEqual(orch._events(run_dir)[-1]["error"]["run_dir"], str(run_dir))
        self.assertFalse((self.case / "escape.py").exists())
        self.assertFalse((run_dir / "escape.py").exists())
        self.assertFalse((run_dir / "patch.json").exists())
        self.assertEqual((self.case / "fixture-repo" / "solution.py").read_bytes(), original)
        self.assertEqual((run_dir / "checkout" / "solution.py").read_bytes(), original)

    def test_materialization_rejects_traversal_and_symlink_archives(self):
        for name, entry_type in (("../escape.txt", tarfile.REGTYPE),
                                 ("link", tarfile.SYMTYPE)):
            with self.subTest(name=name, entry_type=entry_type):
                data = io.BytesIO()
                with tarfile.open(fileobj=data, mode="w") as bundle:
                    info = tarfile.TarInfo(name)
                    info.type = entry_type
                    info.size = 1 if entry_type == tarfile.REGTYPE else 0
                    info.linkname = "../escape.txt" if entry_type == tarfile.SYMTYPE else ""
                    bundle.addfile(info, io.BytesIO(b"x") if info.size else None)
                target = self.root / f"checkout-{entry_type!r}-{len(name)}"
                with self.assertRaises(orch.OrchestrationError) as context:
                    orch._materialize(data.getvalue(), target, 4)
                self.assertEqual(context.exception.code, "invalid_archive")
                self.assertFalse((self.root / "escape.txt").exists())

    def test_materialization_honors_file_limit_and_does_not_replace_existing(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w") as bundle:
            for name in ("one.txt", "two.txt"):
                info = tarfile.TarInfo(name)
                info.size = 1
                bundle.addfile(info, io.BytesIO(b"x"))
        with self.assertRaises(orch.OrchestrationError) as context:
            orch._materialize(data.getvalue(), self.root / "small-checkout", 1)
        self.assertEqual(context.exception.code, "checkout_too_large")
        existing = self.root / "existing-checkout"
        existing.mkdir()
        sentinel = existing / "keep.txt"
        sentinel.write_text("original", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            orch._materialize(data.getvalue(), existing, 4)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "original")

    def test_archiving_base_closes_its_subprocess_pipe(self):
        task = read_json(self.case / "task.json")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            archive = orch._archive_bytes(self.case / "fixture-repo", task["base_commit"],
                                          2_000_000)
            gc.collect()
        self.assertTrue(archive)
        leaked = [str(warning.message) for warning in caught
                  if issubclass(warning.category, ResourceWarning)
                  and "unclosed file" in str(warning.message)]
        self.assertEqual(leaked, [])

    def test_evaluator_tamper_stops_before_creating_a_run(self):
        (self.case / "evaluator" / "test_solution.py").write_text("pass\n", encoding="utf-8")
        with self.assertRaises(orch.OrchestrationError) as context:
            orch.dry_run(self.case, "fixture", "fixture", "baseline")
        self.assertEqual(context.exception.code, "task_integrity_failed")
        self.assertFalse((self.case / "runs").exists())

    def test_task_base_or_source_tamper_stops_before_creating_a_run(self):
        task_path = self.case / "task.json"
        task = read_json(task_path)
        task["base_commit"] = "0" * 40
        save_json(task_path, task)
        with self.assertRaises(orch.OrchestrationError) as context:
            orch.dry_run(self.case, "fixture", "fixture", "baseline")
        self.assertEqual(context.exception.code, "base_changed")
        self.assertFalse((self.case / "runs").exists())

    def test_failed_verifier_records_failure_without_completion_claim(self):
        with patch.object(orch, "_verify_docker", side_effect=fake_verifier(exit_code=1)):
            with self.assertRaises(orch.OrchestrationError) as context:
                orch.run(self.case, "fixture", "fixture", "baseline", None, False, False)
        self.assertEqual(context.exception.code, "checks_failed")
        run_dir = Path(context.exception.run_dir)
        events = orch._events(run_dir)
        self.assertEqual(events[-1]["event"], "failed")
        self.assertNotIn("completed", [event["event"] for event in events])
        self.assertEqual(read_json(run_dir / "verification.json")["exit_code"], 1)
        self.assertEqual(orch.inspect(run_dir)["status"], "failed")

    def test_zero_exit_without_trusted_test_verdict_is_not_green(self):
        with patch.object(orch, "_verify_docker", side_effect=fake_verifier(verdict=False)):
            with self.assertRaises(orch.OrchestrationError) as context:
                orch.run(self.case, "fixture", "off", "baseline", None, False, False)
        self.assertEqual(context.exception.code, "checks_incomplete")
        run_dir = Path(context.exception.run_dir)
        self.assertNotIn("completed", [event["event"] for event in orch._events(run_dir)])

    def test_replay_recomputes_route_and_rejects_snapshot_tamper(self):
        result = self.run_fixture()
        run_dir = Path(result["run_dir"])
        replay = orch.replay(run_dir)
        self.assertEqual(replay["route"], "fast")
        self.assertIs(replay["jev_network_called"], False)
        config_path = run_dir / "config.snapshot.json"
        config = read_json(config_path)
        config["baseline"]["simple"] = "strong"
        save_json(config_path, config)
        with self.assertRaises(orch.OrchestrationError) as context:
            orch.replay(run_dir)
        self.assertEqual(context.exception.code, "record_integrity_failed")

    def test_replay_rejects_changed_recorded_route(self):
        result = self.run_fixture()
        run_dir = Path(result["run_dir"])
        event_path = run_dir / "events.jsonl"
        events = orch._events(run_dir)
        for event in events:
            if event["event"] == "routed":
                event["selected_route"] = "strong"
        event_path.write_bytes(b"".join(orch.canonical_bytes(event) + b"\n" for event in events))
        with self.assertRaises(orch.OrchestrationError) as context:
            orch.replay(run_dir)
        self.assertEqual(context.exception.code, "record_integrity_failed")

    def test_replay_rejects_changed_jev_response_hash(self):
        result = self.run_fixture()
        run_dir = Path(result["run_dir"])
        events = orch._events(run_dir)
        for event in events:
            if event["event"] == "routed":
                event["jev_response_hash"] = "0" * 64
        (run_dir / "events.jsonl").write_bytes(
            b"".join(orch.canonical_bytes(event) + b"\n" for event in events))
        with self.assertRaises(orch.OrchestrationError) as context:
            orch.replay(run_dir)
        self.assertEqual(context.exception.code, "record_integrity_failed")

    def test_replay_requires_model_patch_and_evaluator_evidence(self):
        for missing in ("model-output.json", "patch.json", "trusted-evaluator/test_solution.py"):
            with self.subTest(missing=missing):
                result = self.run_fixture()
                run_dir = Path(result["run_dir"])
                evidence = run_dir / missing
                self.assertTrue(evidence.is_file())
                evidence.unlink()
                with self.assertRaises(orch.OrchestrationError) as context:
                    orch.replay(run_dir)
                self.assertEqual(context.exception.code, "record_integrity_failed")

    def test_replay_rejects_forged_completion_after_failed_verifier(self):
        with patch.object(orch, "_verify_docker", side_effect=fake_verifier(exit_code=1)):
            with self.assertRaises(orch.OrchestrationError) as context:
                orch.run(self.case, "fixture", "fixture", "baseline", None, False, False)
        run_dir = Path(context.exception.run_dir)
        self.assertEqual(read_json(run_dir / "verification.json")["exit_code"], 1)
        events = orch._events(run_dir)
        events[-1]["event"] = "completed"
        events[-1]["verified_completion"] = True
        (run_dir / "events.jsonl").write_bytes(
            b"".join(orch.canonical_bytes(event) + b"\n" for event in events))
        with self.assertRaises(orch.OrchestrationError) as inspect_error:
            orch.inspect(run_dir)
        self.assertEqual(inspect_error.exception.code, "record_integrity_failed")
        with self.assertRaises(orch.OrchestrationError) as replay_error:
            orch.replay(run_dir)
        self.assertEqual(replay_error.exception.code, "record_integrity_failed")

    def test_local_model_failure_is_recorded_and_does_not_fall_back(self):
        safe = local_model.LocalModelError("connection_failed", "Local server unavailable.",
                                           "Start the local server.")
        with (patch.object(orch.sys, "stdin", SimpleNamespace(isatty=lambda: True)),
              patch("builtins.input", return_value="yes"),
              patch.object(orch.local_model, "chat_completion", side_effect=safe) as model,
              patch.object(orch, "_verify_docker", side_effect=AssertionError("verifier called")),
              redirect_stderr(io.StringIO())):
            with self.assertRaises(orch.OrchestrationError) as context:
                orch.run(self.case, "live", "fixture", "baseline", None, True, False)
        self.assertEqual(context.exception.code, "connection_failed")
        self.assertEqual(model.call_count, 1)
        run_dir = Path(context.exception.run_dir)
        events = orch._events(run_dir)
        self.assertEqual(events[-1]["event"], "failed")
        self.assertIn("restore_proven", [event["event"] for event in events])
        self.assertNotIn("completed", [event["event"] for event in events])
        self.assertFalse((run_dir / "model-output.json").exists())

    def test_unexpected_write_failure_keeps_run_path_and_terminal_record(self):
        with patch.object(orch, "_apply_patch", side_effect=OSError("disk error")):
            with self.assertRaises(orch.OrchestrationError) as context:
                orch.run(self.case, "fixture", "off", "baseline", None, False, False)
        self.assertEqual(context.exception.code, "internal_error")
        run_dir = Path(context.exception.run_dir)
        self.assertEqual(orch._events(run_dir)[-1]["event"], "failed")
        self.assertEqual(orch._events(run_dir)[-1]["error"]["run_dir"], str(run_dir))

    def test_live_coding_requests_schema_for_declared_file_edits(self):
        response = {"model": "qwen25-coder-7b-int4",
                    "content": '{"files":[{"path":"solution.py","content":"def add(a, b):\\n    return a + b\\n"}]}',
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}
        with (patch.object(orch.sys, "stdin", SimpleNamespace(isatty=lambda: True)),
              patch("builtins.input", return_value="yes"),
              patch.object(orch.local_model, "chat_completion", return_value=response) as model,
              patch.object(orch, "_verify_docker", side_effect=fake_verifier()),
              redirect_stderr(io.StringIO())):
            orch.run(self.case, "live", "fixture", "baseline", None, True, False)
        output_format = model.call_args.kwargs["response_format"]
        self.assertEqual(output_format["type"], "json_schema")
        schema = output_format["json_schema"]["schema"]
        self.assertEqual(schema["properties"]["files"]["items"]["properties"]["path"]["enum"],
                         ["solution.py"])
        self.assertIs(schema["additionalProperties"], False)


class DockerDemoIntegrationTest(unittest.TestCase):
    def test_verifier_output_file_never_exceeds_declared_cap(self):
        with tempfile.TemporaryDirectory(prefix="jev-output-cap-test-") as temporary:
            root = Path(temporary)
            checkout = root / "checkout"
            checkout.mkdir()
            (checkout / "solution.py").write_text("pass\n", encoding="utf-8")
            evaluator = root / "evaluator" / "test_solution.py"
            evaluator.parent.mkdir()
            evaluator.write_text("import sys\nsys.stdout.write('x' * 1000000)\n",
                                 encoding="utf-8")
            run_dir = root / "run"
            run_dir.mkdir()
            with self.assertRaises(orch.OrchestrationError) as context:
                orch._verify_docker(checkout, evaluator, orch.VERIFIER_IMAGE, 10, 4_096, run_dir)
            self.assertEqual(context.exception.code, "verifier_output_limit")
            self.assertLessEqual((run_dir / "verifier.stdout").stat().st_size +
                                 (run_dir / "verifier.stderr").stat().st_size, 4_096)

    def test_candidate_early_zero_exit_cannot_claim_green(self):
        with tempfile.TemporaryDirectory(prefix="jev-early-exit-test-") as temporary:
            directory = Path(temporary) / "case"
            orch.initialize(directory, ENDPOINT)
            fixtures_path = directory / "coding-fixtures.json"
            fixtures = read_json(fixtures_path)
            fixtures["fast"]["files"][0]["content"] = "import os\nos._exit(0)\n"
            save_json(fixtures_path, fixtures)
            with self.assertRaises(orch.OrchestrationError) as context:
                orch.run(directory, "fixture", "off", "baseline", None, False, False)
            self.assertIn(context.exception.code, ("checks_failed", "checks_incomplete"))
            run_dir = Path(context.exception.run_dir)
            self.assertNotIn("completed", [row["event"] for row in orch._events(run_dir)])

    def test_one_real_bounded_demo_uses_pinned_docker_verifier(self):
        for command in (["docker", "info", "--format", "{{.ServerVersion}}"],
                        ["docker", "image", "inspect", orch.VERIFIER_IMAGE, "--format", "{{.Id}}"]):
            probe = subprocess.run(command, capture_output=True, text=True, check=False,
                                   timeout=10)
            if probe.returncode != 0:
                self.skipTest("Docker daemon or pinned verifier image is unavailable")
        with tempfile.TemporaryDirectory(prefix="jev-demo-test-") as temporary:
            directory = Path(temporary) / "case"
            script = Path(orch.__file__)

            def command(*args):
                process = subprocess.run([sys.executable, "-B", str(script), *args],
                                         capture_output=True, text=True, check=False,
                                         timeout=45)
                self.assertEqual(process.returncode, 0, process.stderr)
                return json.loads(process.stdout)

            self.assertEqual(command("init", "--directory", str(directory))["status"], "completed")
            scope = command("dry-run", "--directory", str(directory), "--mode", "fixture",
                            "--jev-mode", "fixture", "--route-source", "baseline")
            self.assertEqual(scope["status"], "dry_run")
            self.assertFalse((directory / "runs").exists())
            result = command("demo", "--directory", str(directory))
            self.assertEqual(result["status"], "completed")
            self.assertIs(result["verified_completion"], True)
            run_dir = Path(result["run_dir"])
            self.assertEqual(command("inspect", "--run-dir", str(run_dir))["status"], "completed")
            self.assertEqual(command("replay", "--run-dir", str(run_dir))["route"], "fast")
            verification = read_json(run_dir / "verification.json")
            self.assertEqual(verification["exit_code"], 0)
            self.assertEqual(verification["command"][0:2], ["docker", "run"])
            self.assertIn("Ran 3 tests", (run_dir / "verifier.stderr").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
