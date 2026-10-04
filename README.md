<!-- doc-governance: essential; canonical: self; checked: 2026-10-04 -->
# Jev Harness

A local Python CLI for one configurable Choice classification question, deterministic acceptance rules, inspectable audit records, offline replay, and bounded labeled evaluation. It returns recommendations; it does not execute business actions.

Read [the broader Jev/Laya scope and adoption plan](docs/RESEARCH.md), [live probe results](docs/LIVE_RESULTS.md), [requirements](docs/PRD.md), and [observed verification](docs/walkthrough.md).

## One-task coding orchestration experiment

The separate `orchestrate.py` CLI now combines one Jev Choice observation, a code-owned route, one coding-model response, strict JSON replacement of declared files, and protected Docker evaluation. Its [PRD](docs/PRD-Jev-Orchestration-Harness.md), [PRS](docs/PRS-Jev-Orchestration-Harness.md), and [build packet](docs/build-tasks/jev-orchestration-harness/PRD.md) track the broader goal and remaining gaps. `init` creates either the simple `add(a, b)` fixture with three protected checks or, with `--fixture-complexity complex`, an interval-merge fixture with six protected checks. These are bounded examples, not a model-quality benchmark.

From this directory, with Python 3.14.6, Git, and a Linux/amd64 Docker engine, inspect and verify the pinned verifier image before a fresh fixture run. The shipped preparation command can install it on an empty Docker cache after its bounded dry-run; the tested host already had the image, so only `dry-run` and `verify` were exercised:

```powershell
pwsh -NoProfile -File tools/prepare_verifier.ps1 -Action dry-run
pwsh -NoProfile -File tools/prepare_verifier.ps1 -Action verify
```

If `verify` names a missing image, run `pwsh -NoProfile -File tools/prepare_verifier.ps1 -Action install` once after inspecting the dry-run, then verify again. The fixture uses generated state and makes no model request:

```powershell
python -B orchestrate.py init --directory demo-orchestration
python -B orchestrate.py dry-run --directory demo-orchestration --mode fixture --jev-mode fixture
$demoRun = python -B orchestrate.py demo --directory demo-orchestration | ConvertFrom-Json
python -B orchestrate.py inspect --run-dir $demoRun.run_dir
python -B orchestrate.py replay --run-dir $demoRun.run_dir
```

`init` refuses a nonempty directory. `demo` writes to its generated isolated checkout and executes the evaluator in `docker.io/library/python@sha256:b921fe7e7522f828d45197a47656ec465a9b15689b27fa8e1fba2864fca5b967` with no network, a read-only root and checkout, and dropped Linux capabilities. [Verifier image preparation](tools/prepare_verifier.ps1) reads the image pin from `orchestrate.py`, checks the registry manifest and local Linux/amd64 identity, and refuses an install over an existing image. Keep the generated evaluator and Git base intact because their hashes are checked before each run.

For a rules-only fixture control, run `python -B orchestrate.py run --directory demo-orchestration --mode fixture --jev-mode off --route-source baseline`. That mode makes zero Jev calls. Fixture and live Jev modes retain a Jev observation; the baseline still owns the route unless experimental Jev control is requested.

`local_model.py probe` can send one bounded synthetic prompt to an already running OpenVINO Model Server (OVMS) on loopback. The Windows setup script currently supports a no-write scope check for each pinned coding model:

```powershell
pwsh -File tools/setup_ovms.ps1 -Action dry-run -Model fast
pwsh -File tools/setup_ovms.ps1 -Action dry-run -Model strong
python -B local_model.py probe --endpoint http://127.0.0.1:8765/v1/chat/completions --model qwen25-coder-7b-int4 --max-tokens 64 --timeout-seconds 120
```

The script also exposes `-Action install`, `serve`, and read-only `verify`. A separate fast-model installation and serve completed at loopback port 8766, and a later `verify` passed pinned archive and model-file checks; the strong-model script install/serve path has not been tested. Its model downloads are several gigabytes, so inspect the dry-run's paths and byte limits before a watched install. [model-pins.json](model-pins.json) owns the two OpenVINO model IDs, revisions, and expected artifact metadata; both `init` and the [setup script](tools/setup_ovms.ps1) read it, and controller load rejects identity/revision drift. The controller still does not verify installed artifact hashes, server version, or device during a run.

