"""Strict local computer-use records and transport; no inference or UI effects."""
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent


class UIError(Exception):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise UIError(f"Duplicate JSON key: {key}; regenerate the fixture.")
            result[key] = value
        return result
    raw = Path(path).read_bytes()
    if len(raw) > 1_000_000:
        raise UIError("Artifact exceeds 1000000 bytes; inspect it before continuing.")
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(UIError(f"Invalid JSON value: {value}")))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
        handle.write(canonical(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    return path


def exact(value, keys, name):
    if type(value) is not dict or set(value) != set(keys):
        raise UIError(f"Invalid {name} fields; regenerate with ui_fixture.py generate.")


def bounded(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise UIError(f"{name} must be an integer in [{low}, {high}].")


def validate(config, task):
    exact(config, ["schema_version", "port", "headless", "viewport", "max_steps", "freshness_ms",
                   "action_timeout_ms", "max_run_ms"], "configuration")
    if config["schema_version"] != 1 or type(config["headless"]) is not bool:
        raise UIError("Invalid schema_version or headless setting.")
    for name, lo, hi in [("port", 1024, 65535), ("max_steps", 1, 4), ("freshness_ms", 100, 60000),
                         ("action_timeout_ms", 100, 10000), ("max_run_ms", 1000, 120000)]:
        bounded(config[name], lo, hi, name)
    exact(config["viewport"], ["width", "height"], "viewport")
    bounded(config["viewport"]["width"], 400, 1600, "viewport.width")
    bounded(config["viewport"]["height"], 300, 1200, "viewport.height")
    exact(task, ["schema_version", "objective", "note", "variant"], "ComputerUseTask")
    if task["schema_version"] != 1 or task["objective"] != "save_local_draft":
        raise UIError("Unsupported ComputerUseTask objective or schema_version.")
    if type(task["note"]) is not str or not 1 <= len(task["note"]) <= 200 or not task["note"].isascii():
        raise UIError("task.note must contain 1..200 ASCII characters of approved synthetic text.")
    if type(task["variant"]) is not str or task["variant"] not in ("clean", "ambiguous", "hidden", "disabled", "injection", "wrong_origin", "egress"):
        raise UIError("Unsupported task.variant.")
    return config, task


def load(directory):
    directory = Path(directory).resolve()
    config, task = validate(read(directory / "config.json"), read(directory / "task.json"))
    # The generated fixture is owned by its generator, never by page content.
    from ui_fixture import html
    if (directory / "fixture.html").read_bytes() != html(task):
        raise UIError("fixture.html differs from its generator; use reset into a new directory.")
    return directory, config, task


def rpc(directory, operation, payload=None):
    directory, config, _ = load(directory)
    session = read(directory / "session.json")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(f"http://127.0.0.1:{config['port']}/rpc/{operation}",
                                    data=canonical(payload or {}), method="POST",
                                    headers={"Authorization": "Bearer " + session["token"],
                                             "Content-Type": "application/json"})
    try:
        with opener.open(request, timeout=config["action_timeout_ms"] / 1000 + 5) as response:
            value = json.loads(response.read(1_000_001))
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UIError("Browser service acknowledgement unavailable; inspect intents before reset. Do not repeat an action.") from None
    if value.get("status") == "failed":
        raise UIError(value["error"])
    return value


def save_record(directory, kind, value):
    record = {"schema_version": 1, "kind": kind, "id": str(uuid.uuid4()),
              "created_ms": time.time_ns() // 1_000_000, "value": value}
    return write_new(Path(directory) / "records" / f"{record['id']}.json", record)


def observe(directory):
    return save_record(directory, "UIObservation", rpc(directory, "observe"))


def record_path(directory, path):
    path = Path(path).resolve()
    if path.parent != Path(directory).resolve() / "records" or path.suffix != ".json":
        raise UIError("Artifact path must be a JSON record in this fixture's records directory.")
    return path


def candidate(snapshot, task):
    if snapshot["note"] != task["note"]:
        return {"label": "fill_note", "target": "note", "argument": task["note"]}
    if snapshot["draft"] != task["note"] or snapshot["save_count"] != 1:
        return {"label": "save_draft", "target": "save", "argument": None}
    return None


def checks(snapshot, task):
    return {"note_matches": snapshot["note"] == task["note"],
            "draft_matches": snapshot["draft"] == task["note"],
            "exactly_one_save": snapshot["save_count"] == 1,
            "expected_revision": snapshot["revision"] == 2}


def cli_result(action):
    try:
        value = action()
        print(json.dumps(value, indent=2, ensure_ascii=False))
        return 0
    except (UIError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc),
                          "next": "Inspect retained records; correct the named input or reset into a new directory."}))
        return 1
