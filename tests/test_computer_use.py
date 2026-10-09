"""Real Chromium integration and boundary checks for the local fixture slice."""
import concurrent.futures
import copy
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

import computer_use as controller
import ui_fixture
from ui_common import UIError, digest, load, observe, read, rpc, save_record, validate
from ui_executor import execute
from ui_verify import verify


def port():
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return handle.getsockname()[1]


class Contracts(unittest.TestCase):
    def test_config_bounds_and_unknown_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "fixture"
            ui_fixture.generate(root, port=port())
            _, config, task = load(root)
            for key, value in [("port", 80), ("max_steps", 5), ("freshness_ms", True), ("max_run_ms", 0), ("headless", 1), ("extra", 0)]:
                with self.subTest(key=key), self.assertRaises(UIError):
                    validate({**config, key: value}, task)
            with self.assertRaises(UIError):
                validate(config, {**task, "note": "x" * 201})

    def test_reset_retains_custom_valid_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "fixture"
            ui_fixture.generate(root, port=port())
            config = read(root / "config.json")
            config["freshness_ms"] = 12345
            # Only disposable generated input; original and changed bytes retained by this test.
            original = (root / "config.json").read_bytes()
            restored = Path(temporary) / "restore.json"
            restored.write_bytes(original)
            self.assertEqual(restored.read_bytes(), original)
            (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
            output = Path(temporary) / "reset"
            ui_fixture.reset(root, output)
            self.assertEqual(load(root)[1:], load(output)[1:])

    def test_failed_serve_is_failed_command(self):
        with patch("ui_fixture.serve", return_value=7), patch("sys.argv", ["ui_fixture.py", "serve", "--directory", "unused"]):
            self.assertEqual(ui_fixture.main(), 1)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "absent"
            with patch("sys.argv", ["computer_use.py", "dry-run", "--directory", str(root)]):
                self.assertEqual(controller.main(), 0)
            self.assertFalse(root.exists())


class Browser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        controller.doctor()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "fixture"
        self.process = None

    def launch(self, variant="clean", config_changes=None):
        ui_fixture.generate(self.root, port=port(), variant=variant)
        if config_changes:
            config = read(self.root / "config.json")
            original = (self.root / "config.json").read_bytes()
            backup = Path(self.temporary.name) / "config.backup"
            backup.write_bytes(original)
            self.assertEqual(backup.read_bytes(), original)
            (self.root / "config.json").write_text(json.dumps({**config, **config_changes}), encoding="utf-8")
        self.process = controller.start(self.root)

    def tearDown(self):
        if self.process:
            if self.process.poll() is None:
                try: rpc(self.root, "shutdown")
                except UIError: self.process.terminate()
            self.process.wait(timeout=10)
        self.temporary.cleanup()

    def test_complete_and_replay_without_browser_or_provider(self):
        self.launch()
        self.assertEqual(verify(self.root)["status"], "verification_failed")
        controller.step(self.root)
        controller.step(self.root)
        result = verify(self.root)
        self.assertEqual(result["status"], "completed")
        with patch("computer_use.rpc", side_effect=AssertionError("No RPC in replay")), patch("jev_harness._live_response", side_effect=AssertionError("No provider in replay")):
            replayed = controller.replay(self.root, result["verification"])
        self.assertEqual(replayed["ui_actions"], 0)
        self.assertEqual(replayed["provider_calls"], 0)

    def test_duplicate_and_concurrent_permit(self):
        self.launch()
        permit = controller.broker(self.root)["permit"]
        def attempt():
            try: return execute(self.root, permit)["status"]
            except UIError: return "refused"
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: attempt(), range(2)))
        self.assertCountEqual(results, ["executed", "refused"])
        with self.assertRaisesRegex(UIError, "consumed"):
            execute(self.root, permit)
        self.assertEqual(read(observe(self.root))["value"]["snapshot"]["revision"], 1)

    def test_stale_state(self):
        self.launch()
        old = controller.broker(self.root)["permit"]
        current = controller.broker(self.root)["permit"]
        execute(self.root, current)
        with self.assertRaisesRegex(UIError, "Stale"):
            execute(self.root, old)

    def test_cancel(self):
        self.launch()
        permit = controller.broker(self.root)["permit"]
        rpc(self.root, "stop")
        with self.assertRaisesRegex(UIError, "cancelled"):
            execute(self.root, permit)
        self.assertEqual(read(observe(self.root))["value"]["snapshot"]["revision"], 0)

    def test_step_cap(self):
        self.launch(config_changes={"max_steps": 1})
        controller.step(self.root)
        with self.assertRaisesRegex(UIError, "max_steps"):
            controller.step(self.root)
        self.assertEqual(verify(self.root)["status"], "verification_failed")

    def test_unsupported_argument_and_missing_audit(self):
        self.launch()
        permit = read(controller.broker(self.root)["permit"])
        grant = permit["value"]
        action = save_record(self.root, "UIAction", {"label": "fill_note", "target": "note", "argument": "unauthorized"})
        bad = save_record(self.root, "ActionPermit", {**grant, "action": action.name, "action_hash": digest(read(action))})
        with self.assertRaisesRegex(UIError, "unauthorized"):
            execute(self.root, bad)
        decision = read(self.root / "records" / grant["decision"])
        absent = save_record(self.root, "JevShadow", {**decision["value"], "audit": "jev-audit/absent.jsonl"})
        bad = save_record(self.root, "ActionPermit", {**grant, "decision": absent.name, "decision_hash": digest(read(absent))})
        with self.assertRaises(UIError):
            execute(self.root, bad)
        self.assertEqual(read(observe(self.root))["value"]["snapshot"]["revision"], 0)

    def test_expired_wrong_session_and_permit_path(self):
        self.launch()
        permit = read(controller.broker(self.root)["permit"])
        grant = permit["value"]
        bad = save_record(self.root, "ActionPermit", {**grant, "session_id": "wrong"})
        with self.assertRaisesRegex(UIError, "inconsistent"):
            execute(self.root, bad)
        observation = read(self.root / "records" / grant["observation"])
        expired = save_record(self.root, "UIObservation", {**observation["value"], "created_ms": 0})
        bad = save_record(self.root, "ActionPermit", {**grant, "observation": expired.name, "observation_hash": digest(read(expired))})
        with self.assertRaisesRegex(UIError, "Expired"):
            execute(self.root, bad)
        with self.assertRaisesRegex(UIError, "path"):
            execute(self.root, Path(self.temporary.name) / "outside.json")

    def test_reset_restores_empty_state(self):
        self.launch()
        controller.step(self.root)
        rpc(self.root, "shutdown"); self.process.wait(timeout=10); self.process = None
        reset = Path(self.temporary.name) / "reset"
        ui_fixture.reset(self.root, reset)
        old = self.root
        self.root = reset
        self.process = controller.start(reset)
        state = read(observe(reset))["value"]["snapshot"]
        self.assertEqual((state["note"], state["draft"], state["revision"], state["save_count"]), ("", "", 0, 0))
        self.assertTrue((old / "attempts").exists())

    def test_missing_permit(self):
        self.launch()
        with self.assertRaises(UIError):
            execute(self.root, self.root / "records" / "00000000-0000-0000-0000-000000000000.json")

    def test_unknown_outcome_after_effect_never_repeats(self):
        # Inject a storage failure only in this child, after fill() and before acknowledgement.
        hook = Path(self.temporary.name) / "fault.cjs"
        hook.write_text("const fs=require('fs');const original=fs.writeFileSync;fs.writeFileSync=function(fd,data,...args){if(typeof data==='string'&&data.includes('\\\"kind\\\":\\\"UIExecution\\\"'))throw Error('Injected acknowledgement storage failure');return original.call(this,fd,data,...args)};", encoding="utf-8")
        with patch.dict(os.environ, {"NODE_OPTIONS": f'--require="{hook.as_posix()}"'}):
            self.launch()
        permit = controller.broker(self.root)["permit"]
        with self.assertRaisesRegex(UIError, "unknown_outcome"):
            execute(self.root, permit)
        state = read(observe(self.root))["value"]["snapshot"]
        self.assertEqual(state["revision"], 1)
        with self.assertRaisesRegex(UIError, "unknown_outcome"):
            controller.step(self.root)
        self.assertEqual(read(observe(self.root))["value"]["snapshot"]["revision"], 1)
        self.assertEqual(verify(self.root)["status"], "verification_failed")
        self.assertEqual(len(list((self.root / "attempts").glob("*.intent.json"))), 1)
        self.assertEqual(len(list((self.root / "attempts").glob("*.result.json"))), 0)

    def test_changed_verification_cannot_claim_completion(self):
        self.launch()
        incomplete = verify(self.root)
        forged = save_record(self.root, "Verification", {**read(incomplete["verification"])["value"], "status": "completed", "checks": {key:True for key in incomplete["checks"]}})
        with self.assertRaisesRegex(UIError, "integrity"):
            controller.replay(self.root, forged)

    def test_isolated_page_blocks_external_resources(self):
        self.launch(variant="egress")
        value = read(observe(self.root))["value"]["snapshot"]
        self.assertEqual(value["allowed_requests"], [value["url"]])
        self.assertIn("http://127.0.0.1:1/forbidden", value["failed_requests"])
        controller.step(self.root); controller.step(self.root)
        self.assertEqual(verify(self.root)["status"], "completed")


class FixtureVariants(unittest.TestCase):
    def test_ambiguous_hidden_disabled_injection(self):
        for variant in ("ambiguous", "hidden", "disabled", "injection", "wrong_origin"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "fixture"
                ui_fixture.generate(root, port=port(), variant=variant)
                process = controller.start(root)
                try:
                    with self.assertRaises(UIError): controller.broker(root)
                    self.assertFalse((root / "attempts").exists())
                finally:
                    rpc(root, "shutdown"); process.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
