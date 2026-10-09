#!/usr/bin/env python3
"""Direct bounded patch broker, Docker verifier, and saved-checkout reconstruction."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile

import jev_harness as jev
import orchestrate as orch


def _destination(output: Path, protected: list[Path]) -> Path:
    # Reject links before resolving so a linked parent cannot redirect a write.
    absolute = output.absolute()
    if any(p.is_symlink() for p in (absolute, *absolute.parents)):
        orch.fail("invalid_destination", "output contains a symbolic link.",
                  "Choose a new directory with regular parent directories.")
    output = absolute.resolve()
    if output.exists():
        orch.fail("destination_exists", "output already exists; nothing is replaced.",
                  "Choose a new output directory.")
    if not output.parent.is_dir():
        orch.fail("invalid_destination", "output parent does not exist.",
                  "Choose a destination under an existing directory.")
    for path in protected:
        path = path.resolve()
        if output.is_relative_to(path) or path.is_relative_to(output):
            orch.fail("invalid_destination", "output overlaps protected input or evidence.",
                      "Choose a separate output directory outside the task and saved run.")
    return output


def _regular_tree(root: Path, max_files: int, max_bytes: int) -> None:
    if not root.is_dir() or root.is_symlink():
        orch.fail("record_integrity_failed", "A required regular-file tree is missing or linked.",
                  "Restore the original evidence or use reconstruct for a derived checkout.")
    count = size = 0
    for path in root.rglob("*"):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            orch.fail("record_integrity_failed", "A tree contains a link or unsupported file.",
                      "Use regular-file artifacts only.")
        if path.is_file():
            count += 1
            size += path.stat().st_size
            if count > max_files or size > max_bytes:
                orch.fail("checkout_too_large", "The tree exceeds configured checkout limits.",
                          "Reduce task scope or adjust validated limits.")


def _start(output: Path, operation: str) -> orch.RunLedger:
    output.mkdir(exist_ok=False)
    ledger = orch.RunLedger(output)
    ledger.add("started", operation=operation)
    return ledger


def _failed(ledger: orch.RunLedger, output: Path, exc: Exception) -> None:
    if not isinstance(exc, orch.OrchestrationError):
        exc = orch.OrchestrationError("operation_failed", "The operation could not finish.",
                                      "Inspect the partial output and retry with a new destination.")
    exc.run_dir = str(output)
    ledger.add("failed", error=exc.report())
    raise exc


def _scope(operation: str, output: Path, config: dict, **fields) -> dict:
    return {"schema_version": 1, "operation": operation, "status": "dry_run",
            "output": str(output), "network_called": False,
            "limits": config["limits"], **fields}


def broker(directory: Path, patch_file: Path | None, output: Path, dry_run: bool = False,
           fixture_route: str | None = None) -> dict:
    base, config, task, _, repo, evaluator = orch.load_state(directory)
    orch._verify_base(repo, task["base_commit"])
    if (patch_file is None) == (fixture_route is None):
        orch.fail("invalid_patch_source", "Select exactly one patch_file or fixture_route.",
                  "Use --fixture-route fast|strong for a generated first run, or --patch-file.")
    if fixture_route is not None:
        if fixture_route not in orch.ROUTES:
            orch.fail("invalid_patch_source", "fixture_route must be fast or strong.",
                      "Select a generated fixture route.")
        fixtures = orch.load_json(orch._child(base, config["fixture_file"], "fixture_file"))
        orch._object(fixtures, "coding fixtures", set(orch.ROUTES))
        payload = fixtures[fixture_route]
    else:
        payload = orch.load_json(patch_file, config["limits"]["max_patch_bytes"])
    files = orch._parse_patch(orch.canonical_bytes(payload).decode("utf-8"), task,
                              config["limits"]["max_patch_bytes"])
    output = _destination(output, [base] + ([patch_file] if patch_file is not None else []))
    scope = _scope("broker", output, config, task_id=task["id"],
                   base_commit=task["base_commit"], files=[row["path"] for row in files],
                   patch_bytes=len(orch.canonical_bytes(payload)), fixture_route=fixture_route,
                   writes="new output only")
    if dry_run:
        return scope
    ledger = _start(output, "broker")
    try:
        archive = orch._archive_bytes(repo, task["base_commit"], config["limits"]["max_checkout_bytes"])
        checkout, scratch = output / "checkout", output / "restore-proof"
        for target in (checkout, scratch):
            orch._materialize(archive, target, config["limits"]["max_checkout_files"])
        base_hash = orch._tree_hash(scratch)
        if orch._tree_hash(checkout) != base_hash:
            orch.fail("restore_failed", "Scratch regeneration did not match the pinned base.",
                      "Inspect the base before applying any patch.")
        ledger.add("restore_proven", base_tree_sha256=base_hash)
        orch.write_new(output / "config.snapshot.json", config)
        orch.write_new(output / "task.snapshot.json", task)
        orch.snapshot_evaluator(evaluator, output / "trusted-evaluator" / evaluator.name,
                                task["evaluator_sha256"], config["limits"]["max_checkout_bytes"])
        hashes = orch._apply_patch(checkout, files)
        _regular_tree(checkout, config["limits"]["max_checkout_files"],
                      config["limits"]["max_checkout_bytes"])
        orch.write_new(output / "patch.json", {"base_commit": task["base_commit"],
                                               "files": files, "hashes": hashes})
        receipt = {"schema_version": 1, "config_hash": orch.digest(config),
                   "task_hash": orch.digest(task), "base_tree_sha256": base_hash,
                   "checkout_tree_sha256": orch._tree_hash(checkout),
                   "patch_sha256": orch.file_hash(output / "patch.json"),
                   "evaluator_sha256": task["evaluator_sha256"]}
        orch.write_new(output / "broker.json", receipt)
        ledger.add("patch_prepared", **receipt)
        return {**scope, "status": "prepared", "broker_dir": str(output),
                "checkout": str(checkout), "verified_completion": False,
                "checkout_tree_sha256": receipt["checkout_tree_sha256"]}
    except Exception as exc:
        _failed(ledger, output, exc)
    finally:
        ledger.close()


def _validate_broker(base: Path, config: dict, task: dict, broker_dir: Path,
                     regenerate: bool = True) -> Path:
    receipt = orch.load_json(broker_dir / "broker.json")
    orch._object(receipt, "broker receipt", {"schema_version", "config_hash", "task_hash",
                                            "base_tree_sha256", "checkout_tree_sha256",
                                            "patch_sha256", "evaluator_sha256"})
    if (type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1 or
            receipt["config_hash"] != orch.digest(config) or
            receipt["task_hash"] != orch.digest(task) or
            orch.load_json(broker_dir / "config.snapshot.json") != config or
            orch.load_json(broker_dir / "task.snapshot.json") != task):
        orch.fail("record_integrity_failed", "The broker receipt differs from the canonical task/config.",
                  "Use the original task configuration and broker output.")
    patch_path = broker_dir / "patch.json"
    if patch_path.is_symlink() or orch.file_hash(patch_path) != receipt["patch_sha256"]:
        orch.fail("record_integrity_failed", "The broker patch is missing or changed.",
                  "Restore the original broker evidence.")
    patch = orch.load_json(patch_path)
    orch._object(patch, "broker patch", {"base_commit", "files", "hashes"})
    files = orch._parse_patch(orch.canonical_bytes({"files": patch["files"]}).decode("utf-8"),
                              task, config["limits"]["max_patch_bytes"])
    checkout = broker_dir / "checkout"
    _regular_tree(checkout, config["limits"]["max_checkout_files"],
                  config["limits"]["max_checkout_bytes"])
    evaluator = broker_dir / "trusted-evaluator" / Path(task["evaluator_file"]).name
    if (evaluator.is_symlink() or not evaluator.is_file() or
            receipt["evaluator_sha256"] != task["evaluator_sha256"] or
            orch.file_hash(evaluator) != task["evaluator_sha256"]):
        orch.fail("record_integrity_failed", "The broker evaluator differs from the protected evaluator.",
                  "Restore the original evaluator snapshot.")
    if orch._tree_hash(checkout) != receipt["checkout_tree_sha256"]:
        orch.fail("record_integrity_failed", "The broker checkout differs from its receipt.",
                  "Create a new broker output from the canonical task and patch.")
    if not regenerate:
        return evaluator
    repo = orch._child(base, task["source_repo"], "task.source_repo")
    archive = orch._archive_bytes(repo, task["base_commit"], config["limits"]["max_checkout_bytes"])
    with tempfile.TemporaryDirectory(prefix="jev-broker-check-") as temporary:
        regenerated = Path(temporary) / "checkout"
        orch._materialize(archive, regenerated, config["limits"]["max_checkout_files"])
        base_hash = orch._tree_hash(regenerated)
        hashes = orch._apply_patch(regenerated, files)
        expected_hash = orch._tree_hash(regenerated)
        if (patch["base_commit"] != task["base_commit"] or patch["hashes"] != hashes or
                receipt["base_tree_sha256"] != base_hash or
                receipt["checkout_tree_sha256"] != expected_hash or
                orch._tree_hash(checkout) != expected_hash):
            orch.fail("record_integrity_failed", "The broker checkout differs from pinned base plus patch.",
                      "Create a new broker output from the canonical task and patch.")
    return evaluator


def verify(directory: Path, broker_dir: Path, output: Path, dry_run: bool = False) -> dict:
    base, config, task, _, _, _ = orch.load_state(directory)
    broker_dir = broker_dir.resolve()
    output = _destination(output, [base, broker_dir])
    # Dry-run validates existing files using reads. Full regeneration precedes Docker.
    evaluator = _validate_broker(base, config, task, broker_dir, regenerate=not dry_run)
    scope = _scope("verify", output, config, task_id=task["id"], broker_dir=str(broker_dir),
                   verifier_image=config["verifier_image"], writes="new verifier evidence only")
    if dry_run:
        return scope
    ledger = _start(output, "verify")
    try:
        ledger.add("admitted", task_hash=orch.digest(task), config_hash=orch.digest(config),
                   broker_dir=str(broker_dir),
                   broker_receipt_sha256=orch.file_hash(broker_dir / "broker.json"),
                   checkout_tree_sha256=orch._tree_hash(broker_dir / "checkout"),
                   evaluator_sha256=task["evaluator_sha256"])
        result = orch._verify_docker(broker_dir / "checkout", evaluator,
                                     config["verifier_image"], config["limits"]["max_eval_seconds"],
                                     config["limits"]["max_evidence_bytes"], output)
        # Persist process failure evidence before interpreting its success verdict.
        orch.write_new(output / "verification.json", result)
        ledger.add("verified", **result)
        if result["exit_code"] != 0:
            orch.fail("checks_failed", "The protected verifier did not pass.",
                      "Inspect verifier.stdout and verifier.stderr in the output directory.")
        verdict = orch._trusted_verdict(Path(result["stdout_path"]))
        # Check again after execution: a changed host-side checkout cannot earn completion.
        _validate_broker(base, config, task, broker_dir)
        ledger.add("completed", verdict=verdict, verified_completion=True)
        return {**scope, "status": "completed", "verified_completion": True,
                "verification_path": str(output / "verification.json"), "verdict": verdict}
    except Exception as exc:
        _failed(ledger, output, exc)
    finally:
        ledger.close()


def reconstruct(run_dir: Path, output: Path, dry_run: bool = False) -> dict:
    run_dir = run_dir.resolve()
    base = run_dir.parent.parent
    config = orch.validate_config(orch.load_json(run_dir / "config.snapshot.json"))
    task = orch.validate_task(orch.load_json(run_dir / "task.snapshot.json"), base)
    output = _destination(output, [base])
    events = orch._events(run_dir)
    if not events or events[-1].get("event") != "completed":
        orch.fail("reconstruction_unavailable", "Only a completed run has full reconstruction evidence.",
                  "Inspect the incomplete run; do not substitute a partial result.")
    scope = _scope("reconstruct", output, config, run_dir=str(run_dir),
                   base_commit=task["base_commit"], writes="new reconstructed checkout only")
    if dry_run:
        return scope
    repo = orch._child(base, task["source_repo"], "task.source_repo")
    archive = orch._archive_bytes(repo, task["base_commit"], config["limits"]["max_checkout_bytes"])
    patch = orch.load_json(run_dir / "patch.json")
    files = orch._parse_patch(orch.canonical_bytes({"files": patch["files"]}).decode("utf-8"),
                              task, config["limits"]["max_patch_bytes"])
    # First prove the restore into scratch, then validate every historical artifact
    # using that reconstructed tree. A damaged original checkout is never trusted.
    with tempfile.TemporaryDirectory(prefix="jev-reconstruct-") as temporary:
        scratch = Path(temporary) / "checkout"
        orch._materialize(archive, scratch, config["limits"]["max_checkout_files"])
        restore = next(row for row in events if row["event"] == "restore_proven")
        if orch._tree_hash(scratch) != restore["base_tree_sha256"]:
            orch.fail("restore_failed", "The pinned Git base differs from the saved restore proof.",
                      "Restore the original pinned repository and run artifacts.")
        orch._apply_patch(scratch, files)
        _regular_tree(scratch, config["limits"]["max_checkout_files"],
                      config["limits"]["max_checkout_bytes"])
        orch.replay(run_dir, reconstructed_checkout=scratch)
        expected = orch._tree_hash(scratch)
        # No replacement: existing paths are refused, including the damaged original.
        orch._materialize(archive, output, config["limits"]["max_checkout_files"])
        try:
            orch._apply_patch(output, files)
            if orch._tree_hash(output) != expected:
                orch.fail("restore_failed", "Published reconstruction differs from the scratch proof.",
                          "Inspect the partial output; retry with a new destination.")
        except Exception as exc:
            error = exc if isinstance(exc, orch.OrchestrationError) else orch.OrchestrationError(
                "restore_failed", "Reconstruction could not finish.", "Inspect output and use a new destination.")
            error.run_dir = str(output)
            raise error
    return {**scope, "status": "reconstructed", "checkout_tree_sha256": expected,
            "historical_evidence_validated": True, "tests_rerun": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("broker", "verify", "reconstruct"):
        command = sub.add_parser(name)
        command.add_argument("--output", required=True)
        command.add_argument("--dry-run", action="store_true")
        if name == "reconstruct":
            command.add_argument("--run-dir", required=True)
        else:
            command.add_argument("--directory", required=True)
            if name == "broker":
                source = command.add_mutually_exclusive_group(required=True)
                source.add_argument("--patch-file")
                source.add_argument("--fixture-route", choices=orch.ROUTES)
            else:
                command.add_argument("--broker-dir", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "broker":
            result = broker(Path(args.directory), Path(args.patch_file) if args.patch_file else None,
                            Path(args.output), args.dry_run, args.fixture_route)
        elif args.command == "verify":
            result = verify(Path(args.directory), Path(args.broker_dir), Path(args.output), args.dry_run)
        else:
            result = reconstruct(Path(args.run_dir), Path(args.output), args.dry_run)
        print(orch.canonical_bytes(result).decode("utf-8"))
        return 0
    except (orch.OrchestrationError, jev.HarnessError) as exc:
        report = exc.report() if isinstance(exc, orch.OrchestrationError) else {
            "status": "failed", "code": exc.code, "message": exc.message,
            "next_action": exc.next_action}
    except Exception:
        report = {"status": "failed", "code": "operation_failed",
                  "message": "The operation could not finish.",
                  "next_action": "Inspect input paths and partial output; retry with a new destination."}
    print(orch.canonical_bytes(report).decode("utf-8"), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
