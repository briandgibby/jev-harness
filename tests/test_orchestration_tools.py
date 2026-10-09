"""Independent interfaces retain the controller's effect and completion boundaries."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import orchestrate as orch
import orchestration_tools as interfaces


def fake_verifier(exit_code=0, verdict=True):
    def verify(checkout, evaluator, image, timeout, max_bytes, output):
        assert evaluator.is_file()
        assert image == orch.VERIFIER_IMAGE
        assert (checkout / "solution.py").is_file()
        stdout, stderr = output / "verifier.stdout", output / "verifier.stderr"
        stdout.write_text(json.dumps({"schema_version": 1, "tests_run": 3,
                                      "failures": 0, "errors": 0}) if verdict else "")
        stderr.write_text("synthetic verifier output\n")
        return {"command": ["synthetic-verifier"], "exit_code": exit_code,
                "stdout_path": str(stdout), "stderr_path": str(stderr),
                "stdout_sha256": orch.file_hash(stdout), "stderr_sha256": orch.file_hash(stderr),
                "elapsed_ms": 0}
    return verify


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="jev-interface-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.case = self.root / "case"
        orch.initialize(self.case, "http://127.0.0.1:8000/v1/chat/completions")
        self.patch_file = self.root / "input-patch.json"
        fixture = orch.load_json(self.case / "coding-fixtures.json")["fast"]
        orch.write_new(self.patch_file, fixture)

    def broker(self):
        return interfaces.broker(self.case, self.patch_file, self.root / "broker")

    def completed_run(self):
        with patch.object(orch, "_verify_docker", side_effect=fake_verifier()):
            result = orch.run(self.case, "fixture", "off", "baseline", None, False, False)
        return Path(result["run_dir"])

    def assert_failure(self, expected, call):
        with self.assertRaises(orch.OrchestrationError) as context:
            call()
        self.assertEqual(context.exception.code, expected)
        return context.exception

    def test_broker_dry_run_has_no_writes_or_provider_calls(self):
        before = orch._tree_hash(self.root)
        with patch.object(orch, "_archive_bytes", side_effect=AssertionError("no archive needed")):
            result = interfaces.broker(self.case, self.patch_file, self.root / "broker", True)
        self.assertEqual(result["files"], ["solution.py"])
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(result["network_called"])
        self.assertEqual(before, orch._tree_hash(self.root))

    def test_broker_applies_declared_patch_without_touching_source_or_claiming_completion(self):
        before = orch._tree_hash(self.case)
        result = self.broker()
        self.assertEqual(result["status"], "prepared")
        self.assertFalse(result["verified_completion"])
        self.assertEqual(before, orch._tree_hash(self.case))
        self.assertEqual((Path(result["checkout"]) / "solution.py").read_text(),
                         orch.load_json(self.patch_file)["files"][0]["content"])

    def test_first_run_uses_generated_fixture_without_manually_placed_patch(self):
        result = interfaces.broker(self.case, None, self.root / "broker", fixture_route="fast")
        self.assertEqual(result["status"], "prepared")
        self.assertEqual(result["fixture_route"], "fast")
        self.assertEqual((Path(result["checkout"]) / "solution.py").read_text(),
                         orch.load_json(self.case / "coding-fixtures.json")["fast"]["files"][0]["content"])

    def test_broker_rejects_undeclared_evaluator_write_before_output(self):
        self.patch_file.write_text(json.dumps({"files": [{"path": "../evaluator/test_solution.py",
                                                        "content": "pass\n"}]}))
        self.assert_failure("invalid_patch", self.broker)
        self.assertFalse((self.root / "broker").exists())

    def test_existing_or_overlapping_destination_is_refused(self):
        self.assert_failure("destination_exists", lambda: interfaces.broker(
            self.case, self.patch_file, self.case))
        self.assert_failure("invalid_destination", lambda: interfaces.broker(
            self.case, self.patch_file, self.case / "new-output"))
        self.broker()
        before = orch._tree_hash(self.root / "broker")
        self.assert_failure("destination_exists", self.broker)
        self.assertEqual(before, orch._tree_hash(self.root / "broker"))

    def test_verify_uses_shared_sandbox_and_records_verdict(self):
        result = self.broker()
        with patch.object(orch, "_verify_docker", side_effect=fake_verifier()) as verifier:
            checked = interfaces.verify(self.case, Path(result["broker_dir"]), self.root / "verified")
        self.assertTrue(checked["verified_completion"])
        self.assertEqual(checked["verdict"]["tests_run"], 3)
        self.assertEqual(verifier.call_args.args[2], orch.VERIFIER_IMAGE)
        events = orch._events(self.root / "verified")
        self.assertEqual(events[1]["event"], "admitted")
        self.assertEqual(events[1]["broker_receipt_sha256"],
                         orch.file_hash(Path(result["broker_dir"]) / "broker.json"))
        self.assertEqual(events[-1]["event"], "completed")
        self.assertTrue((self.root / "verified" / "verification.json").is_file())

    def test_verifier_dry_run_only_reads_and_does_not_invoke_docker(self):
        result = self.broker()
        before = orch._tree_hash(self.root)
        with patch.object(orch, "_verify_docker", side_effect=AssertionError("no Docker")):
            checked = interfaces.verify(self.case, Path(result["broker_dir"]), self.root / "verified", True)
        self.assertEqual(checked["status"], "dry_run")
        self.assertEqual(before, orch._tree_hash(self.root))

    def test_changed_checkout_or_receipt_cannot_reach_verifier(self):
        result = self.broker()
        (Path(result["checkout"]) / "solution.py").write_text("def add(a, b): return 99\n")
        with patch.object(orch, "_verify_docker", side_effect=AssertionError("must stop")):
            self.assert_failure("record_integrity_failed", lambda: interfaces.verify(
                self.case, Path(result["broker_dir"]), self.root / "verified"))
        self.assertFalse((self.root / "verified").exists())

    def test_verifier_dry_run_rejects_missing_broker_instead_of_reporting_valid_scope(self):
        self.assert_failure("file_read_failed", lambda: interfaces.verify(
            self.case, self.root / "missing-broker", self.root / "verified", True))
        self.assertFalse((self.root / "verified").exists())

    def test_failed_verifier_keeps_unedited_output_and_terminal_failure(self):
        result = self.broker()
        with patch.object(orch, "_verify_docker", side_effect=fake_verifier(exit_code=1)):
            error = self.assert_failure("checks_failed", lambda: interfaces.verify(
                self.case, Path(result["broker_dir"]), self.root / "verified"))
        self.assertEqual(error.run_dir, str(self.root / "verified"))
        self.assertEqual(orch._events(self.root / "verified")[-1]["event"], "failed")
        self.assertEqual((self.root / "verified" / "verifier.stderr").read_text(),
                         "synthetic verifier output\n")
        self.assertEqual(orch.load_json(self.root / "verified" / "verification.json")["exit_code"], 1)

    def test_zero_exit_without_verdict_never_completes(self):
        result = self.broker()
        with patch.object(orch, "_verify_docker", side_effect=fake_verifier(verdict=False)):
            self.assert_failure("checks_incomplete", lambda: interfaces.verify(
                self.case, Path(result["broker_dir"]), self.root / "verified"))
        self.assertEqual(orch._events(self.root / "verified")[-1]["event"], "failed")
        self.assertTrue((self.root / "verified" / "verification.json").is_file())

    def test_verifier_failure_to_start_has_a_reportable_output_directory(self):
        result = self.broker()
        failure = orch.OrchestrationError("verifier_unavailable", "Docker unavailable.", "Start Docker.")
        with patch.object(orch, "_verify_docker", side_effect=failure):
            self.assert_failure("verifier_unavailable", lambda: interfaces.verify(
                self.case, Path(result["broker_dir"]), self.root / "verified"))
        self.assertEqual(orch._events(self.root / "verified")[-1]["error"]["next_action"], "Start Docker.")

    def test_mutation_during_verification_cannot_complete(self):
        result = self.broker()
        delegate = fake_verifier()
        def mutate(*args):
            response = delegate(*args)
            (args[0] / "solution.py").write_text("changed while checking\n")
            return response
        with patch.object(orch, "_verify_docker", side_effect=mutate):
            self.assert_failure("record_integrity_failed", lambda: interfaces.verify(
                self.case, Path(result["broker_dir"]), self.root / "verified"))
        self.assertEqual(orch._events(self.root / "verified")[-1]["event"], "failed")

    def test_reconstruct_recovers_damaged_checkout_without_overwriting_it(self):
        run_dir = self.completed_run()
        expected = orch._tree_hash(run_dir / "checkout")
        damaged = run_dir / "checkout" / "solution.py"
        damaged.write_text("damaged derived file\n")
        self.assert_failure("record_integrity_failed", lambda: orch.replay(run_dir))
        before = orch._tree_hash(self.case)
        result = interfaces.reconstruct(run_dir, self.root / "restored")
        self.assertEqual(result["status"], "reconstructed")
        self.assertTrue(result["historical_evidence_validated"])
        self.assertFalse(result["tests_rerun"])
        self.assertEqual(expected, orch._tree_hash(self.root / "restored"))
        self.assertEqual(before, orch._tree_hash(self.case))
        self.assertEqual(damaged.read_text(), "damaged derived file\n")

    def test_reconstruct_restores_missing_checkout_and_refuses_existing_output(self):
        run_dir = self.completed_run()
        # This tree is derived: prove regeneration before exercising deletion in scratch.
        interfaces.reconstruct(run_dir, self.root / "proof")
        self.assertEqual(orch._tree_hash(self.root / "proof"), orch._tree_hash(run_dir / "checkout"))
        shutil.rmtree(run_dir / "checkout")
        interfaces.reconstruct(run_dir, self.root / "restored")
        self.assertEqual(orch._tree_hash(self.root / "proof"), orch._tree_hash(self.root / "restored"))
        self.assert_failure("destination_exists", lambda: interfaces.reconstruct(run_dir, self.root / "proof"))

    def test_reconstruct_rejects_tampered_patch_before_publishing(self):
        run_dir = self.completed_run()
        # Preserve and prove restoration of the test-only evidence before tampering.
        original = (run_dir / "patch.json").read_bytes()
        backup = self.root / "patch.backup"
        backup.write_bytes(original)
        restored = self.root / "patch.restore"
        restored.write_bytes(backup.read_bytes())
        self.assertEqual(original, restored.read_bytes())
        saved = orch.load_json(run_dir / "patch.json")
        saved["files"][0]["content"] = "def add(a, b): return 999\n"
        (run_dir / "patch.json").write_text(json.dumps(saved))
        self.assert_failure("record_integrity_failed", lambda: interfaces.reconstruct(run_dir, self.root / "restored"))
        self.assertFalse((self.root / "restored").exists())

    def test_reconstruct_dry_run_does_not_create_scratch_or_output(self):
        run_dir = self.completed_run()
        before = orch._tree_hash(self.root)
        with patch.object(orch, "_archive_bytes", side_effect=AssertionError("read-only dry run")):
            result = interfaces.reconstruct(run_dir, self.root / "restored", True)
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(before, orch._tree_hash(self.root))

    def test_cli_reports_nonzero_json_for_missing_input(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = interfaces.main(["reconstruct", "--run-dir", str(self.root / "missing"),
                                      "--output", str(self.root / "restored")])
        self.assertEqual(status, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(json.loads(stderr.getvalue())["code"], "file_read_failed")


class DockerInterfaceIntegrationTest(unittest.TestCase):
    def test_direct_broker_and_verifier_with_real_pinned_docker(self):
        with tempfile.TemporaryDirectory(prefix="jev-interface-docker-") as temporary:
            root = Path(temporary)
            case = root / "case"
            orch.initialize(case, "http://127.0.0.1:8000/v1/chat/completions")
            patch_file = root / "patch.json"
            orch.write_new(patch_file, orch.load_json(case / "coding-fixtures.json")["fast"])
            prepared = interfaces.broker(case, patch_file, root / "broker")
            result = interfaces.verify(case, Path(prepared["broker_dir"]), root / "verify")
            self.assertEqual(result["verdict"]["tests_run"], 3)
            recorded = orch.load_json(root / "verify" / "verification.json")
            command = recorded["command"]
            self.assertIn(orch.VERIFIER_IMAGE, command)
            for required in ("--network", "none", "--read-only", "--cap-drop", "ALL"):
                self.assertIn(required, command)


if __name__ == "__main__":
    unittest.main()