For one watched local coding attempt, first start the matching pinned model under OVMS, set `--fast-endpoint` and `--strong-endpoint` during `init` if their loopback ports differ from the defaults (8000 and 8001), and inspect the exact scope. Each registration needs its own correctly named OVMS server; one endpoint cannot answer for both model IDs:

```powershell
python -B orchestrate.py dry-run --directory demo-orchestration --mode live --jev-mode fixture --route-source baseline
python -B orchestrate.py run --directory demo-orchestration --mode live --jev-mode fixture --route-source baseline --watch
```

The live command requires an interactive terminal and typed `yes`; it makes at most one coding-model call and one Docker verification call. With `--jev-mode fixture`, Jev's answer is synthetic. `--jev-mode live` makes one TypeSafe call using the `JEV_API_KEY` environment variable, or a literal dotenv key supplied by `--dotenv`; only the generated approved routing summary is sent, not source files. `--route-source jev` is an experimental one-run option and requires `--experimental-jev-route` in live coding mode. There is no held-out promotion gate, automatic repair, or claim that Jev routes better than rules. A failed call leaves an inspectable run and never falls back to a fixture response.

Current-format evidence includes a watched [rules-only strong-model interval-merge run](evidence/orchestration-proof-interval/runs/87f75c56-e81b-4e12-9676-6f9f9c541921/events.jsonl) with [six-test trusted verdict](evidence/orchestration-proof-interval/runs/87f75c56-e81b-4e12-9676-6f9f9c541921/verifier.stdout), and a watched [experimental Jev-routed fast-model add run](evidence/orchestration-proof-add/runs/54cf2c0e-dc53-417a-bf8f-bb51675d1472/events.jsonl) with [three-test trusted verdict](evidence/orchestration-proof-add/runs/54cf2c0e-dc53-417a-bf8f-bb51675d1472/verifier.stdout). Both replayed with saved evaluator/model/patch/checkout checks at the original workspace. These copied historical records are static archival proof: their nested fixture Git histories and absolute original paths were intentionally not migrated, so use a newly created run for `inspect` and `replay` in this project folder. A separate evaluator audit reproduced a false-green path in which candidate code could exit the old evaluator before tests; the current evaluator runs candidate calls in child processes and requires a trusted test-count verdict. A direct [OpenVINO device query and fast OVMS command line](docs/build-tasks/jev-orchestration-harness/evidence/ovms-device-map.md) map `GPU.1` to Arc Pro B70 and show explicit targeting on the 7B server's port 8766. The controller does not yet bind server PID/device/artifact proof to individual runs. The two models solved different generated tasks, so there is no paired model or Jev-routing quality comparison. The [implementation walkthrough](docs/build-tasks/jev-orchestration-harness/walkthrough.md) records what was observed and what remains unfinished.

## First run

Use Python **3.14.6**, pinned in `.python-version`. There are no third-party runtime dependencies or installation steps. Run these commands from this directory:

```powershell
python --version
python jev_harness.py init --directory demo
python jev_harness.py run --config demo/config.json --input demo/input.json --mode fixture
python jev_harness.py evaluate --config demo/config.json --dataset demo/dataset.json --mode fixture
```

`init` creates the configuration, input record, synthetic response fixtures, and labeled dataset. It refuses to replace an existing nonempty directory. Use a fresh directory name for another bootstrap. Fixture runs make no API calls; their labels and metrics verify plumbing only.

The generated `config.json` is the operator configuration surface. It contains the pinned model, endpoint, credential environment-variable name, question/label definitions, thresholds, input limit, timeout, and local paths. Invalid settings are rejected. Change a rubric or threshold there without rebuilding. Set `review_labels` to labels that must always be reviewed. The source module owns default generation and schema bounds.

The input is a JSON object with `id` and `state`. State may be a text string, object, or array. Files use UTF-8 JSON. The local pilot deliberately accepts a narrower question configuration than the full provider API: one Choice question with textual instructions and textual label definitions.

## Replay

Capture the absolute `audit_path` returned by a successful run:

```powershell
$jevRun = python jev_harness.py run --config demo/config.json --input demo/input.json --mode fixture | ConvertFrom-Json
python jev_harness.py replay --record $jevRun.audit_path
```

