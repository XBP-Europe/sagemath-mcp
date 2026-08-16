# Doctest corpus validation statistics

The most important functional test of the security guardrails: every
`sage:` example in the installed SageMath library, pushed through
`preparse` + `validate_module`, asking whether this server would refuse
the mathematics Sage itself documents. Generated on every run of
`tests/test_sage_doctest_corpus.py`; counts only, never corpus text.

- Generated: 2026-08-16 20:45:58 UTC
- SageMath: 10.9 (`/home/sage/sage/local/var/lib/sage/venv-python3.12/lib/python3.12/site-packages/sage`)

| Metric | Value |
| --- | ---: |
| Source files | 3,168 |
| Docstrings | 60,094 |
| Examples | 432,878 |
| Accepted | 370,492 |
| Refused | 3,936 |
| Excluded (out of scope by design) | 58,268 |
| Unparsed | 182 |
| **Acceptance (in-scope)** | **98.9488%** |
| Required acceptance | 98.50% |
| Required accepted examples | 250,000 |

## Refused, by rule

In-scope mathematics a guardrail turned away, categorized by the rule
that fired. Every rule here must appear in `DELIBERATE_RULES` with a
ceiling, or `test_every_refusal_is_a_rule_we_meant_to_write` fails.

| Count | Share of in-scope | Rule |
| ---: | ---: | --- |
| 2,026 | 0.5411% | `'X' is not offered: it spawns an external program, and this server does the same mathema` |
| 1,642 | 0.4385% | `'X' is not a name this server offers` |
| 130 | 0.0347% | `Access through 'X' is blocked ('X' is not permitted in Sage executions)` |
| 69 | 0.0184% | `Access to 'X' is blocked: writing files is not available to caller code` |
| 38 | 0.0101% | `Call to forbidden function 'X' is blocked` |
| 17 | 0.0045% | `Call to forbidden attribute 'X' is blocked` |
| 11 | 0.0029% | `Import statements are disabled for Sage executions` |
| 2 | 0.0005% | `Access to forbidden function 'X' is blocked` |
| 1 | 0.0003% | `Reference to forbidden name 'X' is blocked` |

## Excluded, by capability

Out of scope by design: doctests using capabilities this server does
not offer (imports, persistence, filesystem, external interfaces, ...).
Counted, not asserted over, and not part of the acceptance rate.

| Count | Share of examples | Capability |
| ---: | ---: | --- |
| 30,219 | 6.9810% | `optional-tag` |
| 19,149 | 4.4236% | `import` |
| 2,257 | 0.5214% | `dunder` |
| 1,915 | 0.4424% | `persistence` |
| 1,327 | 0.3066% | `filesystem` |
| 978 | 0.2259% | `display` |
| 813 | 0.1878% | `repl-magic` |
| 747 | 0.1726% | `interfaces` |
| 706 | 0.1631% | `shell-or-eval` |
| 157 | 0.0363% | `network` |
