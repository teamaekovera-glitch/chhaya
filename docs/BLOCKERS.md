# BLOCKERS.md — deploy issues live here (§0 rule 9: blocked > 20 min → log and take the §11 fallback)

| Date | Phase | Blocker / exact error | Fallback taken |
| ---- | ----- | --------------------- | -------------- |
| 2026-10-07 | 0 | AWS credentials not yet available in the build environment — `sam build` + `sam deploy` + `curl $ApiUrl/route` are one-command-pending (`docs/DEPLOY.md`); template validated offline (`sam validate`), web built green locally. No AWS error string exists yet. | None needed — scaffold is complete; deploy runs the moment credentials land. |

<!-- Template for the next row: | YYYY-MM-DD | phase | `<exact error string>` | §11 fallback N + one-line note | -->
