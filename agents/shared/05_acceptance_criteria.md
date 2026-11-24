# Acceptance Criteria

> Source: [Tab 22 verbatim export](../raw/tab_22_raw.txt) (Lines 25-28)

```markdown
## Acceptance

- Run `uv run --no-sync pytest -q -ra tests firmware/head/tests` from `code/`, the tracked lint command and receipt verifiers. Run sanitizer, WROOM, Sense, dock and Feather jobs from [host CI](../../../.github/workflows/host-verification.yml). Check the exact result revision, review comments and required check outcomes. Record any host, workflow or toolchain limits with reproduction paths, exact failed commands and affected claims.
- Verify the source-to-physical trace for robot/dock/station using guides [10](10-requirements-and-shopping.md), [40](40-voice-and-proactive-behavior.md), [60](60-object-recall-and-navigation.md) and [70](70-fit-power-manipulation-and-dock.md). Each acceptance row needs source revision, fixture or real assembly ID, operator evidence and status. Treat historical CI and physical evidence from different assemblies as separate records. Keep the PR in its required draft state until the active release policy allows promotion. [Current build guide](../../guides/build.md), [Verification ledger](../../records/verification.md)
```
