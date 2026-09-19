# Decision: Lane C lives in this repo

Date: 2026-09-19
Status: accepted

Lane C (evaluate, sim, openvsp worker, simulation viewport) is vendored into
`leonardo-d-garcia/AITX-Hackathon` on branch `lane-c`.

There is no second copy of the evaluator. The claimed `~/Coding/dronebench`
tree with 217 tests is not on this machine and is not the source of truth.

Lane A/B consume and produce the frozen JSON files. Do not fork those schemas
privately. A contract change requires a note in this folder and updates to
every consumer in the same change.
