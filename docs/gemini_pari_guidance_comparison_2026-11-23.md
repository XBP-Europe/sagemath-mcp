# Gemini PARI guidance comparison (2026-11-23)

This small diagnostic sample compares merged `main` at `9c5575756d7e5f5f6584e5141e3a18cff31aafcd` with the guidance change at `125d5e08c4ea8cf99945094d3a1ef5b970d9acb5`. It is not a release pass or an estimate of a stable success rate. The candidate removes advice to call `.pari()` on an arbitrary Sage object and suggests native Sage functions and bracketed Bessel root finding.

The same candidate harness, standard tier, full tool catalogue, Gemini CLI 0.70.0 and requested `gemini-3.8-flash` model were used throughout. Separate containers used the same SageMath 10.10 image (`sha256:63392d91bfe8404c2a2a56b94ff30988dfc8ebdac6d9850755594641d94e5e4b`) and matching installed package versions. Three repetitions per side were interleaved baseline, candidate, candidate, baseline, baseline, candidate. A local Python test suite ran concurrently with part of the first baseline and candidate runs; execution times are therefore not comparable. No random seed or provider-side model immutability was controlled. The initially rejected, untrusted workspace registration ran no cases and is excluded.

| Server | Run | Strict passes | Correct answers | Recovered / response-matched | Tool errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 1 | 1/3 | 3/3 | 2 / 2 | 3 |
| Baseline | 2 | 1/3 | 3/3 | 2 / 2 | 2 |
| Baseline | 3 | 0/3 | 3/3 | 3 / 3 | 3 |
| Candidate | 1 | 3/3 | 3/3 | 0 / 0 | 0 |
| Candidate | 2 | 1/3 | 3/3 | 2 / 2 | 2 |
| Candidate | 3 | 2/3 | 3/3 | 1 / 1 | 1 |
| **Baseline total** | | **2/9** | **9/9** | **7 / 7** | **8** |
| **Candidate total** | | **6/9** | **9/9** | **3 / 3** | **3** |

The cases were the anharmonic oscillator, Mercury precession and Bessel zero. An expected value in a configured output field after an error is supporting evidence; it does not prove that the client used it. The candidate had fewer observed errors, but this sample is too small to establish a reliable improvement or attribute it to the change. It does not meet the default release criterion of a full strict pass. Failures still included attempted imports, unknown names, and symbolic formatting.

The current error-category classifier is not reliable for all refusals: in baseline run 3 it classified the unknown name `bessel_zeros` as a timeout because the generic refusal mentions a timeout as a possible cause of lost session variables. The table uses error counts and strict outcomes, which that category label does not change. Full traces are retained privately outside the repository; they may contain prompts and tool data. See [TESTING.md](../TESTING.md#client-integration-claude-gemini-codex) for retention, sanitization, and release-decision guidance.
