# Jev Harness execution brief

## Mission

Research and implement the Choice pilot authorized by the user. The continuation authorizes a bounded authenticated synthetic probe using an existing dotenv key and read-only research of Receptron's Laya repository. The completed probe establishes exercised API compatibility, not domain quality. Keep general adoption work scoped by the research and representative data. Do not initialize or publish a repository, install/run Laya as part of research, schedule work, or execute downstream business actions.

## References

Read [PRD.md](PRD.md), [implementation_plan.md](implementation_plan.md), and [task_checklist.md](task_checklist.md). The research document supplies the primary-source evidence. The code owns the local configuration schema; generated bootstrap files are its outputs, not independently maintained defaults.

## Workflow instructions

Follow the dependency order in the plan. Mark one checklist item in progress per active implementer, and mark completed only after a corresponding check. Preserve unrelated work. No silent fallback, no unpinned dependencies, no credentials in logs, no overwriting existing state. When diagnosing a bug, produce a failing reproduction before changing code and rerun it after the fix. State the one variable changed. Keep tests meaningful.

The first watched execution is local and bounded; the live continuation performs one smoke before at most 12 further calls (FR-07). Fixture outputs must be identified as synthetic, and live synthetic probes must be distinguished from domain benchmarks. The live transport must name a missing credential setting and stop. Credentials are loaded literally without executing dotenv contents and are never written or displayed. Model output is evidence consumed by deterministic code, not an authorization source or a connector between components. Reconcile these documents if implementation changes.

## Verification and deliverables

From the deliverable root run `python --version`, `python jev_harness.py --help`, and `python -m unittest -v`. Use `init` to bootstrap a fresh temporary directory, run one fixture record, replay the returned audit path, and evaluate the generated small dataset. Capture each command and its unedited output in `evidence/`.

For the live continuation, exact commands and unedited output are linked from `LIVE_RESULTS.md`. From the deliverable root, `python analyze_probe.py --directory evidence/live-pilot` verifies the existing probe offline without credentials or spending. A new paid probe must use a new output directory and preserve the watched smoke/battery sequence.

Deliver source, tests, runtime pin, research, usage guide, this packet, and an evidence-based walkthrough. Report actual limits: the recorded live probe establishes only the exercised Choice contract and small-sample observations. Predictive quality, calibration, broad fresh-call consistency, Laya runtime behavior, and production readiness require further evidence. No confidence or probability threshold is a domain accuracy guarantee.
