# Doctest corpus validation statistics

The most important functional test of the security guardrails: every
`sage:` example in the installed SageMath library, pushed through
`preparse` + `validate_module`, asking whether this server would refuse
the mathematics Sage itself documents. Generated on every run of
`tests/test_sage_doctest_corpus.py`; counts only, never corpus text.

- Generated: 2026-10-05 09:54:03 UTC
- SageMath: 10.10 (`/home/sage/sage/local/var/lib/sage/venv-python3.12/lib/python3.12/site-packages/sage`)
- Verdict fingerprint: `5f005a06e223756854f150e04056d4618a7cff255f3a9f26914026947ad76177`

The fingerprint is a SHA-256 over every example's outcome, refusal
messages in full. It changes whenever any single verdict changes, even
when every count above stays the same.

| Metric | Value |
| --- | ---: |
| Source files | 3,185 |
| Docstrings | 60,681 |
| Examples | 438,124 |
| Accepted | 375,891 |
| Refused | 4,259 |
| Excluded (out of scope by design) | 57,794 |
| Unparsed | 180 |
| **Acceptance (in-scope)** | **98.8797%** |
| Required acceptance | 98.50% |
| Required accepted examples | 250,000 |

## Refused, by rule

In-scope mathematics a guardrail turned away, categorized by the rule
that fired. Every rule here must appear in `DELIBERATE_RULES` with a
ceiling, or `test_every_refusal_is_a_rule_we_meant_to_write` fails.

| Count | Share of in-scope | Rule |
| ---: | ---: | --- |
| 1,961 | 0.5158% | `'X' is not offered: it spawns an external program, and this server does the same mathema` |
| 1,185 | 0.3117% | `'X' is not a name this server offers` |
| 597 | 0.1570% | `Reaching into the 'X' module is not permitted, and 'X' is not offered under any other sp` |
| 212 | 0.0558% | `Reaching into the 'X' module is not permitted; name the function directly: 'X'` |
| 92 | 0.0242% | `Access through 'X' is blocked ('X' is not permitted in Sage executions)` |
| 72 | 0.0189% | `Access to 'X' is blocked: writing files is not available to caller code` |
| 48 | 0.0126% | `'X' may be called but not reached into: latex(expr) builds a string, while its attribute` |
| 38 | 0.0100% | `Call to forbidden function 'X' is blocked` |
| 23 | 0.0061% | `Deleting 'X' is not permitted: it is a name this server provides, and the session keeps ` |
| 17 | 0.0045% | `Call to forbidden attribute 'X' is blocked` |
| 11 | 0.0029% | `Import statements are disabled for Sage executions` |
| 1 | 0.0003% | `Reaching into the 'X' module is not permitted; name the function directly` |
| 1 | 0.0003% | `Reference to forbidden name 'X' is blocked` |
| 1 | 0.0003% | `Access to forbidden function 'X' is blocked` |

## Excluded, by capability

Out of scope by design: doctests using capabilities this server does
not offer (imports, persistence, filesystem, external interfaces, ...).
Counted, not asserted over, and not part of the acceptance rate.

| Count | Share of examples | Capability |
| ---: | ---: | --- |
| 29,382 | 6.7063% | `optional-tag` |
| 19,476 | 4.4453% | `import` |
| 2,276 | 0.5195% | `dunder` |
| 1,912 | 0.4364% | `persistence` |
| 1,328 | 0.3031% | `filesystem` |
| 984 | 0.2246% | `display` |
| 814 | 0.1858% | `repl-magic` |
| 747 | 0.1705% | `interfaces` |
| 717 | 0.1637% | `shell-or-eval` |
| 158 | 0.0361% | `network` |
