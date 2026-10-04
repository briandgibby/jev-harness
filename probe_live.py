"""Bounded research probe; reads one authorized dotenv key without disclosure."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

import jev_harness as harness


def read_key(path, name):
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", name):
        harness.fail("credential_config", "key-name must be an uppercase environment name.")
    try:
        raw = Path(path).read_bytes()
        if len(raw) > 1_000_000:
            harness.fail("credential_config", "The dotenv file exceeds the supported size.")
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeError):
        harness.fail("credential_config", "The authorized dotenv file could not be read as UTF-8.", "Check the dotenv path and permissions.")
    matches = []
    for line in text.splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if match and match.group(1) == name:
            value = match.group(2).strip()
            if value[:1] in ("'", '"'):
                quote = value[0]
                end = value.find(quote, 1)
                if end < 1 or (value[end + 1:].strip() and not value[end + 1:].lstrip().startswith("#")):
                    harness.fail("credential_config", "The selected dotenv value has unsupported quoting.")
                value = value[1:end]
            else:
                value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
            if not value or any(ord(c) < 33 or ord(c) > 126 for c in value) or any(c in value for c in "$\\'\""):
                harness.fail("credential_config", "The selected dotenv key is empty or uses unsupported syntax.", "Use a literal, single-line provider key without interpolation.")
            matches.append(value)
    if len(matches) != 1:
        harness.fail("credential_config", "The selected credential name must occur exactly once in dotenv.", "Check key-name and remove ambiguous duplicate definitions.")
    return matches[0]


def save_new(path, data):
    try:
        with path.open("x", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, allow_nan=False, indent=2)
            output.write("\n")
    except OSError:
        harness.fail("probe_record_failed", "The probe evidence file could not be created exclusively.", "Inspect existing evidence and choose a fresh output directory for a new probe.")


def load_cases(path):
    suite = harness.load_json(path)
    harness._object(suite, "probe suite", {"cases"}, {"cases"})
    cases = suite["cases"]
    if type(cases) is not list or not 1 <= len(cases) <= 13:
        harness.fail("invalid_probe", "The probe must define between 1 and 13 cases.")
    states, resolved = {}, []
    for case in cases:
        harness._object(case, "probe case", {"id", "expected_label", "purpose"}, {"id", "state", "repeat_of", "expected_label", "purpose"})
        if ("state" in case) == ("repeat_of" in case):
            harness.fail("invalid_probe", "Each case needs either state or repeat_of.")
        if "repeat_of" in case:
            if type(case["repeat_of"]) is not str or case["repeat_of"] not in states:
                harness.fail("invalid_probe", "repeat_of must reference an earlier case.")
            state = states[case["repeat_of"]]
        else:
            state = case["state"]
        item = harness.validate_input({"id": case["id"], "state": state})
        if item["id"] in states:
            harness.fail("invalid_probe", "Probe IDs must be unique.")
        for name in ("expected_label", "purpose"):
            harness._string(case[name], "probe." + name, 500)
        states[item["id"]] = state
        resolved.append({**item, "expected_label": case["expected_label"], "purpose": case["purpose"]})
    return resolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dotenv", required=True)
    parser.add_argument("--key-name", required=True)
    parser.add_argument("--cases", default=str(Path(__file__).with_name("live_cases.json")))
    parser.add_argument("--out", required=True)
    parser.add_argument("--phase", required=True, choices=("smoke", "battery"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    attempted, completed, base = 0, [], Path(args.out).resolve()
    try:
        cases = load_cases(args.cases)
        chosen = cases[:1] if args.phase == "smoke" else cases[1:]
        if not chosen:
            harness.fail("invalid_probe", "The selected phase has no cases.")
        if args.dry_run:
            print(json.dumps({"phase": args.phase, "max_requests": len(chosen), "case_ids": [c["id"] for c in chosen], "data": "supplied synthetic case file", "credential_read": False, "network_called": False}))
            return 0
        if args.phase == "smoke":
            harness.initialize(base)
        else:
            smoke = harness.load_json(base / "smoke-results.json")
            if smoke.get("status") != "completed" or smoke.get("cases_hash") != harness.canonical_hash(cases):
                harness.fail("invalid_probe", "A successful smoke from this unchanged case suite is required first.")
        config = harness.validate_config(harness.load_json(base / "config.json"))
        for case in chosen:
            if case["expected_label"] not in config["question"]["criteria"]:
                harness.fail("invalid_probe", "A probe expected_label is absent from configured criteria.")
            if len(harness._canonical_bytes({"id": case["id"], "state": case["state"]})) > config["max_input_bytes"]:
                harness.fail("invalid_probe", "A probe input exceeds max_input_bytes.")
        if args.phase == "battery" and smoke["config_hash"] != harness.canonical_hash(config):
            harness.fail("invalid_probe", "The configuration changed since smoke; start a new probe.")
        save_new(base / (args.phase + "-started.json"), {"status": "started", "phase": args.phase, "max_requests": len(chosen), "cases_hash": harness.canonical_hash(cases), "config_hash": harness.canonical_hash(config)})
        # Only the chosen dotenv value enters this process environment. Nothing is sourced or executed.
        os.environ[config["api_key_env"]] = read_key(args.dotenv, args.key_name)
        try:
            for case in chosen:
                attempted += 1
                result = harness.run_one(config, base, {"id": case["id"], "state": case["state"]}, "live")
                row = {"id": case["id"], "purpose": case["purpose"], "expected_label": case["expected_label"], "matches_expected": result["decision"]["label"] == case["expected_label"], "decision": result["decision"], "response": result["response"], "request_hash": result["request_hash"], "response_hash": result["response_hash"], "elapsed_ms": result["elapsed_ms"], "audit_path": result["audit_path"]}
                completed.append(row)
                print(json.dumps({"event": "case_completed", **row}, ensure_ascii=False), flush=True)
        finally:
            os.environ.pop(config["api_key_env"], None)
        report = {"status": "completed", "phase": args.phase, "attempted": attempted, "cases_hash": harness.canonical_hash(cases), "config_hash": harness.canonical_hash(config), "results": completed, "limitations": "Small synthetic probe; no production accuracy, calibration, security, or universal determinism claim. Fresh HTTP calls do not prove absence of provider caching."}
        save_new(base / (args.phase + "-results.json"), report)
        print(json.dumps({"event": "phase_completed", "phase": args.phase, "completed": len(completed), "report": str(base / (args.phase + "-results.json"))}), flush=True)
        return 0
    except harness.HarnessError as error:
        print(json.dumps({**error.report(), "phase": args.phase, "attempted": attempted, "completed": len(completed), "evaluation_incomplete": True}), file=sys.stderr)
        return 1
    except Exception:
        print(json.dumps({"status": "failed", "phase": args.phase, "attempted": attempted, "completed": len(completed), "message": "Unexpected probe error; inspect retained audit evidence. No automatic retry occurred."}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
