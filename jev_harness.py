#!/usr/bin/env python3
"""A stdlib-only, auditable adapter for TypeSafe Jev classification.

Fixture mode exercises synthetic plumbing. Live mode is always explicit.
Policy decisions recommend acceptance or human review; they perform no action.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, localcontext
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


HARNESS_VERSION = "0.1.0"
MAX_FILE_BYTES = 1_000_000
MAX_DATASET_ITEMS = 20
FIXTURE_NOTICE = "Synthetic fixture: validates harness plumbing, not Jev accuracy."
CONFIG_FIELDS = {
    "schema_version", "endpoint", "model", "api_key_env", "timeout_seconds",
    "max_input_bytes", "audit_dir", "question", "policy", "fixture_file",
}


class HarnessError(Exception):
    """A safe, actionable error; upstream bodies and credentials never belong here."""

    def __init__(self, code: str, message: str, next_action: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.next_action = next_action
        self.audit_path: str | None = None
        self.context: dict = {}

    def report(self) -> dict:
        return {
            "status": "failed", "code": self.code, "message": self.message,
            "next_action": self.next_action, "audit_path": self.audit_path, **self.context,
        }


def fail(code: str, message: str, action: str = "Correct the named field and retry."):
    raise HarnessError(code, message, action)


def _finite_json(value, location="JSON", depth=0):
    if depth > 100:
        fail("invalid_json", f"{location} exceeds the supported nesting depth of 100.")
    if value is None or type(value) in (bool, int):
        return
    if type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise HarnessError("invalid_json", f"{location} contains invalid Unicode.", "Replace unpaired Unicode surrogates with valid Unicode text.") from exc
        return
    if type(value) is float:
        if not math.isfinite(value):
            fail("invalid_json", f"{location} contains a non-finite number.")
        return
    if type(value) is list:
        for item in value:
            _finite_json(item, location, depth + 1)
        return
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            fail("invalid_json", f"{location} contains a non-string object key.")
        for key in value:
            _finite_json(key, location, depth + 1)
        for item in value.values():
            _finite_json(item, location, depth + 1)
        return
    fail("invalid_json", f"{location} contains a value that JSON cannot represent.")


def _pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            fail("invalid_json", "JSON contains a duplicate object key.", "Remove the duplicate key; do not rely on last-value-wins parsing.")
        obj[key] = value
    return obj


def _constant(_value):
    fail("invalid_json", "JSON contains NaN or Infinity.", "Use only finite JSON numbers.")


def _parse_json(raw: bytes):
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        _finite_json(value)
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise HarnessError("invalid_json", "The document is not supported UTF-8 JSON.", "Correct JSON syntax and keep nesting at or below 100 levels.") from exc


def load_json(path, max_bytes=MAX_FILE_BYTES):
    """Load bounded UTF-8 JSON, rejecting duplicate keys and non-finite numbers."""
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError as exc:
        raise HarnessError("file_read_failed", "A required JSON file could not be read.", "Check the supplied path and read permissions.") from exc
    if len(raw) > max_bytes:
        fail("file_too_large", "A JSON file exceeds the configured byte limit.", "Reduce the file size or adjust max_input_bytes within its allowed range.")
    return _parse_json(raw)


def _canonical_bytes(value):
    _finite_json(value)
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise HarnessError("invalid_json", "JSON cannot be encoded canonically.", "Use valid Unicode and bounded JSON nesting.") from exc


def canonical_hash(value):
    """SHA-256 of sorted-key, compact, UTF-8 JSON without float normalization."""
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _object(value, field, required=None, allowed=None):
    if type(value) is not dict:
        fail("invalid_field", f"{field} must be an object.")
    if required is not None and not set(required).issubset(value):
        fail("missing_field", f"{field} is missing required fields: {', '.join(sorted(set(required) - set(value)))}.")
    if allowed is not None and set(value) - set(allowed):
        names = [key if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key) else "<nonstandard field name>" for key in sorted(set(value) - set(allowed))]
        fail("unknown_field", f"{field} contains unsupported fields: {', '.join(names)}.", f"Use only the documented fields for {field}.")


def _string(value, field, limit=100_000):
    if type(value) is not str or not value.strip() or len(value) > limit:
        fail("invalid_field", f"{field} must be a nonempty string of at most {limit} characters.")


def _number(value, field, low, high, integer=False):
    valid_types = (int,) if integer else (int, float)
    if type(value) not in valid_types or (type(value) is float and not math.isfinite(value)) or not low <= value <= high:
        kind = "integer" if integer else "finite number"
        fail("invalid_field", f"{field} must be a {kind} between {low} and {high}.")


def _relative_path(value, field):
    _string(value, field, 240)
    # Reject both separators so config semantics remain portable across hosts.
    parts = value.replace("\\", "/").split("/")
    if Path(value).is_absolute() or ":" in value or any(p in ("", ".", "..") for p in parts):
        fail("invalid_field", f"{field} must be a child path relative to the configuration directory.")


def _resolve_relative(base: Path, value: str, field: str) -> Path:
    _relative_path(value, field)
    destination = (base / value).resolve()
    if not destination.is_relative_to(base.resolve()) or destination == base.resolve():
        fail("invalid_field", f"{field} resolves outside the configuration directory.")
    return destination


def validate_config(config):
    """Validate all operator settings and their bounds; return the original object."""
    _finite_json(config, "config")
    _object(config, "config", CONFIG_FIELDS, CONFIG_FIELDS)
    if type(config["schema_version"]) is not int or config["schema_version"] != 1:
        fail("invalid_field", "schema_version must be integer 1.")
    _string(config["endpoint"], "endpoint", 200)
    try:
        endpoint = urllib.parse.urlsplit(config["endpoint"])
        valid_endpoint = (
            endpoint.scheme == "https" and endpoint.hostname == "api.typesafe.ai"
            and endpoint.port in (None, 443) and endpoint.path == "/v1/systemone"
            and endpoint.username is None and endpoint.password is None
            and not endpoint.query and not endpoint.fragment
        )
    except ValueError:
        valid_endpoint = False
    if not valid_endpoint:
        fail("invalid_field", "endpoint must identify https://api.typesafe.ai/v1/systemone without credentials, query, or fragment.")
    if type(config["model"]) is not str or not re.fullmatch(r"jev-[0-9]+\.[0-9]+\.[0-9]+", config["model"]):
        fail("invalid_field", "model must be a pinned jev-x.y.z version; aliases such as latest are forbidden.")
    if type(config["api_key_env"]) is not str or not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", config["api_key_env"]):
        fail("invalid_field", "api_key_env must be an uppercase environment variable name.")
    _number(config["timeout_seconds"], "timeout_seconds", 1, 120)
    _number(config["max_input_bytes"], "max_input_bytes", 1, MAX_FILE_BYTES, integer=True)
    _relative_path(config["audit_dir"], "audit_dir")
    _relative_path(config["fixture_file"], "fixture_file")
    question = config["question"]
    _object(question, "question", {"id", "instructions", "criteria"}, {"id", "instructions", "criteria"})
    _string(question["id"], "question.id", 128)
    _string(question["instructions"], "question.instructions")
    _object(question["criteria"], "question.criteria")
    if not 2 <= len(question["criteria"]) <= 255:
        fail("invalid_field", "question.criteria must contain between 2 and 255 labels.")
    for label, description in question["criteria"].items():
        _string(label, "question.criteria label", 128)
        _string(description, "question.criteria description", 10_000)
    policy = config["policy"]
    fields = {"min_probability", "min_margin", "review_labels"}
    _object(policy, "policy", fields, fields)
    _number(policy["min_probability"], "policy.min_probability", 0, 1)
    _number(policy["min_margin"], "policy.min_margin", 0, 1)
    if type(policy["review_labels"]) is not list or any(type(label) is not str for label in policy["review_labels"]):
        fail("invalid_field", "policy.review_labels must be a list of criterion labels.")
    if len(set(policy["review_labels"])) != len(policy["review_labels"]) or not set(policy["review_labels"]).issubset(question["criteria"]):
        fail("invalid_field", "policy.review_labels must contain distinct labels from question.criteria.")
    return config


def validate_input(value):
    _finite_json(value, "input")
    _object(value, "input", {"id", "state"}, {"id", "state"})
    _string(value["id"], "input.id", 256)
    if type(value["state"]) not in (str, dict, list):
        fail("invalid_field", "input.state must be a string, object, or array.")
    return value


def build_request(config, input_value):
    question = config["question"]
    return {
        "model": config["model"], "state": input_value["state"],
        "questions": {question["id"]: {
            "type": "choice", "instructions": question["instructions"],
            "criteria": question["criteria"],
        }},
    }


def validate_response(response, request):
    """Check provider output strictly without changing or renormalizing any value."""
    _finite_json(response, "response")
    _object(response, "response", {"model", "answers", "usage"})
    if response["model"] != request["model"]:
        fail("invalid_response", "The response model does not match the pinned request model.", "Check the provider version contract; do not accept this response.")
    _object(response["answers"], "response.answers")
    if set(response["answers"]) != set(request["questions"]):
        fail("invalid_response", "The response must contain exactly the requested question answers.")
    for question_id, question in request["questions"].items():
        answer = response["answers"][question_id]
        _object(answer, "answer", {"type", "choice", "probabilities", "confidence"})
        if answer["type"] != "choice":
            fail("invalid_response", "The answer type must be choice.")
        labels = set(question["criteria"])
        if type(answer["choice"]) is not str or answer["choice"] not in labels:
            fail("invalid_response", "The selected choice is not a configured criterion.")
        _object(answer["probabilities"], "answer.probabilities")
        if set(answer["probabilities"]) != labels:
            fail("invalid_response", "Probability labels must exactly match the configured criteria.")
        for probability in answer["probabilities"].values():
            _number(probability, "answer.probabilities value", 0, 1)
        if abs(math.fsum(answer["probabilities"].values()) - 1.0) > 0.001:
            fail("invalid_response", "Answer probabilities must sum to 1 within tolerance 0.001.")
        if answer["probabilities"][answer["choice"]] != max(answer["probabilities"].values()):
            fail("invalid_response", "The selected choice does not have maximum probability.")
        _number(answer["confidence"], "answer.confidence", 0, 1)
    _object(response["usage"], "response.usage", {"input_tokens", "output_tokens"})
    for name in ("input_tokens", "output_tokens"):
        value = response["usage"][name]
        if type(value) is not int or value < 0:
            fail("invalid_response", f"response.usage.{name} must be a nonnegative integer.")
    return response


def decide(response, config):
    """Apply deterministic thresholds to an already validated provider response."""
    answer = response["answers"][config["question"]["id"]]
    probabilities = sorted(answer["probabilities"].values(), reverse=True)
    probability = answer["probabilities"][answer["choice"]]
    # JSON decimal thresholds are inclusive. Avoid binary subtraction turning
    # the exact decimal margin 0.6 - 0.4 into 0.19999999999999996.
    with localcontext() as decimal_context:
        decimal_context.prec = 400
        decimal_margin = Decimal(str(probabilities[0])) - Decimal(str(probabilities[1]))
    margin = float(decimal_margin)
    reasons = []
    if probabilities[0] == probabilities[1]:
        reasons.append("tied_top_probability")
    if probability < config["policy"]["min_probability"]:
        reasons.append("below_min_probability")
    if decimal_margin < Decimal(str(config["policy"]["min_margin"])):
        reasons.append("below_min_margin")
    if answer["choice"] in config["policy"]["review_labels"]:
        reasons.append("label_requires_review")
    return {
        "status": "review" if reasons else "accept", "label": answer["choice"],
        "reasons": reasons, "probability": probability, "margin": margin,
        "confidence": answer["confidence"], "recommendation_only": True,
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _live_response(config, request):
    key = os.environ.get(config["api_key_env"])
    if not key:
        fail("missing_credential", f"Missing configured credential {config['api_key_env']}.", "Set this environment variable in your shell and retry live mode.")
    if any(character in key for character in ("\r", "\n", "\x00")):
        fail("invalid_credential", "The configured credential has an invalid header value.", "Replace the environment variable with a valid provider credential.")
    req = urllib.request.Request(
        config["endpoint"], data=_canonical_bytes(request), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json"},
    )
    # Explicit direct TLS connection: no inherited proxy, redirect, or retry.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(req, timeout=config["timeout_seconds"]) as response:
            if response.status != 200:
                fail("http_error", f"The provider returned HTTP status {response.status}.", "Check service availability and the provider request contract, then retry manually.")
            raw = response.read(MAX_FILE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        raise HarnessError("http_error", f"The provider returned HTTP status {code}.", "Check the credential, quota, pinned model, and provider status; retry manually if appropriate.") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise HarnessError("transport_error", "The direct HTTPS request failed or timed out.", "Check network access, TLS trust, and timeout_seconds; retry manually if appropriate.") from None
    if len(raw) > MAX_FILE_BYTES:
        fail("response_too_large", "The provider response exceeded the hard 1000000-byte limit.", "Reduce the request scope and retry manually.")
    return _parse_json(raw)


def _fixture_response(config, base, input_value):
    fixtures = load_json(_resolve_relative(base, config["fixture_file"], "fixture_file"))
    _object(fixtures, "fixtures")
    if input_value["id"] not in fixtures:
        fail("fixture_missing", "No synthetic fixture exists for input.id.", "Add the matching synthetic fixture or choose an existing example input ID.")
    return fixtures[input_value["id"]]


class Audit:
    def __init__(self, directory: Path):
        self.path = directory / f"{uuid.uuid4()}.jsonl"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL, 0o600)
            self.handle = os.fdopen(descriptor, "a", encoding="utf-8", newline="\n")
        except OSError as exc:
            raise HarnessError("audit_failed", "The audit record could not be created.", "Check audit_dir, free disk space, and write permissions before retrying.") from exc

    def write(self, event):
        try:
            self.handle.write(_canonical_bytes(event).decode("utf-8") + "\n")
            self.handle.flush()
            os.fsync(self.handle.fileno())
        except OSError as exc:
            failure = HarnessError("audit_failed", "The audit event could not be persisted.", "Inspect the incomplete audit record and restore writable storage before retrying.")
            failure.audit_path = str(self.path)
            raise failure from exc

    def close(self):
        try:
            self.handle.close()
        except OSError:
            fail("audit_failed", "The audit file could not be closed cleanly.", "Inspect the audit record and storage state before relying on this run.")


def run_one(config, base, input_value, mode):
    validate_config(config)
    validate_input(input_value)
    if len(_canonical_bytes(input_value)) > config["max_input_bytes"]:
        fail("input_too_large", "The input exceeds max_input_bytes.", "Reduce input size or adjust max_input_bytes within its allowed range.")
    request = build_request(config, input_value)
    audit = Audit(_resolve_relative(base, config["audit_dir"], "audit_dir"))
    start = time.monotonic_ns()
    common = {
        "harness_version": HARNESS_VERSION, "mode": mode,
        "source": "synthetic_fixture" if mode == "fixture" else "typesafe_api",
        "config_snapshot": config, "input_snapshot": input_value, "request": request,
        "policy": config["policy"], "config_hash": canonical_hash(config),
        "input_hash": canonical_hash(input_value), "request_hash": canonical_hash(request),
        "policy_hash": canonical_hash(config["policy"]),
    }
    if mode == "fixture":
        common["notice"] = FIXTURE_NOTICE
    try:
        audit.write({"event": "started", "status": "started", "created_unix_ms": time.time_ns() // 1_000_000, **common})
        if mode == "fixture":
            response = _fixture_response(config, base, input_value)
        elif mode == "live":
            response = _live_response(config, request)
        else:
            fail("invalid_mode", "mode must explicitly be fixture or live.")
        validate_response(response, request)
        decision = decide(response, config)
        terminal = {
            "event": "completed", "status": "completed", **common,
            "response": response, "response_hash": canonical_hash(response),
            "decision": decision, "decision_hash": canonical_hash(decision),
            "elapsed_ms": (time.monotonic_ns() - start) // 1_000_000,
        }
        audit.write(terminal)
        return {**terminal, "audit_path": str(audit.path)}
    except HarnessError as exc:
        exc.audit_path = str(audit.path)
        if exc.code != "audit_failed":
            audit.write({"event": "failed", "harness_version": HARNESS_VERSION, "mode": mode, "error": exc.report(), "elapsed_ms": (time.monotonic_ns() - start) // 1_000_000})
        raise
    except Exception as exc:
        safe = HarnessError("internal_error", "The harness encountered an unexpected failure.", "Retain the audit record and report the failing command without credentials.")
        safe.audit_path = str(audit.path)
        audit.write({"event": "failed", "harness_version": HARNESS_VERSION, "mode": mode, "error": safe.report(), "elapsed_ms": (time.monotonic_ns() - start) // 1_000_000})
        raise safe from None
    finally:
        audit.close()


def replay(record_path):
    try:
        with Path(record_path).open("rb") as handle:
            raw = handle.read(12 * MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise HarnessError("file_read_failed", "The audit record could not be read.", "Check the record path and permissions.") from exc
    if len(raw) > 12 * MAX_FILE_BYTES:
        fail("invalid_record", "The audit record exceeds the supported size limit.")
    lines = raw.splitlines()
    if len(lines) != 2:
        fail("invalid_record", "Replay requires exactly one started event and one completed event.", "Select a completed, unmodified per-run JSONL audit record.")
    started, completed = [_parse_json(line) for line in lines]
    _object(started, "started audit event", {"event", "mode", "harness_version"})
    _object(completed, "completed audit event", {"event", "mode", "harness_version", "response", "response_hash", "decision", "decision_hash"})
    if started["event"] != "started" or completed["event"] != "completed":
        fail("invalid_record", "The audit record is incomplete or failed.", "Select a successfully completed audit record.")
    if started["harness_version"] != HARNESS_VERSION or completed["harness_version"] != HARNESS_VERSION:
        fail("incompatible_record", "The audit record uses a different harness version.", "Replay with the harness version recorded in the audit event.")
    if completed["mode"] not in ("fixture", "live") or started["mode"] != completed["mode"]:
        fail("invalid_record", "The audit mode is inconsistent or invalid.")
    for name, hash_name in (("config_snapshot", "config_hash"), ("input_snapshot", "input_hash"), ("request", "request_hash"), ("policy", "policy_hash")):
        for event in (started, completed):
            if name not in event or hash_name not in event or canonical_hash(event[name]) != event[hash_name]:
                fail("record_integrity_failed", f"The audit {name} hash does not match.", "Use the original audit record; this file may have been modified.")
        if started[hash_name] != completed[hash_name]:
            fail("record_integrity_failed", f"The started and completed {name} differ.")
    for name in ("response", "decision"):
        if canonical_hash(completed[name]) != completed[f"{name}_hash"]:
            fail("record_integrity_failed", f"The audit {name} hash does not match.", "Use the original audit record; this file may have been modified.")
    config = validate_config(completed["config_snapshot"])
    input_value = validate_input(completed["input_snapshot"])
    if config["policy"] != completed["policy"] or build_request(config, input_value) != completed["request"]:
        fail("record_integrity_failed", "The stored request or policy differs from its configuration and input.")
    validate_response(completed["response"], completed["request"])
    decision = decide(completed["response"], config)
    if decision != completed["decision"]:
        fail("record_integrity_failed", "Recomputed policy decision differs from the recorded decision.")
    result = {
        "status": "completed", "operation": "historical_replay", "mode": completed["mode"],
        "harness_version": HARNESS_VERSION, "decision": decision, "audit_path": str(Path(record_path).resolve()),
        "network_called": False, "request_hash": completed["request_hash"],
        "response_hash": completed["response_hash"], "policy_hash": completed["policy_hash"],
        "integrity_scope": "Hashes detect inconsistent edits, not forgery; records are not digitally signed.",
    }
    if completed["mode"] == "fixture":
        result["notice"] = FIXTURE_NOTICE
    return result


def evaluate(config, base, dataset, mode):
    _object(dataset, "dataset", {"items"}, {"items"})
    items = dataset["items"]
    if type(items) is not list or not 1 <= len(items) <= MAX_DATASET_ITEMS:
        fail("invalid_dataset", "dataset.items must contain between 1 and 20 rows.")
    identifiers = set()
    for row in items:
        _object(row, "dataset row", {"id", "state", "expected_label"}, {"id", "state", "expected_label"})
        value = validate_input({"id": row["id"], "state": row["state"]})
        if len(_canonical_bytes(value)) > config["max_input_bytes"]:
            fail("input_too_large", "A dataset row exceeds max_input_bytes.")
        if row["id"] in identifiers:
            fail("invalid_dataset", "dataset.items contains duplicate input IDs.")
        identifiers.add(row["id"])
        if type(row["expected_label"]) is not str or row["expected_label"] not in config["question"]["criteria"]:
            fail("invalid_dataset", "Each expected_label must be a configured criterion.")
    # Validate every row before the first transport call or audit mutation.
    results = []
    for row in items:
        try:
            result = run_one(config, base, {"id": row["id"], "state": row["state"]}, mode)
        except HarnessError as exc:
            exc.context.update({
                "evaluation_incomplete": True, "completed_count": len(results),
                "total_count": len(items), "mode": mode,
                "completed_audit_paths": [prior["audit_path"] for prior in results],
            })
            raise
        results.append({"id": row["id"], "expected_label": row["expected_label"], "decision": result["decision"], "audit_path": result["audit_path"]})
    correct = sum(row["decision"]["label"] == row["expected_label"] for row in results)
    accepted = [row for row in results if row["decision"]["status"] == "accept"]
    accepted_correct = sum(row["decision"]["label"] == row["expected_label"] for row in accepted)
    confusion = {label: {predicted: 0 for predicted in config["question"]["criteria"]} for label in config["question"]["criteria"]}
    for row in results:
        confusion[row["expected_label"]][row["decision"]["label"]] += 1
    report = {
        "status": "completed", "operation": "evaluate", "mode": mode,
        "source": "synthetic_fixture" if mode == "fixture" else "typesafe_api",
        "harness_version": HARNESS_VERSION, "count": len(results),
        "accuracy": correct / len(results), "accepted_accuracy": accepted_correct / len(accepted) if accepted else None,
        "accepted_coverage": len(accepted) / len(results), "review_count": len(results) - len(accepted),
        "confusion": confusion, "confusion_axes": {"rows": "expected", "columns": "predicted"}, "results": results,
    }
    if mode == "fixture":
        report["notice"] = FIXTURE_NOTICE
    return report


def initialize(directory):
    directory = Path(directory).resolve()
    try:
        if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
            fail("init_target_not_empty", "The initialization directory must be empty or absent.", "Choose a new empty directory; init never overwrites files.")
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HarnessError("init_failed", "The initialization directory could not be created or inspected.", "Choose an accessible empty directory.") from exc
    config = {
        "schema_version": 1, "endpoint": "https://api.typesafe.ai/v1/systemone",
        "model": "jev-1.13.0", "api_key_env": "TYPESAFE_API_KEY", "timeout_seconds": 30,
        "max_input_bytes": 100_000, "audit_dir": "audit", "fixture_file": "fixtures.json",
        "question": {"id": "route", "instructions": "Classify the primary intent of the supplied request. Choose unknown when the intent is unclear or outside the other categories.", "criteria": {
            "maintenance": "A request to inspect, repair, or maintain physical equipment or facilities.",
            "admin": "A request about billing, accounts, paperwork, or scheduling that does not request physical repair.",
            "unknown": "The intent is ambiguous, has conflicting primary purposes, or fits neither maintenance nor admin.",
        }},
        "policy": {"min_probability": 0.9, "min_margin": 0.2, "review_labels": ["unknown"]},
    }
    maintenance_state = "The lift in Building B is stuck. Please send a maintenance technician."
    admin_state = "Please update the billing contact for our next service invoice."
    unknown_state = "Can you take care of the thing we discussed?"
    def synthetic(choice, probabilities, confidence):
        return {"model": config["model"], "answers": {"route": {"type": "choice", "choice": choice, "probabilities": probabilities, "confidence": confidence}}, "usage": {"input_tokens": 0, "output_tokens": 0}}
    fixtures = {
        "example-maintenance": synthetic("maintenance", {"maintenance": 0.98, "admin": 0.01, "unknown": 0.01}, 0.92),
        "example-admin": synthetic("admin", {"maintenance": 0.02, "admin": 0.95, "unknown": 0.03}, 0.90),
        "example-unknown": synthetic("unknown", {"maintenance": 0.15, "admin": 0.15, "unknown": 0.70}, 0.60),
    }
    files = {
        "config.json": config,
        "input.json": {"id": "example-maintenance", "state": maintenance_state},
        "fixtures.json": fixtures,
        "dataset.json": {"items": [
            {"id": "example-maintenance", "state": maintenance_state, "expected_label": "maintenance"},
            {"id": "example-admin", "state": admin_state, "expected_label": "admin"},
            {"id": "example-unknown", "state": unknown_state, "expected_label": "unknown"},
        ]},
    }
    created = []
    try:
        for name, value in files.items():
            with (directory / name).open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
            created.append(name)
    except OSError as exc:
        fail("init_failed", "Initialization stopped before all files were created.", "Inspect the partial directory and choose a new empty directory; existing files are never overwritten.")
    return {"status": "completed", "operation": "init", "directory": str(directory), "created": created, "notice": FIXTURE_NOTICE}


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        fail("invalid_arguments", "The command arguments are invalid or incomplete.", "Run the command with --help and supply all required arguments; --mode must explicitly be fixture or live.")


def main(argv=None):
    parser = SafeArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Create synthetic examples in an empty directory.")
    init.add_argument("--directory", required=True)
    for name in ("run", "evaluate"):
        command = sub.add_parser(name)
        command.add_argument("--config", required=True)
        command.add_argument("--input" if name == "run" else "--dataset", required=True)
        command.add_argument("--mode", required=True, choices=("fixture", "live"))
    replay_parser = sub.add_parser("replay", help="Recompute a historical decision without network access.")
    replay_parser.add_argument("--record", required=True)
    try:
        args = parser.parse_args(argv)
        if args.command == "init":
            result = initialize(args.directory)
        elif args.command == "replay":
            result = replay(args.record)
        else:
            config_path = Path(args.config).resolve()
            config = validate_config(load_json(config_path))
            if args.command == "run":
                value = validate_input(load_json(args.input, config["max_input_bytes"]))
                result = run_one(config, config_path.parent, value, args.mode)
            else:
                result = evaluate(config, config_path.parent, load_json(args.dataset), args.mode)
        print(_canonical_bytes(result).decode("utf-8"))
        return 0
    except HarnessError as exc:
        print(json.dumps(exc.report(), ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1
    except Exception:
        print(json.dumps({"status": "failed", "code": "internal_error", "message": "An unexpected harness failure occurred.", "next_action": "Retain any audit record and report the failing command without credentials.", "audit_path": None}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
