#!/usr/bin/env python3
"""One-task coding experiment with bounded Jev routing and local inference.

The controller, rather than either model, owns eligibility, file effects, and
verification. Fixture mode is a plumbing test. Live mode is a watched local
experiment, not an unattended coding agent.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid

import jev_harness as jev
import local_model
from probe_live import read_key


SCHEMA_VERSION = 1
MAX_JSON_BYTES = 1_000_000
MAX_CHECKOUT_BYTES = 50_000_000
MAX_CHECKOUT_FILES = 1_000
MAX_PATCH_BYTES = 65_536
MAX_EVIDENCE_BYTES = 262_144
VERIFIER_IMAGE = "docker.io/library/python@sha256:b921fe7e7522f828d45197a47656ec465a9b15689b27fa8e1fba2864fca5b967"
ROUTES = ("fast", "strong")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MODEL_PIN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_SECRET_HINT = re.compile(r"(?i)(-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{16,})")


class OrchestrationError(Exception):
    def __init__(self, code: str, message: str, next_action: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.next_action = next_action
        self.run_dir: str | None = None

    def report(self) -> dict:
        status = "review_required" if self.code == "review_required" else "failed"
        return {"status": status, "code": self.code, "message": self.message,
                "next_action": self.next_action, "run_dir": self.run_dir}


def fail(code: str, message: str, action: str) -> None:
    raise OrchestrationError(code, message, action)


def canonical_bytes(value) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise OrchestrationError("invalid_json", "A value is not supported JSON.",
                                 "Use finite JSON and valid UTF-8 text.") from exc


def digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_hash(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            fail("invalid_json", "JSON contains a duplicate object key.", "Remove the duplicate key.")
        value[key] = item
    return value


def _reject_constant(_value):
    fail("invalid_json", "JSON contains NaN or Infinity.", "Use finite JSON numbers.")


def load_json(path: Path, limit: int = MAX_JSON_BYTES):
    try:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
    except OSError as exc:
        raise OrchestrationError("file_read_failed", "A required JSON file could not be read.",
                                 "Check the path and permissions.") from exc
    if len(raw) > limit:
        fail("file_too_large", "A JSON file exceeds its byte limit.", "Reduce the file size.")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
                          parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise OrchestrationError("invalid_json", "A file is not supported UTF-8 JSON.",
                                 "Correct the JSON file.") from exc


def write_new(path: Path, value) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise OrchestrationError("write_failed", "A new record could not be written.",
                                 "Inspect the partial run and storage permissions; no file is replaced.") from exc


def snapshot_evaluator(source: Path, target: Path, expected_sha256: str,
                       max_bytes: int) -> None:
    try:
        with source.open("rb") as stream:
            raw = stream.read(max_bytes + 1)
    except OSError as exc:
        raise OrchestrationError("evaluator_changed", "The trusted evaluator could not be read.",
                                 "Restore the evaluator and start a new run.") from exc
    if (len(raw) > max_bytes or hashlib.sha256(raw).hexdigest() != expected_sha256):
        fail("evaluator_changed", "The trusted evaluator exceeds the task bound or changed.",
             "Restore the pinned evaluator or reduce its size before a new run.")
    try:
        target.parent.mkdir(exist_ok=False)
        with target.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise OrchestrationError("write_failed", "The trusted evaluator snapshot could not be written.",
                                 "Inspect the partial run and storage permissions.") from exc


def _object(value, field: str, keys: set[str]) -> None:
    if type(value) is not dict or set(value) != keys:
        fail("invalid_field", f"{field} must contain exactly: {', '.join(sorted(keys))}.",
             "Correct the named configuration or task field.")


def _text(value, field: str, limit: int = 1024) -> None:
    if type(value) is not str or not value.strip() or len(value) > limit:
        fail("invalid_field", f"{field} must be nonempty text of at most {limit} characters.",
             "Correct the named field.")
    try:
        value.encode("utf-8")
    except UnicodeError:
        fail("invalid_field", f"{field} contains invalid Unicode.", "Use valid UTF-8 text.")


def _integer(value, field: str, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        fail("invalid_field", f"{field} must be an integer in {low}..{high}.",
             "Correct the named setting within its code-owned bounds.")


def _child(base: Path, name: str, field: str) -> Path:
    _text(name, field, 240)
    parts = name.replace("\\", "/").split("/")
    if (Path(name).is_absolute() or ":" in name or
            any(part in ("", ".", "..") for part in parts)):
        fail("invalid_path", f"{field} must be a clean relative child path.",
             "Use a relative path without dot segments or drive letters.")
    path = (base / name).resolve()
    if not path.is_relative_to(base.resolve()) or path == base.resolve():
        fail("invalid_path", f"{field} resolves outside its root.", "Choose a child path.")
    return path


def load_model_pins() -> dict:
    pins = load_json(Path(__file__).with_name("model-pins.json"))
    _object(pins, "model pins", {"schema_version", "models"})
    if type(pins["schema_version"]) is not int or pins["schema_version"] != 1:
        fail("invalid_model_pins", "model-pins.json schema_version must be integer 1.",
             "Restore a supported pinned model registry.")
    _object(pins["models"], "model pins models", set(ROUTES))
    for route in ROUTES:
        spec = pins["models"][route]
        _object(spec, f"model pins {route}", {"id", "provider_model", "hf_repo",
                                               "hf_revision", "bytes", "file_count",
                                               "weights_sha256", "tool_parser"})
        for name in ("id", "provider_model"):
            _text(spec[name], f"model pins {route}.{name}", 200)
            if not _MODEL_PIN_ID.fullmatch(spec[name]):
                fail("invalid_model_pins", f"model pins {route}.{name} is invalid.",
                     "Use a stable printable model name.")
        _text(spec["hf_repo"], f"model pins {route}.hf_repo", 200)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", spec["hf_repo"]):
            fail("invalid_model_pins", f"model pins {route}.hf_repo is invalid.",
                 "Use an exact organization/model repository.")
        if type(spec["hf_revision"]) is not str or not _COMMIT.fullmatch(spec["hf_revision"]):
            fail("invalid_model_pins", f"model pins {route}.hf_revision must be a full commit.",
                 "Pin the model to an immutable commit.")
        _integer(spec["bytes"], f"model pins {route}.bytes", 1, 100_000_000_000)
        _integer(spec["file_count"], f"model pins {route}.file_count", 1, 1_000)
        if type(spec["weights_sha256"]) is not str or not _SHA256.fullmatch(spec["weights_sha256"]):
            fail("invalid_model_pins", f"model pins {route}.weights_sha256 is invalid.",
                 "Pin the exact model weights SHA-256.")
        if spec["tool_parser"] is not None:
            _text(spec["tool_parser"], f"model pins {route}.tool_parser", 64)
            if not _SAFE_ID.fullmatch(spec["tool_parser"]):
                fail("invalid_model_pins", f"model pins {route}.tool_parser is invalid.",
                     "Use a safe parser ID or null.")
    if pins["models"]["fast"]["id"] == pins["models"]["strong"]["id"]:
        fail("invalid_model_pins", "The two model pin IDs must be distinct.",
             "Give each registered model one stable ID.")
    return pins


def validate_config(config: dict) -> dict:
    _object(config, "orchestration config", {"schema_version", "profile_file", "fixture_file",
                                             "baseline", "models", "limits", "verifier_image"})
    if config["schema_version"] != SCHEMA_VERSION or type(config["schema_version"]) is not int:
        fail("invalid_field", "schema_version must be integer 1.", "Use the supported schema version.")
    for name in ("profile_file", "fixture_file"):
        _child(Path.cwd(), config[name], name)
    if config["verifier_image"] != VERIFIER_IMAGE:
        fail("invalid_field", "verifier_image must be the pinned supported image digest.",
             "Use the documented verifier image; upgrades require a reviewed code change.")
    _object(config["baseline"], "baseline", {"simple", "complex"})
    for key in ("simple", "complex"):
        if config["baseline"][key] not in ROUTES:
            fail("invalid_field", f"baseline.{key} must name fast or strong.", "Correct the route mapping.")
    _object(config["models"], "models", set(ROUTES))
    for route in ROUTES:
        spec = config["models"][route]
        _object(spec, f"models.{route}", {"id", "provider_model", "hf_repo", "hf_revision",
                                           "endpoint", "data_classes", "max_output_tokens", "timeout_seconds"})
        _text(spec["id"], f"models.{route}.id", 64)
        if not _SAFE_ID.fullmatch(spec["id"]):
            fail("invalid_field", f"models.{route}.id is invalid.", "Use a stable safe model ID.")
        _text(spec["provider_model"], f"models.{route}.provider_model", 200)
        _text(spec["hf_repo"], f"models.{route}.hf_repo", 200)
        if type(spec["hf_revision"]) is not str or not _COMMIT.fullmatch(spec["hf_revision"]):
            fail("invalid_field", f"models.{route}.hf_revision must be a full pinned commit.",
                 "Pin the Hugging Face model snapshot to a 40-character commit SHA.")
        local_model._loopback_url(spec["endpoint"])
        if (type(spec["data_classes"]) is not list or not spec["data_classes"] or
                any(type(item) is not str or item not in ("public", "local")
                    for item in spec["data_classes"]) or
                len(set(spec["data_classes"])) != len(spec["data_classes"])):
            fail("invalid_field", f"models.{route}.data_classes is invalid.",
                 "Use distinct public/local data classes.")
        _integer(spec["max_output_tokens"], f"models.{route}.max_output_tokens", 1, 4096)
        _integer(spec["timeout_seconds"], f"models.{route}.timeout_seconds", 1, 120)
    if config["models"]["fast"]["id"] == config["models"]["strong"]["id"]:
        fail("invalid_field", "Model registrations must have distinct IDs.", "Register two distinct models.")
    limits = config["limits"]
    _object(limits, "limits", {"max_checkout_bytes", "max_checkout_files", "max_patch_bytes",
                                "max_evidence_bytes", "max_eval_seconds"})
    for name, high in (("max_checkout_bytes", MAX_CHECKOUT_BYTES),
                       ("max_checkout_files", MAX_CHECKOUT_FILES),
                       ("max_patch_bytes", MAX_PATCH_BYTES),
                       ("max_evidence_bytes", MAX_EVIDENCE_BYTES),
                       ("max_eval_seconds", 120)):
        _integer(limits[name], f"limits.{name}", 1, high)
    return config


def validate_task(task: dict, base: Path) -> dict:
    _object(task, "task", {"schema_version", "id", "objective", "approved_summary",
                            "data_class", "jev_egress_approved", "complexity", "source_repo",
                            "base_commit", "allowed_files", "evaluator_file", "evaluator_sha256"})
    if type(task["schema_version"]) is not int or task["schema_version"] != SCHEMA_VERSION:
        fail("invalid_field", "task.schema_version must be integer 1.", "Use schema version 1.")
    _text(task["id"], "task.id", 64)
    if not _SAFE_ID.fullmatch(task["id"]):
        fail("invalid_field", "task.id is invalid.", "Use a stable safe task ID.")
    _text(task["objective"], "task.objective", 2_000)
    _text(task["approved_summary"], "task.approved_summary", 800)
    if task["data_class"] not in ("public", "local"):
        fail("invalid_field", "task.data_class must be public or local.", "Classify the task input.")
    if type(task["jev_egress_approved"]) is not bool:
        fail("invalid_field", "task.jev_egress_approved must be boolean.", "Set true or false.")
    if task["complexity"] not in ("simple", "complex"):
        fail("invalid_field", "task.complexity must be simple or complex.", "Choose the task class.")
    _child(base, task["source_repo"], "task.source_repo")
    _child(base, task["evaluator_file"], "task.evaluator_file")
    if type(task["base_commit"]) is not str or not _COMMIT.fullmatch(task["base_commit"]):
        fail("invalid_field", "task.base_commit must be a full Git commit SHA.", "Pin the base commit.")
    if type(task["evaluator_sha256"]) is not str or not _SHA256.fullmatch(task["evaluator_sha256"]):
        fail("invalid_field", "task.evaluator_sha256 must be a SHA-256 digest.", "Hash the trusted evaluator file.")
    files = task["allowed_files"]
    if (type(files) is not list or not 1 <= len(files) <= 4 or
            any(type(name) is not str for name in files) or len(set(files)) != len(files)):
        fail("invalid_field", "task.allowed_files must contain 1..4 distinct paths.", "Declare bounded writable files.")
    for name in files:
        _child(base, name, "task.allowed_files entry")
    return task


def load_state(directory: Path):
    directory = directory.resolve()
    config = validate_config(load_json(directory / "orchestration.json"))
    pins = load_model_pins()
    for route in ROUTES:
        for name in ("id", "provider_model", "hf_repo", "hf_revision"):
            if config["models"][route][name] != pins["models"][route][name]:
                fail("model_pin_mismatch", f"models.{route}.{name} differs from model-pins.json.",
                     "Reinitialize a task or deliberately update the canonical model registry.")
    task = validate_task(load_json(directory / "task.json"), directory)
    profile_path = _child(directory, config["profile_file"], "profile_file")
    profile = jev.validate_config(jev.load_json(profile_path))
    if set(profile["question"]["criteria"]) != {"fast", "strong", "unclear"}:
        fail("invalid_profile", "The route profile must use fast, strong, and unclear labels.",
             "Restore the versioned coding-route profile.")
    if "unclear" not in profile["policy"]["review_labels"]:
        fail("invalid_profile", "The unclear label must require review.", "Add unclear to review_labels.")
    repo = _child(directory, task["source_repo"], "task.source_repo")
    evaluator = _child(directory, task["evaluator_file"], "task.evaluator_file")
    if evaluator.is_relative_to(repo):
        fail("invalid_field", "task.evaluator_file must be outside the model-writable source tree.",
             "Place evaluator code in a separate protected directory.")
    if not repo.is_dir() or not evaluator.is_file() or file_hash(evaluator) != task["evaluator_sha256"]:
        fail("task_integrity_failed", "The source repository or trusted evaluator is missing or changed.",
             "Restore the pinned source and evaluator before running.")
    return directory, config, task, profile, repo, evaluator


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                                text=True, timeout=30, check=False, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OrchestrationError("git_failed", "The bounded Git command could not run.",
                                 "Install Git and check the fixture repository.") from exc
    if result.returncode != 0:
        fail("git_failed", "The bounded Git command failed.", "Inspect the repository and pinned base commit.")
    return result.stdout.strip()


def _verify_base(repo: Path, commit: str) -> None:
    if _git(repo, "rev-parse", "HEAD") != commit:
        fail("base_changed", "The repository HEAD differs from task.base_commit.",
             "Create a new task manifest for the intended base commit.")
    if _git(repo, "status", "--porcelain"):
        fail("dirty_source", "The task source repository has uncommitted changes.",
             "Use a clean pinned base or create a separate task source.")


def _archive_bytes(repo: Path, commit: str, max_bytes: int) -> bytes:
    try:
        with subprocess.Popen(["git", "-C", str(repo), "-c", "core.autocrlf=false",
                               "archive", "--format=tar", commit],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
            assert process.stdout is not None
            raw = process.stdout.read(max_bytes + 1)
            if len(raw) > max_bytes:
                process.kill()
                process.wait(timeout=5)
                fail("checkout_too_large", "The base archive exceeds limits.max_checkout_bytes.",
                     "Reduce the task source or raise the setting within its bound.")
            if process.wait(timeout=30) != 0:
                fail("git_failed", "The pinned base archive could not be produced.", "Inspect the base commit.")
            return raw
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OrchestrationError("git_failed", "The pinned base archive could not be produced.",
                                 "Inspect Git and the repository.") from exc


def _materialize(archive: bytes, destination: Path, max_files: int) -> None:
    destination.mkdir(exist_ok=False)
    count = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            for member in bundle:
                path = PurePosixPath(member.name)
                if (path.is_absolute() or any(part in ("", ".", "..") for part in path.parts)
                        or not (member.isfile() or member.isdir())):
                    fail("invalid_archive", "The base archive contains an unsafe entry.",
                         "Use a source repository with regular files and directories only.")
                target = destination.joinpath(*path.parts)
                if not target.resolve().is_relative_to(destination.resolve()):
                    fail("invalid_archive", "The base archive entry escapes its checkout.",
                         "Inspect the source repository.")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                count += 1
                if count > max_files:
                    fail("checkout_too_large", "The base archive has too many files.",
                         "Reduce task scope or adjust limits.max_checkout_files.")
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    fail("invalid_archive", "An archive file could not be read.", "Inspect the base commit.")
                with target.open("xb") as output:
                    shutil.copyfileobj(source, output)
    except (tarfile.TarError, OSError) as exc:
        raise OrchestrationError("invalid_archive", "The base archive could not be materialized.",
                                 "Inspect the pinned source commit and partial checkout.") from exc


def _tree_hash(root: Path) -> str:
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            entries.append([path.relative_to(root).as_posix(), file_hash(path)])
    return digest(entries)


class RunLedger:
    def __init__(self, run_dir: Path):
        self.path = run_dir / "events.jsonl"
        try:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            self.stream = os.fdopen(descriptor, "ab")
        except OSError as exc:
            error = OrchestrationError("audit_failed", "The run ledger could not be created.",
                                       "Inspect the partial run and storage permissions.")
            error.run_dir = str(run_dir)
            raise error from exc

    def add(self, event: str, **fields) -> None:
        record = {"event": event, "time_unix_ms": time.time_ns() // 1_000_000, **fields}
        try:
            self.stream.write(canonical_bytes(record) + b"\n")
            self.stream.flush()
            os.fsync(self.stream.fileno())
        except OSError as exc:
            error = OrchestrationError("audit_failed", "A run event could not be persisted.",
                                       "Inspect the incomplete run and restore writable storage.")
            error.run_dir = str(self.path.parent)
            raise error from exc

    def close(self) -> None:
        try:
            self.stream.close()
        except OSError as exc:
            error = OrchestrationError("audit_failed", "The run ledger could not be closed safely.",
                                       "Inspect the incomplete run and storage health.")
            error.run_dir = str(self.path.parent)
            raise error from exc


def _eligible(config: dict, task: dict) -> list[str]:
    return [route for route in ROUTES if task["data_class"] in config["models"][route]["data_classes"]]


def _validate_run_modes(mode: str, jev_mode: str, route_source: str, dotenv: str | None = None) -> None:
    if (mode not in ("fixture", "live") or jev_mode not in ("off", "fixture", "live")
            or route_source not in ("baseline", "jev")):
        fail("invalid_arguments", "An execution mode or route source is unsupported.",
             "Choose fixture/live coding, off/fixture/live Jev, and baseline/jev routing.")
    if route_source == "jev" and jev_mode == "off":
        fail("invalid_arguments", "Jev cannot own a route when Jev mode is off.",
             "Enable a bounded Jev mode or choose baseline routing.")
    if dotenv is not None and jev_mode != "live":
        fail("invalid_arguments", "--dotenv is only valid with live Jev mode.",
             "Remove --dotenv or select live Jev mode.")


def _scope(directory: Path, config: dict, task: dict, mode: str, jev_mode: str,
           route_source: str) -> dict:
    eligible = _eligible(config, task)
    return {"task_id": task["id"], "source_repo": str(_child(directory, task["source_repo"], "task.source_repo")),
            "base_commit": task["base_commit"], "allowed_files": task["allowed_files"],
            "evaluator": task["evaluator_file"], "data_class": task["data_class"],
            "route_source": route_source, "jev_mode": jev_mode, "coding_mode": mode,
            "eligible_routes": eligible,
            "provider_destinations": (["https://api.typesafe.ai/v1/systemone"] if jev_mode == "live" else [])
                + ([config["models"][route]["endpoint"] for route in eligible] if mode == "live" else []),
            "maximum_calls": {"jev": 0 if jev_mode == "off" else 1,
                              "coding": 1, "verifier": 1}, "limits": config["limits"]}


def dry_run(directory: Path, mode: str, jev_mode: str, route_source: str) -> dict:
    _validate_run_modes(mode, jev_mode, route_source)
    base, config, task, _profile, repo, _evaluator = load_state(directory)
    _verify_base(repo, task["base_commit"])
    return {"status": "dry_run", "effects": _scope(base, config, task, mode, jev_mode, route_source),
            "notice": "No model, Git checkout, tool, or provider call was made."}


def _route_packet(task: dict, eligible: list[str]) -> dict:
    return {"approved_summary": task["approved_summary"], "complexity": task["complexity"],
            "eligible_routes": eligible, "data_class": task["data_class"]}


def _jev_decision(directory: Path, profile: dict, task: dict, eligible: list[str],
                  jev_mode: str, dotenv: str | None) -> dict:
    if jev_mode == "live":
        if task["data_class"] != "public" or not task["jev_egress_approved"]:
            fail("jev_egress_denied", "This task does not approve the public summary for Jev egress.",
                 "Use fixture mode or approve and classify the exact summary before retrying.")
        if _SECRET_HINT.search(task["approved_summary"]):
            fail("jev_egress_denied", "The approved summary resembles a credential.",
                 "Remove secret-bearing text before Jev egress.")
    packet = _route_packet(task, eligible)
    prior = os.environ.get(profile["api_key_env"])
    if dotenv is not None:
        if jev_mode != "live":
            fail("invalid_arguments", "--dotenv is only valid with live Jev mode.",
                 "Remove --dotenv or select live Jev mode.")
        os.environ[profile["api_key_env"]] = read_key(dotenv, profile["api_key_env"])
    try:
        result = jev.run_one(profile, directory, {"id": task["id"], "state": packet}, jev_mode)
    finally:
        if dotenv is not None:
            if prior is None:
                os.environ.pop(profile["api_key_env"], None)
            else:
                os.environ[profile["api_key_env"]] = prior
    return {"decision": result["decision"], "audit_path": result["audit_path"],
            "request_hash": result["request_hash"], "response_hash": result["response_hash"]}


def _route(config: dict, task: dict, eligible: list[str], decision: dict | None, source: str) -> str:
    if source == "baseline":
        route = config["baseline"][task["complexity"]]
    else:
        if decision is None:
            fail("invalid_record", "A Jev-owned route has no decision.",
                 "Inspect the Jev audit and route record.")
        if decision["status"] != "accept":
            fail("review_required", "Jev did not accept a bounded route.",
                 "Inspect its audit and resolve the route in a new run.")
        route = decision["label"]
    if route not in eligible:
        fail("review_required", "The selected route is ineligible for this task.",
             "Choose a registered eligible route in a new reviewed run.")
    return route


def _prompt(task: dict, checkout: Path, max_bytes: int) -> list[dict]:
    inputs = []
    for name in task["allowed_files"]:
        path = _child(checkout, name, "allowed file")
        if not path.is_file() or path.is_symlink():
            fail("invalid_source", "An allowed source file is absent or not regular.",
                 "Correct the task manifest or pinned base commit.")
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise OrchestrationError("invalid_source", "An allowed source file is not readable UTF-8 text.",
                                     "Use a text source file for this bounded experiment.") from exc
        inputs.append({"path": name, "content": content})
    body = {"objective": task["objective"], "files": inputs,
            "allowed_paths": task["allowed_files"]}
    if len(canonical_bytes(body)) > max_bytes:
        fail("prompt_too_large", "The coding input exceeds limits.max_patch_bytes.",
             "Reduce the task source or adjust the configured bound.")
    return [
        {"role": "system", "content": "You edit only the listed files. Return only one JSON object: {\"files\":[{\"path\":\"allowed/path\",\"content\":\"full UTF-8 file text\"}]}. Do not include Markdown, commentary, commands, or other keys."},
        {"role": "user", "content": json.dumps(body, ensure_ascii=False, sort_keys=True)},
    ]


def _patch_response_format(task: dict) -> dict:
    """Ask OVMS to constrain the next response; _parse_patch remains authoritative."""
    return {"type": "json_schema", "json_schema": {"schema": {
        "type": "object", "properties": {"files": {
            "type": "array", "items": {"type": "object", "properties": {
                "path": {"type": "string", "enum": task["allowed_files"]},
                "content": {"type": "string"}},
                "required": ["path", "content"], "additionalProperties": False}}},
        "required": ["files"], "additionalProperties": False}}}


def _parse_patch(content: str, task: dict, max_bytes: int) -> list[dict]:
    if type(content) is not str or len(content.encode("utf-8")) > max_bytes:
        fail("invalid_patch", "The model patch exceeds limits.max_patch_bytes.",
             "Reduce the requested edit or increase the bound within its code range.")
    try:
        patch = json.loads(content, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise OrchestrationError("invalid_patch", "The model did not return strict JSON file content.",
                                 "Inspect the protected model output and start a new bounded run.") from exc
    _object(patch, "model patch", {"files"})
    files = patch["files"]
    if type(files) is not list or not 1 <= len(files) <= len(task["allowed_files"]):
        fail("invalid_patch", "The patch must contain a bounded nonempty files list.",
             "Return only declared file edits.")
    paths = []
    for row in files:
        _object(row, "patch file", {"path", "content"})
        if row["path"] not in task["allowed_files"] or row["path"] in paths:
            fail("invalid_patch", "The patch names a duplicate or undeclared path.",
                 "Return only distinct allowed file paths.")
        if type(row["content"]) is not str or not row["content"]:
            fail("invalid_patch", "A patch file has empty or non-text content.",
                 "Return full nonempty UTF-8 file text.")
        paths.append(row["path"])
    return files


def _apply_patch(checkout: Path, files: list[dict]) -> dict:
    before = {}
    after = {}
    for row in files:
        path = _child(checkout, row["path"], "patch path")
        if not path.is_file() or path.is_symlink():
            fail("invalid_patch", "The patch target is not an existing regular file.",
                 "Edit a declared source file from the pinned base.")
        before[row["path"]] = file_hash(path)
    for row in files:
        path = _child(checkout, row["path"], "patch path")
        temporary = path.with_name(path.name + ".jev-new")
        if temporary.exists():
            fail("write_failed", "A temporary patch path already exists.",
                 "Inspect the isolated checkout before retrying.")
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(row["content"])
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        after[row["path"]] = file_hash(path)
    return {"before": before, "after": after}


def _verify_docker(checkout: Path, evaluator: Path, image: str, timeout: int,
                   max_bytes: int, run_dir: Path) -> dict:
    name = "jev-verify-" + run_dir.name.replace("_", "-")
    stdout_path = run_dir / "verifier.stdout"
    stderr_path = run_dir / "verifier.stderr"
    command = ["docker", "run", "--rm", "--pull", "never", "--name", name,
               "--network", "none", "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--pids-limit", "64",
               "--memory", "256m", "--cpus", "1", "--user", "65534:65534",
               "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
               "--mount", f"type=bind,source={checkout},target=/work,readonly",
               "--mount", f"type=bind,source={evaluator.parent},target=/eval,readonly",
               "--workdir", "/work", image, "python", "-B", f"/eval/{evaluator.name}", "/work"]
    start = time.monotonic()
    with stdout_path.open("xb") as out, stderr_path.open("xb") as err:
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,
                                       env={"PATH": os.environ.get("PATH", ""),
                                            "SystemRoot": os.environ.get("SystemRoot", "C:\\Windows")})
        except OSError as exc:
            raise OrchestrationError("verifier_unavailable", "Docker could not start the verifier.",
                                     "Start Docker and install the pinned verifier image.") from exc
        output_bytes = 0
        output_lock = threading.Lock()
        output_limit = threading.Event()
        reader_failure = threading.Event()

        def copy_bounded(source, destination):
            nonlocal output_bytes
            try:
                with source:
                    while chunk := source.read(4_096):
                        with output_lock:
                            remaining = max_bytes - output_bytes
                            portion = chunk[:remaining]
                            if portion:
                                destination.write(portion)
                                output_bytes += len(portion)
                            if len(chunk) > remaining:
                                output_limit.set()
                                return
            except OSError:
                reader_failure.set()

        assert process.stdout is not None and process.stderr is not None
        readers = [threading.Thread(target=copy_bounded, args=(process.stdout, out), daemon=True),
                   threading.Thread(target=copy_bounded, args=(process.stderr, err), daemon=True)]
        for reader in readers:
            reader.start()
        failure = None
        while process.poll() is None:
            if time.monotonic() - start > timeout:
                failure = "verifier_timeout"
                break
            if output_limit.is_set():
                failure = "verifier_output_limit"
                break
            if reader_failure.is_set():
                failure = "verifier_io_failed"
                break
            time.sleep(0.05)
        if failure:
            try:
                subprocess.run(["docker", "kill", name], capture_output=True,
                               timeout=10, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                fail("verifier_stop_failed", "The verifier process could not be stopped promptly.",
                     "Inspect the named Docker container and partial run before retrying.")
        else:
            process.wait(timeout=10)
        for reader in readers:
            reader.join(timeout=10)
        if any(reader.is_alive() for reader in readers):
            fail("verifier_io_failed", "A verifier output reader did not finish.",
                 "Inspect the Docker process and partial evidence before retrying.")
        if output_limit.is_set():
            failure = "verifier_output_limit"
        if reader_failure.is_set():
            failure = "verifier_io_failed"
        if failure:
            fail(failure, "The trusted verifier exceeded a time/output bound or could not record output.",
                 "Inspect the restricted verifier evidence and reduce task scope.")
        exit_code = process.returncode
    if output_bytes > max_bytes:
        fail("verifier_output_limit", "The trusted verifier exceeded its output limit.",
             "Inspect the restricted verifier evidence and reduce task scope.")
    return {"command": command, "exit_code": exit_code,
            "stdout_path": str(stdout_path), "stderr_path": str(stderr_path),
            "stdout_sha256": file_hash(stdout_path), "stderr_sha256": file_hash(stderr_path),
            "elapsed_ms": round((time.monotonic() - start) * 1000)}


def _trusted_verdict(path: Path) -> dict:
    try:
        verdict = load_json(path, 1_024)
    except OrchestrationError:
        fail("checks_incomplete", "The verifier exited zero without a trusted test verdict.",
             "Inspect the unedited verifier output; fix the evaluator and start a new run.")
    if (type(verdict) is not dict or set(verdict) !=
            {"schema_version", "tests_run", "failures", "errors"} or
            type(verdict["schema_version"]) is not int or verdict["schema_version"] != 1 or
            type(verdict["tests_run"]) is not int or not 1 <= verdict["tests_run"] <= 1_000 or
            type(verdict["failures"]) is not int or verdict["failures"] != 0 or
            type(verdict["errors"]) is not int or verdict["errors"] != 0):
        fail("checks_incomplete", "The verifier verdict does not prove successful test execution.",
             "Inspect the trusted evaluator and its unedited output; start a new run.")
    return verdict


def run(directory: Path, mode: str, jev_mode: str, route_source: str,
        dotenv: str | None, watch: bool, experimental_jev_route: bool) -> dict:
    _validate_run_modes(mode, jev_mode, route_source, dotenv)
    base, config, task, profile, repo, evaluator = load_state(directory)
    _verify_base(repo, task["base_commit"])
    eligible = _eligible(config, task)
    if not eligible:
        fail("no_eligible_model", "No registered model is eligible for the task data class.",
             "Update validated registration or task scope before running.")
    if route_source == "jev" and mode == "live" and not experimental_jev_route:
        fail("promotion_required", "Live Jev control requires explicit experimental scope or promotion evidence.",
             "Use baseline routing or --experimental-jev-route with --watch for one sandboxed task.")
    if mode == "live" or jev_mode == "live":
        if not watch or not sys.stdin.isatty():
            fail("watch_required", "A live first-run experiment requires an interactive --watch terminal.",
                 "Run one task with --watch in a terminal and inspect the displayed scope.")
        print(json.dumps(_scope(base, config, task, mode, jev_mode, route_source),
                         ensure_ascii=False, sort_keys=True), file=sys.stderr)
        print("Run exactly this one bounded task? Type yes: ", end="", file=sys.stderr, flush=True)
        if input().strip() != "yes":
            fail("operator_declined", "The operator declined the displayed task scope.",
                 "Run dry-run, revise configuration, and retry deliberately.")
    runs = base / "runs"
    runs.mkdir(exist_ok=True)
    run_dir = runs / str(uuid.uuid4())
    run_dir.mkdir(exist_ok=False)
    ledger = RunLedger(run_dir)
    try:
        write_new(run_dir / "config.snapshot.json", config)
        write_new(run_dir / "task.snapshot.json", task)
        ledger.add("started", task_id=task["id"], mode=mode, jev_mode=jev_mode,
                   route_source=route_source, config_hash=digest(config), task_hash=digest(task))
        try:
            evaluator_snapshot = run_dir / "trusted-evaluator" / evaluator.name
            snapshot_evaluator(evaluator, evaluator_snapshot, task["evaluator_sha256"],
                               config["limits"]["max_checkout_bytes"])
            ledger.add("evaluator_snapshotted", evaluator_sha256=task["evaluator_sha256"],
                       path=str(evaluator_snapshot))
            jev_result = (_jev_decision(base, profile, task, eligible, jev_mode, dotenv)
                          if jev_mode != "off" else
                          {"decision": None, "audit_path": None,
                           "request_hash": None, "response_hash": None})
            route = _route(config, task, eligible, jev_result["decision"], route_source)
            ledger.add("routed", selected_route=route, source=route_source,
                       baseline_rule=task["complexity"] if route_source == "baseline" else None,
                       jev_decision=jev_result["decision"], jev_audit_path=jev_result["audit_path"],
                       jev_request_hash=jev_result["request_hash"],
                       jev_response_hash=jev_result["response_hash"], eligible_routes=eligible)
            archive = _archive_bytes(repo, task["base_commit"], config["limits"]["max_checkout_bytes"])
            checkout = run_dir / "checkout"
            scratch = run_dir / "restore-proof"
            _materialize(archive, checkout, config["limits"]["max_checkout_files"])
            _materialize(archive, scratch, config["limits"]["max_checkout_files"])
            original_hash = _tree_hash(checkout)
            if _tree_hash(scratch) != original_hash:
                fail("restore_failed", "Scratch regeneration did not match the isolated base.",
                     "Do not write; inspect the base archive and restore proof.")
            ledger.add("restore_proven", base_tree_sha256=original_hash,
                       checkout=str(checkout), scratch=str(scratch))
            if mode == "fixture":
                fixtures = load_json(_child(base, config["fixture_file"], "fixture_file"))
                _object(fixtures, "coding fixtures", set(ROUTES))
                content = json.dumps(fixtures[route], ensure_ascii=False, sort_keys=True)
                model_result = {"model": "fixture-" + route, "content": content,
                                "usage": None, "source": "synthetic_fixture"}
            else:
                spec = config["models"][route]
                messages = _prompt(task, checkout, config["limits"]["max_patch_bytes"])
                response = local_model.chat_completion(spec["endpoint"], spec["provider_model"],
                                                       messages, spec["max_output_tokens"],
                                                       spec["timeout_seconds"],
                                                       response_format=_patch_response_format(task))
                model_result = {**response, "source": "local_ovms"}
            write_new(run_dir / "model-output.json", model_result)
            ledger.add("model_completed", route=route, model=model_result["model"],
                       source=model_result["source"], usage=model_result["usage"],
                       output_sha256=file_hash(run_dir / "model-output.json"))
            files = _parse_patch(model_result["content"], task, config["limits"]["max_patch_bytes"])
            hashes = _apply_patch(checkout, files)
            artifact = {"base_commit": task["base_commit"], "files": files, "hashes": hashes,
                        "route": route, "model": model_result["model"]}
            write_new(run_dir / "patch.json", artifact)
            ledger.add("patch_applied", patch_sha256=file_hash(run_dir / "patch.json"),
                       files=hashes)
            if file_hash(evaluator) != task["evaluator_sha256"]:
                fail("evaluator_changed", "The trusted evaluator changed during the run.",
                     "Restore the evaluator and start a new run.")
            verification = _verify_docker(checkout, evaluator_snapshot, config["verifier_image"],
                                          config["limits"]["max_eval_seconds"],
                                          config["limits"]["max_evidence_bytes"], run_dir)
            verification["verdict"] = (_trusted_verdict(Path(verification["stdout_path"]))
                                       if verification["exit_code"] == 0 else None)
            write_new(run_dir / "verification.json", verification)
            ledger.add("verified", **verification, evaluator_sha256=task["evaluator_sha256"])
            if verification["exit_code"] != 0:
                fail("checks_failed", "The trusted evaluator did not pass.",
                     "Inspect the unedited verifier output and start a new bounded repair run.")
            ledger.add("completed", verified_completion=True, route=route,
                       model=model_result["model"], verification_path=str(run_dir / "verification.json"))
            return {"status": "completed", "run_dir": str(run_dir), "route": route,
                    "model": model_result["model"], "verified_completion": True,
                    "verification_path": str(run_dir / "verification.json"),
                    "jev_audit_path": jev_result["audit_path"]}
        except (jev.HarnessError, local_model.LocalModelError) as exc:
            error = OrchestrationError(exc.code, exc.message, exc.next_action)
            error.run_dir = str(run_dir)
            ledger.add("failed", error=error.report())
            raise error from None
        except OrchestrationError as exc:
            exc.run_dir = str(run_dir)
            ledger.add("review_required" if exc.code == "review_required" else "failed",
                       error=exc.report())
            raise
    except OrchestrationError as exc:
        if exc.run_dir is None:
            exc.run_dir = str(run_dir)
            ledger.add("failed", error=exc.report())
        raise
    except Exception:
        error = OrchestrationError("internal_error", "An unexpected orchestration failure occurred.",
                                   "Inspect the partial run and report the failing command without credentials.")
        error.run_dir = str(run_dir)
        ledger.add("failed", error=error.report())
        raise error from None
    finally:
        ledger.close()


def initialize(directory: Path, fast_endpoint: str,
               strong_endpoint: str = "http://127.0.0.1:8001/v1/chat/completions",
               fixture_complexity: str = "simple") -> dict:
    directory = directory.resolve()
    local_model._loopback_url(fast_endpoint)
    local_model._loopback_url(strong_endpoint)
    pins = load_model_pins()
    if fixture_complexity not in ("simple", "complex"):
        fail("invalid_field", "fixture_complexity must be simple or complex.",
             "Choose one documented fixture route class.")
    if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
        fail("init_target_not_empty", "The initialization directory must be absent or empty.",
             "Choose a fresh directory; init never replaces existing files.")
    directory.mkdir(parents=True, exist_ok=True)
    repo = directory / "fixture-repo"
    repo.mkdir(exist_ok=False)
    return_contract = "contract_error = None\n"
    if fixture_complexity == "complex":
        task_id = "fixture-merge-intervals"
        objective = ("Implement merge_intervals(intervals). Each interval is a pair of integers "
                     "(start, end) with start <= end. Return a sorted list of tuple intervals, "
                     "merging overlaps and intervals whose endpoints touch. Do not mutate the input.")
        summary = "Single Python interval merge function with seven independent edge-case checks."
        return_contract += (
            "if type(value) is not list:\n"
            "    contract_error = 'return_list'\n"
            "elif any(type(pair) is not tuple or len(pair) != 2 for pair in value):\n"
            "    contract_error = 'tuple_pair'\n"
            "elif any(type(endpoint) is not int for pair in value for endpoint in pair):\n"
            "    contract_error = 'integer_endpoints'\n")
        source_text = "def merge_intervals(intervals):\n    raise NotImplementedError\n"
        solution_text = ("def merge_intervals(intervals):\n"
                         "    ordered = sorted(intervals)\n"
                         "    merged = []\n"
                         "    for start, end in ordered:\n"
                         "        if merged and start <= merged[-1][1]:\n"
                         "            left, right = merged[-1]\n"
                         "            merged[-1] = (left, max(right, end))\n"
                         "        else:\n"
                         "            merged.append((start, end))\n"
                         "    return merged\n")
        tests = (
            "    def test_empty(self): self.assertEqual(invoke([])[0], [])\n"
            "    def test_single_interval(self): self.assertEqual(invoke([[1, 2]])[0], [[1, 2]])\n"
            "    def test_unsorted(self): self.assertEqual(invoke([[5, 7], [1, 3], [2, 6]])[0], [[1, 7]])\n"
            "    def test_touching(self): self.assertEqual(invoke([[1, 3], [3, 5]])[0], [[1, 5]])\n"
            "    def test_contained(self): self.assertEqual(invoke([[1, 8], [3, 5]])[0], [[1, 8]])\n"
            "    def test_disjoint(self): self.assertEqual(invoke([[5, 6], [1, 2]])[0], [[1, 2], [5, 6]])\n"
            "    def test_unmodified(self):\n"
            "        items = [[3, 5], [1, 2]]\n"
            "        self.assertEqual(invoke(items)[1], [items])\n")
        function_name = "merge_intervals"
        route_label = "strong"
        probabilities = {"fast": 0.05, "strong": 0.91, "unclear": 0.04}
    else:
        task_id = "fixture-add"
        objective = "Implement add(a, b) so it returns the arithmetic sum of two integers."
        summary = "Small Python function edit with three independent arithmetic checks."
        source_text = "def add(a, b):\n    raise NotImplementedError\n"
        solution_text = "def add(a, b):\n    return a + b\n"
        tests = (
            "    def test_positive(self): self.assertEqual(invoke(2, 3)[0], 5)\n"
            "    def test_negative(self): self.assertEqual(invoke(-5, 2)[0], -3)\n"
            "    def test_zero(self): self.assertEqual(invoke(0, 0)[0], 0)\n")
        function_name = "add"
        route_label = "fast"
        probabilities = {"fast": 0.91, "strong": 0.05, "unclear": 0.04}
    (repo / "solution.py").write_bytes(source_text.encode("utf-8"))
    fixture_env = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith("GIT_")}
    fixture_env.update({"GIT_AUTHOR_NAME": "Jev Fixture",
                        "GIT_AUTHOR_EMAIL": "fixture@invalid.example",
                        "GIT_COMMITTER_NAME": "Jev Fixture",
                        "GIT_COMMITTER_EMAIL": "fixture@invalid.example",
                        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+0000",
                        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+0000",
                        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    _git(repo, "init", "-q", "--object-format=sha1", env=fixture_env)
    _git(repo, "-c", "core.autocrlf=false", "add", "--", "solution.py", env=fixture_env)
    _git(repo, "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false",
         "-c", "core.hooksPath=.", "commit", "-qm", "Pinned fixture base", env=fixture_env)
    commit = _git(repo, "rev-parse", "HEAD")
    evaluator = directory / "evaluator" / "test_solution.py"
    evaluator.parent.mkdir(exist_ok=False)
    child = (
        "import importlib.util, json, pathlib, sys\n"
        "root = pathlib.Path(sys.argv[1])\n"
        "spec = importlib.util.spec_from_file_location('solution', root / 'solution.py')\n"
        "solution = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(solution)\n"
        "args = json.load(sys.stdin)\n"
        "value = getattr(solution, sys.argv[2])(*args)\n"
        + return_contract +
        "if contract_error is not None:\n"
        "    sys.stdout.write(json.dumps({'contract_error': contract_error}))\n"
        "else:\n"
        "    sys.stdout.write(json.dumps({'value': value, 'args_after': args}))\n")
    evaluator.write_text(
        "import json, pathlib, subprocess, sys, unittest\n"
        "root = pathlib.Path(sys.argv[1])\n"
        + f"CHILD = {child!r}\n"
        + f"FUNCTION = {function_name!r}\n"
        + "def invoke(*args):\n"
        "    result = subprocess.run([sys.executable, '-B', '-c', CHILD, str(root), FUNCTION],\n"
        "                            input=json.dumps(args), capture_output=True, text=True,\n"
        "                            timeout=5, check=False, cwd=root)\n"
        "    if result.returncode != 0:\n"
        "        raise AssertionError('candidate subprocess exited before returning')\n"
        "    try:\n"
        "        payload = json.loads(result.stdout)\n"
        "    except ValueError as exc:\n"
        "        raise AssertionError('candidate subprocess did not return JSON') from exc\n"
        "    if type(payload) is dict and set(payload) == {'contract_error'}:\n"
        "        messages = {\n"
        "            'return_list': 'merge_intervals must return a list',\n"
        "            'tuple_pair': 'each interval must be a two-element tuple',\n"
        "            'integer_endpoints': 'each interval must have integer endpoints'}\n"
        "        error = payload['contract_error']\n"
        "        if type(error) is str and error in messages:\n"
        "            raise AssertionError(messages[error])\n"
        "    if type(payload) is not dict or set(payload) != {'value', 'args_after'}:\n"
        "        raise AssertionError('candidate subprocess returned an invalid result')\n"
        "    return payload['value'], payload['args_after']\n"
        "class Acceptance(unittest.TestCase):\n"
        + tests +
        "result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(\n"
        "    unittest.defaultTestLoader.loadTestsFromTestCase(Acceptance))\n"
        "print(json.dumps({'schema_version': 1, 'tests_run': result.testsRun,\n"
        "                  'failures': len(result.failures), 'errors': len(result.errors)},\n"
        "                 sort_keys=True), flush=True)\n"
        "sys.exit(0 if result.wasSuccessful() and result.testsRun > 0 else 1)\n",
        encoding="utf-8")
    task = {"schema_version": 1, "id": task_id, "objective": objective,
            "approved_summary": summary,
            "data_class": "public", "jev_egress_approved": True, "complexity": fixture_complexity,
            "source_repo": "fixture-repo", "base_commit": commit,
            "allowed_files": ["solution.py"], "evaluator_file": "evaluator/test_solution.py",
            "evaluator_sha256": file_hash(evaluator)}
    profile = {"schema_version": 1, "endpoint": "https://api.typesafe.ai/v1/systemone",
               "model": "jev-1.13.0", "api_key_env": "JEV_API_KEY", "timeout_seconds": 30,
               "max_input_bytes": 8_000, "audit_dir": "jev-audit", "fixture_file": "route-fixtures.json",
               "question": {"id": "coding_route",
                            "instructions": "Choose the next coding model for one bounded task. Select fast for a straightforward local edit, strong for a difficult coding task, and unclear when the route is uncertain. The eligible_routes field is authoritative; do not select an ineligible route.",
                            "criteria": {"fast": "A straightforward, narrow coding edit suitable for the smaller local coding model.",
                                         "strong": "A difficult coding task that needs the larger local coding model.",
                                         "unclear": "The task is ambiguous, out of scope, or the suitable route is uncertain."}},
               "policy": {"min_probability": 0.65, "min_margin": 0.1, "review_labels": ["unclear"]}}
    route_fixture = {"model": "jev-1.13.0", "answers": {"coding_route": {
        "type": "choice", "choice": route_label, "probabilities": probabilities,
        "confidence": 0.84}}, "usage": {"input_tokens": 0, "output_tokens": 0}}
    config = {"schema_version": 1, "profile_file": "route-profile.json", "fixture_file": "coding-fixtures.json",
              "baseline": {"simple": "fast", "complex": "strong"}, "verifier_image": VERIFIER_IMAGE,
              "models": {route: {"id": pins["models"][route]["id"],
                                  "provider_model": pins["models"][route]["provider_model"],
                                  "hf_repo": pins["models"][route]["hf_repo"],
                                  "hf_revision": pins["models"][route]["hf_revision"],
                                  "endpoint": fast_endpoint if route == "fast" else strong_endpoint,
                                  "data_classes": ["public", "local"],
                                  "max_output_tokens": 512 if route == "fast" else 1_024,
                                  "timeout_seconds": 120}
                         for route in ROUTES},
              "limits": {"max_checkout_bytes": 2_000_000, "max_checkout_files": 100,
                         "max_patch_bytes": 32_000, "max_evidence_bytes": 64_000,
                         "max_eval_seconds": 30}}
    coding_fixture = {route: {"files": [{"path": "solution.py", "content": solution_text}]}
                      for route in ROUTES}
    for name, value in (("task.json", task), ("orchestration.json", config),
                        ("route-profile.json", profile),
                        ("route-fixtures.json", {task_id: route_fixture}),
                        ("coding-fixtures.json", coding_fixture)):
        write_new(directory / name, value)
    return {"status": "completed", "operation": "init", "directory": str(directory),
            "base_commit": commit, "created": ["fixture-repo", "evaluator/test_solution.py",
                                              "task.json", "orchestration.json", "route-profile.json",
                                              "route-fixtures.json", "coding-fixtures.json"],
            "notice": "Synthetic fixture and pinned local model registrations; no inference was called."}


def inspect(run_dir: Path) -> dict:
    path = run_dir.resolve() / "events.jsonl"
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise OrchestrationError("file_read_failed", "The run events could not be read.",
                                 "Check the run directory.") from exc
    if len(raw) > MAX_JSON_BYTES:
        fail("record_too_large", "The run events exceed the inspection limit.",
             "Inspect the protected record manually.")
    events = [json.loads(line) for line in raw.splitlines()]
    if not events:
        fail("invalid_record", "The run has no events.", "Inspect the incomplete run directory.")
    if events[-1]["event"] == "completed":
        replay(run_dir)
    return {"status": events[-1]["event"], "run_dir": str(run_dir.resolve()),
            "events": [{"event": event["event"], "time_unix_ms": event["time_unix_ms"]}
                       for event in events], "last_event": events[-1]}


def _assert_completed_artifacts(run_dir: Path, config: dict, task: dict,
                                events: list[dict], routed: dict,
                                reconstructed_checkout: Path | None = None) -> None:
    names = [row.get("event") for row in events]
    if names != ["started", "evaluator_snapshotted", "routed", "restore_proven",
                 "model_completed", "patch_applied", "verified", "completed"]:
        fail("record_integrity_failed", "A completed run lacks its ordered execution evidence.",
             "Use the original run record and artifact files.")
    evaluator_event, restore, model_event, patch_event = events[1], events[3], events[4], events[5]
    evaluator = run_dir / "trusted-evaluator" / Path(task["evaluator_file"]).name
    model_path = run_dir / "model-output.json"
    patch_path = run_dir / "patch.json"
    for path, expected in ((evaluator, task["evaluator_sha256"]),
                           (model_path, model_event.get("output_sha256")),
                           (patch_path, patch_event.get("patch_sha256"))):
        if (not path.is_file() or path.is_symlink() or type(expected) is not str or
                not _SHA256.fullmatch(expected) or file_hash(path) != expected):
            fail("record_integrity_failed", "A completed run artifact is missing or changed.",
                 "Restore the original protected evaluator, model output, and patch evidence.")
    if (evaluator_event.get("evaluator_sha256") != task["evaluator_sha256"] or
            evaluator_event.get("path") != str(evaluator)):
        fail("record_integrity_failed", "The evaluator snapshot event is inconsistent.",
             "Use the original run record.")
    recorded_checkout = run_dir / "checkout"
    checkout = reconstructed_checkout if reconstructed_checkout is not None else recorded_checkout
    scratch = run_dir / "restore-proof"
    if (restore.get("checkout") != str(recorded_checkout) or restore.get("scratch") != str(scratch) or
            not checkout.is_dir() or not scratch.is_dir()):
        fail("record_integrity_failed", "The completed run checkout or restore proof is missing.",
             "Restore the original run artifacts.")
    for root in (checkout, scratch):
        if any(path.is_symlink() for path in root.rglob("*")):
            fail("record_integrity_failed", "A completed run tree contains a link.",
                 "Restore the original regular-file artifacts.")
    if _tree_hash(scratch) != restore.get("base_tree_sha256"):
        fail("record_integrity_failed", "The saved base restore proof changed.",
             "Restore the original pinned base evidence.")
    try:
        model_output = load_json(model_path)
        patch = load_json(patch_path)
        parsed_files = _parse_patch(model_output["content"], task,
                                    config["limits"]["max_patch_bytes"])
    except (OrchestrationError, KeyError, TypeError):
        fail("record_integrity_failed", "The saved model output or patch is invalid.",
             "Restore the original protected model and patch evidence.")
    if (type(patch) is not dict or set(patch) !=
            {"base_commit", "files", "hashes", "route", "model"} or
            patch["base_commit"] != task["base_commit"] or
            patch["route"] != routed["selected_route"] or
            patch["model"] != model_event.get("model") or
            model_output.get("model") != model_event.get("model") or
            patch["files"] != parsed_files or
            type(patch["hashes"]) is not dict or
            set(patch["hashes"]) != {"before", "after"}):
        fail("record_integrity_failed", "The saved patch disagrees with its model and route.",
             "Restore the original run artifacts.")
    before = patch["hashes"]["before"]
    after = patch["hashes"]["after"]
    edited = {row["path"] for row in parsed_files}
    if (type(before) is not dict or type(after) is not dict or
            set(before) != edited or set(after) != edited):
        fail("record_integrity_failed", "The patch file hashes are incomplete.",
             "Restore the original patch artifact.")
    base_files = {path.relative_to(scratch).as_posix(): path for path in scratch.rglob("*")
                  if path.is_file()}
    current_files = {path.relative_to(checkout).as_posix(): path for path in checkout.rglob("*")
                     if path.is_file()}
    if set(base_files) != set(current_files):
        fail("record_integrity_failed", "The checkout file set differs from its pinned base.",
             "Restore the original isolated checkout.")
    for name, base_path in base_files.items():
        base_hash = file_hash(base_path)
        current_hash = file_hash(current_files[name])
        if ((name in edited and (before[name] != base_hash or after[name] != current_hash)) or
                (name not in edited and base_hash != current_hash)):
            fail("record_integrity_failed", "The checkout differs from the recorded patch.",
                 "Restore the original isolated checkout and patch evidence.")


def replay(run_dir: Path, *, reconstructed_checkout: Path | None = None) -> dict:
    run_dir = run_dir.resolve()
    config = validate_config(load_json(run_dir / "config.snapshot.json"))
    task = load_json(run_dir / "task.snapshot.json")
    events = _events(run_dir)
    if not events:
        fail("invalid_record", "The run has no events.", "Inspect the incomplete run directory.")
    record_status = events[-1]["event"]
    started = next((row for row in events if row["event"] == "started"), None)
    routed = next((row for row in events if row["event"] == "routed"), None)
    if started is None or routed is None or digest(config) != started["config_hash"] or digest(task) != started["task_hash"]:
        fail("record_integrity_failed", "Saved task, config, or routing evidence is incomplete or changed.",
             "Use the original immutable run records.")
    if routed["jev_audit_path"] is None:
        if (routed["source"] != "baseline" or routed["jev_decision"] is not None or
                routed["jev_request_hash"] is not None or routed["jev_response_hash"] is not None or
                started["jev_mode"] != "off"):
            fail("record_integrity_failed", "A route without Jev has inconsistent metadata.",
                 "Use the original run record.")
        decision = None
    else:
        if started["jev_mode"] == "off":
            fail("record_integrity_failed", "The Jev audit conflicts with an off-mode run.",
                 "Use the original run record.")
        historical = jev.replay(routed["jev_audit_path"])
        if (historical["request_hash"] != routed["jev_request_hash"] or
                historical["response_hash"] != routed["jev_response_hash"] or
                historical["decision"] != routed["jev_decision"]):
            fail("record_integrity_failed", "The routed Jev evidence differs from its audit.",
                 "Use the original linked Jev audit and run record.")
        decision = historical["decision"]
    eligible = _eligible(config, task)
    selected = _route(config, task, eligible, decision, routed["source"])
    if selected != routed["selected_route"]:
        fail("record_integrity_failed", "The saved route differs from recomputed policy.",
             "Inspect the original run record.")
    if record_status == "completed":
        _assert_completed_artifacts(run_dir, config, task, events, routed,
                                    reconstructed_checkout)
        if (len(events) < 2 or events[-2]["event"] != "verified" or
                events[-1].get("verified_completion") is not True):
            fail("record_integrity_failed", "Completion lacks a preceding trusted verification.",
                 "Inspect the original run record.")
        verified = events[-2]
        verification = load_json(run_dir / "verification.json")
        if (verified.get("exit_code") != 0 or verification.get("exit_code") != 0 or
                verified.get("evaluator_sha256") != task.get("evaluator_sha256") or
                any(verified.get(key) != value for key, value in verification.items())):
            fail("record_integrity_failed", "Completion disagrees with trusted verifier evidence.",
                 "Inspect the original verifier output and run record.")
        if _trusted_verdict(Path(verification["stdout_path"])) != verification.get("verdict"):
            fail("record_integrity_failed", "The saved test verdict differs from trusted verifier output.",
                 "Inspect the original protected verifier record.")
        for path_key, hash_key in (("stdout_path", "stdout_sha256"),
                                   ("stderr_path", "stderr_sha256")):
            evidence = Path(verification[path_key]).resolve()
            if (not evidence.is_relative_to(run_dir) or not evidence.is_file() or
                    file_hash(evidence) != verification[hash_key]):
                fail("record_integrity_failed", "The trusted verifier output is missing or changed.",
                     "Restore the original protected evidence.")
    return {"status": "completed", "operation": "historical_replay", "route": selected,
            "run_status": record_status, "jev_network_called": False,
            "jev_audit_path": routed["jev_audit_path"]}


def _events(run_dir: Path) -> list[dict]:
    return [json.loads(line) for line in (run_dir / "events.jsonl").read_bytes().splitlines()]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="generate a complete isolated fixture task")
    init.add_argument("--directory", required=True)
    init.add_argument("--fast-endpoint", default="http://127.0.0.1:8000/v1/chat/completions")
    init.add_argument("--strong-endpoint", default="http://127.0.0.1:8001/v1/chat/completions")
    init.add_argument("--fixture-complexity", choices=("simple", "complex"), default="simple")
    for name in ("dry-run", "run", "demo"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--directory", required=True)
        if name != "demo":
            cmd.add_argument("--mode", choices=("fixture", "live"), required=True)
            cmd.add_argument("--jev-mode", choices=("off", "fixture", "live"), required=True)
            cmd.add_argument("--route-source", choices=("baseline", "jev"), default="baseline")
        if name == "run":
            cmd.add_argument("--dotenv")
            cmd.add_argument("--watch", action="store_true")
            cmd.add_argument("--experimental-jev-route", action="store_true")
    for name in ("inspect", "replay"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--run-dir", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = initialize(Path(args.directory), args.fast_endpoint, args.strong_endpoint,
                                args.fixture_complexity)
        elif args.command == "dry-run":
            result = dry_run(Path(args.directory), args.mode, args.jev_mode, args.route_source)
        elif args.command == "run":
            result = run(Path(args.directory), args.mode, args.jev_mode, args.route_source,
                         args.dotenv, args.watch, args.experimental_jev_route)
        elif args.command == "demo":
            result = run(Path(args.directory), "fixture", "fixture", "baseline", None, False, False)
        elif args.command == "inspect":
            result = inspect(Path(args.run_dir))
        else:
            result = replay(Path(args.run_dir))
        print(canonical_bytes(result).decode("utf-8"))
        return 0
    except (OrchestrationError, jev.HarnessError, local_model.LocalModelError) as exc:
        if isinstance(exc, OrchestrationError):
            report = exc.report()
        else:
            report = {"status": "failed", "code": exc.code, "message": exc.message,
                      "next_action": exc.next_action, "run_dir": None}
        print(canonical_bytes(report).decode("utf-8"), file=sys.stderr)
        return 1
    except Exception:
        print(canonical_bytes({"status": "failed", "code": "internal_error",
                               "message": "An unexpected orchestration failure occurred.",
                               "next_action": "Inspect the partial run directory and report the failing command without credentials.",
                               "run_dir": None}).decode("utf-8"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