Replay checks recorded hashes and recomputes the recommendation from the saved policy and response. It makes no network request and does not use a changed current config. This verifies historical policy reproducibility, not the consistency of fresh Jev inference. Audit hashes are not digital signatures.

## Live access

The current adapter implements [TypeSafe's direct HTTP API](https://docs.typesafe.ai/api), with a pinned model from the [official model list](https://docs.typesafe.ai/models). Obtain access through the [TypeSafe console](https://console.typesafe.ai/), then make the configured `TYPESAFE_API_KEY` environment variable available to the process through your normal secret-management mechanism. Keep the key out of these files and chat.

Once configured, the following command sends **one record** to TypeSafe and may incur provider charges. Begin with the generated synthetic input and watch the result and audit:

```powershell
python jev_harness.py run --config demo/config.json --input demo/input.json --mode live
```

A missing key is an error. A live failure never becomes a fixture response. There are no automatic retries. This adapter does not accept another gateway as if it were TypeSafe. Supporting another provider requires verifying its request, authentication, and response contract.

## Bounded dotenv probe

An authenticated 13-call synthetic probe has now been recorded. The existing core source is unchanged. To inspect that evidence offline:

```powershell
python analyze_probe.py --directory evidence/live-pilot
```

For a deliberate new probe using the authorized credential location, run from this directory. Dry-run prints scope without reading the key or calling the network:

```powershell
python probe_live.py --dotenv 'C:\Users\bdgibby\Git\signsense-reuse-agent\.env' --key-name JEV_API_KEY --out evidence/new-live-pilot --phase smoke --dry-run
python probe_live.py --dotenv 'C:\Users\bdgibby\Git\signsense-reuse-agent\.env' --key-name JEV_API_KEY --out evidence/new-live-pilot --phase smoke
```

Inspect the one-call result before the remaining phase, which sends at most 12 additional synthetic requests:

```powershell
python probe_live.py --dotenv 'C:\Users\bdgibby\Git\signsense-reuse-agent\.env' --key-name JEV_API_KEY --out evidence/new-live-pilot --phase battery --dry-run
python probe_live.py --dotenv 'C:\Users\bdgibby\Git\signsense-reuse-agent\.env' --key-name JEV_API_KEY --out evidence/new-live-pilot --phase battery
python analyze_probe.py --directory evidence/new-live-pilot
```

These live commands incur provider usage. Choose a new output directory for a new experiment; existing phase markers prevent accidental reruns. `live_cases.json` owns the probe scenarios; `--cases` can select another bounded case file. The credential is never written to output. The runner accepts literal single-line dotenv values and does not execute or expand dotenv contents. The generated configuration owns the rubric and policy; battery requires the same configuration and case definitions as smoke. See [LIVE_RESULTS.md](docs/LIVE_RESULTS.md) for what the small sample establishes and what remains unknown.

## Evaluation and operating limits

`evaluate` accepts a JSON object containing `items`, each with `id`, `state`, and `expected_label`; the entire dataset is validated before calls begin. A run is limited to 20 items. The report separates accuracy across all predictions from accuracy among accepted classifications and the fraction accepted. A failure aborts the evaluation with explicit partial progress rather than a success-shaped partial report.

Thresholds in the generated demo are examples, not validated probabilities of correctness. A `review` result is a normal outcome; a dependency/validation error is a failed command. Exact ties require review. `accept` only means that the label met the configured policy, not that it is certainly correct or that an external action is authorized.

Audit files contain input state, the request, and the provider response. Use a suitably protected local folder and approved input data. The key itself is not recorded. The program creates audit files exclusively and appends events; it does not delete existing state. Incomplete started records remain inspectable if the process is interrupted.

The input byte cap is a local safeguard, not a token counter or proof that a request fits the provider context window. Keep the first pilot small. The bounded synthetic probe includes a few repeated calls; a representative benchmark remains future work. No schedule, automatic review resolution, batching beyond the stated bound, Noul/Score adapter, Laya runtime, calibration, or production connector is included.

## Local verification

```powershell
python -B -m unittest discover -s tests -v
python jev_harness.py --help
```

The tests are under `tests/`; the [walkthrough](docs/walkthrough.md) links the original command outputs and identifies which claims remain unverified. The [implementation plan](docs/implementation_plan.md) explains each file's responsibility.
