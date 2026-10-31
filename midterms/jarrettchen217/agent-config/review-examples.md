# Review findings (examples)

Two independent review passes run during midterm packaging (2026-10-31), each by a read-only reviewer subagent that did
not write the change. The reviewer saw the task, the acceptance criteria, the git range and the check output, not the
implementer's reasoning. Every finding was fixed before the change was merged.

## Model interface (Hybrid model chosen by manifest)

| Finding | Fix | Now checked by |
| --- | --- | --- |
| The watch-mode hint still printed `u19588` when a different model was loaded | The label comes from the loaded model, and a fallback is marked `(fallback)` | `tests/test_model_registry.py::test_watch_hint_names_the_loaded_model`, `test_play_world_labels_the_loaded_model` |
| Malformed manifests (a swapped tensor shape, a missing offset, `floats: null`, a tensor overrunning the file, a JSON list) either crashed or loaded | Every malformed manifest raises a contract error, and the game falls back to the bundled default | `test_malformed_manifests_are_contract_errors_that_fall_back` |
| The documented test command ran under the wrong interpreter | Commands use the project's locked environment (`uv run --frozen …`) | README commands, CI |
| The claim of web/desktop forward-pass parity was stronger than the evidence | Reworded to "identical logits on synthetic inputs only" | (wording) |

## Branch consolidation docs

| Finding | Fix |
| --- | --- |
| The two-branch policy did not mention the one remaining archive branch | Named as a known exception |
| Task routing between the game line and the RL line was unstated | Routing rule added |
| The history of a retired research branch was described inaccurately | Corrected: it survives only in its archive tag |
| The pull-request text had stale lines | Updated before merge |
