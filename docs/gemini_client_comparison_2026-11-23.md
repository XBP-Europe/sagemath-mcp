# Gemini client comparison (2026-11-23)

This is a small diagnostic sample, not a release pass or an estimate of a
stable success rate. It compares the pre-guidance server at `9f87838` with
PR #309's candidate server at `dde2bd2`. Both ran in separate SageMath 10.10
containers with identical installed package versions. The same candidate
harness, standard tier, full tool catalogue, Gemini CLI 0.70.0, and requested
`gemini-3.8-flash` model were used throughout. Three repetitions per side were
interleaved in the order baseline, candidate, candidate, baseline, baseline,
candidate. No random seed or provider-side model immutability was controlled.

Each repetition ran the same anharmonic-oscillator, Mercury and Bessel-zero
cases. Counts include all tool errors, including mathematical errors the strict
harness may tolerate. An expected value in a configured output field after an
error is supporting evidence; it does not prove that the client used it.

| Server | Run | Strict passes | Correct answers | Recovered / response-matched | Tool errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 1 | 0/3 | 3/3 | 3 / 3 | 3 |
| Baseline | 2 | 1/3 | 3/3 | 2 / 2 | 3 |
| Baseline | 3 | 1/3 | 3/3 | 2 / 2 | 2 |
| Candidate | 1 | 2/3 | 3/3 | 1 / 1 | 1 |
| Candidate | 2 | 1/3 | 3/3 | 2 / 2 | 3 |
| Candidate | 3 | 3/3 | 3/3 | 0 / 0 | 0 |
| **Baseline total** | | **2/9** | **9/9** | **7 / 7** | **8** |
| **Candidate total** | | **6/9** | **9/9** | **3 / 3** | **4** |

The candidate had fewer observed errors in this sample, but the sample is too
small to attribute the difference to guidance or to establish a reliable rate.
The results do not meet the default release criterion of a full strict pass.
Classification was recalculated consistently from the retained full traces
after the comparison exposed two additional policy-refusal wordings; the raw
run summaries were not rewritten. Full traces remain private and are not part
of this repository. See [TESTING.md](../TESTING.md#client-integration-claude-gemini-codex)
for retention, sanitization, and release-decision guidance.
