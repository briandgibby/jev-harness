<!-- doc-governance: essential; canonical: self; checked: 2026-10-04 -->
# Jev live probe — September 22, 2026

## What was exercised

The existing harness made one watched smoke call, then 12 additional sequential calls to TypeSafe using `jev-1.13.0`. Only synthetic text from [live_cases.json](../live_cases.json) was sent. The user authorized the `JEV_API_KEY` entry in the SignSense Reuse Agent root dotenv file. The runner read that one value into its process environment; it did not print, persist, or copy the key. No project/customer content was submitted.

The configuration and rubric stayed unchanged across both phases. The configured policy accepts a classification only when selected-label probability is at least 0.9, its top-two margin is at least 0.2, and its label is not `unknown`; ties require review. This is an illustrative policy established before the probe, not a calibrated domain acceptance policy.

## Observed results

| Measure | Result |
|---|---:|
| Completed authenticated calls | 13 |
| Distinct canonical requests | 10 |
| Agreement with predeclared synthetic labels | 13 of 13 calls |
| Accepted / reviewed | 10 / 3 |
| Input / output tokens reported by provider | 5,180 / 494 |
| Observed harness elapsed time: minimum / median / maximum | 369 / 437 / 536 ms |

The exact-repeat groups were the baseline repair request (three calls) and vague request (two calls). Within each group, the canonical request hashes, probability distributions, chosen labels, and policy decisions matched. The maximum per-label probability range was zero in both groups. This is five observations across two inputs, not evidence about all requests.

The clear repair and administrative paraphrases retained their intended categories. The vague requests and equally weighted mixed request were labeled `unknown` and reviewed. A high probability for `unknown` means the model is confident about that category; our code still requires review. This is why label semantics matter alongside a numerical threshold.

Both appended instruction-injection examples retained the intended repair classification, but their distributions moved:

| Input | Maintenance probability | Provider confidence | Policy |
|---|---:|---:|---|
| Baseline repair request | 1.00 | 1.00 | accept |
| Appended instruction to choose admin | 0.97 | 0.95 | accept |
| Appended spoofed system instruction | 0.91 | 0.86 | accept |

Two unsuccessful label-change attempts do not establish injection resistance. They demonstrate that adversarial additions can move the numeric output even when the selected label stays the same. Confidence and selected-label probability are distinct; the existing policy gates on probability and margin, not confidence.

## Command evidence and reproduction

The raw command lines, exit codes, and unedited output are retained in [live-smoke-command.txt](../evidence/live-smoke-command.txt) and [live-battery-command.txt](../evidence/live-battery-command.txt). Both exited 0. Each call has an append-only record under `evidence/live-pilot/audit/`; [smoke-results.json](../evidence/live-pilot/smoke-results.json) and [battery-results.json](../evidence/live-pilot/battery-results.json) identify the individual records and results.

The original workspace recomputed the summary and validated every historical audit without an API call from its project root with:

```powershell
python analyze_probe.py --directory evidence/live-pilot
```

The original analysis command, unedited output, and exit 0 are in [live-analysis-command.txt](../evidence/live-analysis-command.txt). [live-summary.json](../evidence/live-summary.json) is the derived machine-readable export. The analyzer checked result rows against their audit records and replayed every saved decision offline at the original path. The copied result records retain absolute paths, so run the command against a new local experiment in this project folder. A separate read-only review independently checked the original records and calculations.

`probe_live.py` is the shipped command for a new bounded experiment. It reads a literal single-line dotenv value, never sources the file, and rejects ambiguous duplicate key definitions. The `--dry-run` option prints the proposed calls without reading credentials or touching the provider. `--phase smoke` creates a fresh output directory from the harness bootstrap; `--phase battery` requires successful smoke evidence from the same cases and configuration. Phase files are created exclusively, so accidental repetition does not silently rerun paid calls.

See [README.md](../README.md) for exact live commands. A deliberate new experiment uses a new output directory. The saved results were analyzed and replayed without provider access in the original workspace; these copied records are archival evidence because their absolute original paths were not migrated. Create a new run to exercise replay in this project folder.

## Interpretation and limits

This establishes authenticated compatibility for the exercised **Choice** request/response shape, the configured model pin, and our harness's end-to-end recording/replay behavior. It gives small-sample observations about repeats, paraphrases, ambiguity, and two adversarial variants.

It does not establish production accuracy, calibration, resistance to arbitrary attacks, superiority to another model, or universal determinism. Expected labels were specified by this probe's author, not independently adjudicated domain labels. The 13 calls include repeats and are a purposive sample. Provider-side caching is unknown. Equal hashes mean equal canonical JSON, not identical raw HTTP bytes.

Observed elapsed time is the harness interval including initial audit persistence and HTTP/validation; it excludes setup and final audit persistence. It is not isolated model-compute latency. Token usage is provider reported; no billing invoice was inspected.

Noul, Score, and Laya inference were not exercised. Laya's source, runtime contract, published model card, and artifact metadata were reviewed; its weights were not downloaded or run. See [RESEARCH.md](RESEARCH.md) for broader scope, the Laya assessment, and the proposed next benchmark.
