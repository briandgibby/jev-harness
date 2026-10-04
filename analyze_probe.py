"""Recompute the live probe summary from recorded evidence; makes no API calls."""
import argparse
import json
from pathlib import Path
import statistics
import sys

import jev_harness as harness


def analyze(base):
    reports = [harness.load_json(base / (phase + "-results.json")) for phase in ("smoke", "battery")]
    if any(report.get("status") != "completed" for report in reports):
        harness.fail("incomplete_probe", "Both probe phases must have completed.")
    if reports[0]["config_hash"] != reports[1]["config_hash"] or reports[0]["cases_hash"] != reports[1]["cases_hash"]:
        harness.fail("inconsistent_probe", "Probe phases used different configuration or cases.")
    rows = [row for report in reports for row in report["results"]]
    groups = {}
    for row in rows:
        record = Path(row["audit_path"]).resolve()
        # Evidence can be moved with the deliverable. Resolve only the recorded basename locally.
        record = base / "audit" / record.name
        replay = harness.replay(record)
        events = [harness._parse_json(line) for line in record.read_bytes().splitlines()]
        terminal = events[-1]
        if row["decision"] != replay["decision"] or row["request_hash"] != replay["request_hash"] or row["response"] != terminal["response"] or row["response_hash"] != replay["response_hash"]:
            harness.fail("inconsistent_probe", "A summary row differs from its audit record.")
        if row["elapsed_ms"] != terminal["elapsed_ms"] or terminal["config_hash"] != reports[0]["config_hash"]:
            harness.fail("inconsistent_probe", "Timing or configuration differs from its audit record.")
        groups.setdefault(row["request_hash"], []).append(row)
    repeats = []
    for request_hash, samples in groups.items():
        if len(samples) < 2:
            continue
        answers = [next(iter(row["response"]["answers"].values())) for row in samples]
        distributions = [answer["probabilities"] for answer in answers]
        repeats.append({"ids": [row["id"] for row in samples], "request_hash": request_hash,
                        "observations": len(samples), "unique_labels": sorted({a["choice"] for a in answers}),
                        "unique_policy_statuses": sorted({row["decision"]["status"] for row in samples}),
                        "unique_distributions": len({harness.canonical_hash(d) for d in distributions}),
                        "max_probability_range": max(max(d[label] for d in distributions) - min(d[label] for d in distributions) for label in distributions[0])})
    latencies = [row["elapsed_ms"] for row in rows]
    return {"status": "completed", "network_called": False, "calls": len(rows),
            "models": sorted({row["response"]["model"] for row in rows}),
            "matches_predeclared_synthetic_label": sum(row["decision"]["label"] == row["expected_label"] for row in rows),
            "accepted": sum(row["decision"]["status"] == "accept" for row in rows),
            "reviewed": sum(row["decision"]["status"] == "review" for row in rows),
            "input_tokens": sum(row["response"]["usage"]["input_tokens"] for row in rows),
            "output_tokens": sum(row["response"]["usage"]["output_tokens"] for row in rows),
            "observed_call_ms": {"min": min(latencies), "median": statistics.median(latencies), "max": max(latencies), "mean": statistics.mean(latencies)},
            "repeated_request_groups": repeats,
            "cases": [{"id": row["id"], "label": row["decision"]["label"], "policy_status": row["decision"]["status"], "selected_probability": row["decision"]["probability"], "confidence": row["decision"]["confidence"]} for row in rows],
            "limitations": "Purposive synthetic sample, including repeats. No production accuracy, calibration, general security, or universal determinism claim. Provider caching unknown; call timing includes client/audit overhead."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(analyze(Path(args.directory).resolve()), indent=2, ensure_ascii=False, allow_nan=False))
        return 0
    except harness.HarnessError as error:
        print(json.dumps(error.report()), file=sys.stderr)
        return 1
    except Exception:
        print(json.dumps({"status": "failed", "message": "Probe evidence could not be analyzed; inspect the phase results and audit files."}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
