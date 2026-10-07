# BLOCKERS.md — deploy issues live here (§0 rule 9: blocked > 20 min → log and take the §11 fallback)

| Date | Phase | Blocker / exact error | Fallback taken |
| ---- | ----- | --------------------- | -------------- |
| 2026-10-07 | 0 | AWS credentials not yet available in the build environment — `sam build` + `sam deploy` + `curl $ApiUrl/route` are one-command-pending (`docs/DEPLOY.md`); template validated offline (`sam validate`), web built green locally. No AWS error string exists yet. | None needed — scaffold is complete; deploy runs the moment credentials land. |

| 2026-10-07 | 2 | `pipeline/upload.py` is fully written and guarded (GRAPH_BUCKET env + `--execute` flag, dry-run default) but ready-not-run: this build environment has no AWS credentials, so no artifact has ever left the machine. | Guard documented in DEPLOY.md §6; upload executes the moment credentials exist (same §11 fallback as the Phase 0 row above). |

| 2026-10-07 | 3 | The Phase 3 cold-start S3 load path (`routing.load_engine_from_env` → boto3 download to /tmp) is implemented and unit-covered for the local-dir variant, but ready-not-verified: this environment has no AWS credentials, so `GRAPH_BUCKET` download, `/tmp` cache reuse on warm invokes, and `S3ReadPolicy` grants have never run. All compute paths (cost matrices, snap, Dijkstra, all three modes) are fully fixture-tested (30 tests). | None needed — deploy + first `POST /route` (DEPLOY.md §7) verifies it with the `ColdStartMs` EMF line; re-read this row if CloudWatch shows a download failure. |

| 2026-10-07 | 4 | LIVE Location calls are untested-pending-key: the Phase 4 frontend ships complete but this build environment has no `VITE_LOCATION_API_KEY`, so Places v2 `SearchText`, map style descriptor, and browser-side `CalculateRoutes` have never executed (unit + mocked tests cover request shapes). ?mock=1 covers the whole UI with synthetic data for screenshots/CI. | On receipt of the key: set `VITE_LOCATION_API_KEY` in Amplify, redeploy, run the DEPLOY.md §4(b) referer check + one live search-and-route; if the style descriptor 403s, add `geo-maps:GetStyleDescriptor` to the key's `AllowActions` (decision sheet §9 fix). |


<!-- Template for the next row: | YYYY-MM-DD | phase | `<exact error string>` | §11 fallback N + one-line note | -->
