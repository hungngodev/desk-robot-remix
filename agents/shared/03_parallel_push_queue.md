# Parallel Push Queue Protocol

> Source: [Tab 22 verbatim export](../raw/tab_22_raw.txt) (Line 6)

```text
Develop and test in parallel. Before pushing to PR #17, check the shared push queue and CI for the current head. If CI is running or another worker has claimed the next push, queue your commit and continue local work. When your turn comes, refresh the branch, push, and record the new commit SHA. The next worker waits for that SHA’s required checks to finish before pushing.
```
