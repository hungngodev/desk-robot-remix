# GitHub Actions runner preflight diagnosis

Updated November 11 2026, PR [#17](https://github.com/hungngodev/desk-robot-remix/pull/17).

## Observed, not guessed

All four independent GitHub-hosted jobs (Python/head host, WROOM PlatformIO, Sense ESP-IDF, body C++ sanitizers) returned `conclusion=failure` about two seconds after starting. The GitHub Actions jobs API reports `steps: null` and the separate step listing returns `[]`. Job-log retrieval fails HTTP 404 `BlobNotFound`. Example original run [#43123354367](https://github.com/hungngodev/desk-robot-remix/actions/runs/43123354367), commit `5ad4dcfabbe88797d5f408aff4fdf0811fd7d666`. Later run `43155510253` shows the same four pre-step failures. No source test diagnostics were produced.

This pattern is consistent with runner provisioning, account billing/usage restrictions, repository Actions policy, or service storage incidents, but the available tool does **not** retrieve the check-run annotations required to distinguish them. The source might still contain compile/test defects. Do not alter the locked dependency or CI runner image merely to make a red status disappear.

## Exact one-time operator diagnosis

On a machine with the official GitHub CLI already authenticated for this private repository:

```sh
gh api repos/hungngodev/desk-robot-remix/check-runs/130974405130/annotations --jq '.[] | {level:.annotation_level,title,message}'
gh api repos/hungngodev/desk-robot-remix/actions/jobs/130974405130 --jq '{conclusion,started_at,completed_at,runner_name,steps}'
```

If `gh` is unavailable, open the failed run summary's **Annotations** section in GitHub and capture the exact error message, not a screenshot of an empty job log.

Check repository Settings > Actions > General for enabled runners and allowed actions. Check account Settings > Billing and licensing > Budgets and alerts / Actions usage for a quota, billing hold or zero spending limit. Do **not** enable paid spending without the owner's explicit choice. Check [GitHub Status](https://www.githubstatus.com/) and [official troubleshooting](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows) before changing the workflow.

If the annotation confirms billing, resolve the user-controlled budget/usage issue first. If it confirms a GitHub service issue, request GitHub support with run IDs and error text. If runner provisioning succeeds and a real step emits a compiler or test error, fix the actual logged source regression in PR #17.

## Independent reproducible verification once source is available locally

```sh
cd code
uv python install 3.11
uv sync --extra dev --python 3.11 --locked
uv run --no-sync pytest -q -ra tests firmware/head/tests
uv run --no-sync ruff check laptop/src laptop/server/overlay laptop/server/*.py tests scripts firmware/head/*.py
cd ..
cmake -S code/firmware/body -B /tmp/desk-robot-body-host -DBODY_SANITIZERS=ON -DCMAKE_BUILD_TYPE=Debug
cmake --build /tmp/desk-robot-body-host --parallel 2
ctest --test-dir /tmp/desk-robot-body-host --output-on-failure
uvx --from platformio==6.1.18 pio run -d code/firmware/body -e esp32_full
```

The pinned Xiaozhi Sense build requires its exact upstream fixture, ESP-IDF 6.1, the existing overlay generator and separate flashing trials. Use `.github/workflows/host-verification.yml` for reproducible commands and upstream revisions. Never equate a host-only test with physical AEC, safe charger, calibrated clutch, or assembly.

## Evidence rule

Label tests **committed but not executed** until a terminal or runner records a command, exit code and relevant logs. Keep PR #17 draft; do not merge or describe the finished desk pet as qualified from an annotation-free failed run.

## November 12 refreshed blocker on latest integrated head

The four jobs in [run #43167840502](https://github.com/hungngodev/desk-robot-remix/actions/runs/43167840502) **all completed as failure with zero recorded job steps**:

| Job | Check-run ID | Annotations count | GitHub API output |
| --- | --- | --- | --- |
| Python and head tests | `131013784847` | 2 | empty title, summary and text |
| WROOM PlatformIO firmware compile | `131013784865` | 2 | empty title, summary and text |
| XIAO Sense ESP-IDF compile | `131013784728` | 2 | empty title, summary and text |
| Body C++ sanitizer host tests | `131013784584` | 2 | empty title, summary and text |

The connected GitHub fetch interface **explicitly rejects the check-run annotations endpoint** as unsupported; the two diagnostic annotations per job cannot be retrieved in this chat. Job steps and logs are still absent. This does not prove a billing problem or a code problem. An authorized terminal or the GitHub UI must read the annotations before running another expensive speculative source rewrite:

```sh
gh api repos/hungngodev/desk-robot-remix/check-runs/131013784847/annotations
gh api repos/hungngodev/desk-robot-remix/check-runs/131013784865/annotations
```

Use the two actual messages to distinguish account billing/usage/runner restrictions from malformed workflow config or service faults. No permission to spend money or alter account security is implied. Once a runner actually records real execution steps, run and fix compiler/Python regressions; do not infer green tests from GitGuardian secret scanning.

