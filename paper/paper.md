---
title: 'SageMath MCP: a stateful, sandboxed computer algebra system for language models'
tags:
  - Python
  - SageMath
  - computer algebra
  - Model Context Protocol
  - large language models
  - tool use
  - sandboxing
authors:
  - name: Christoph Steinl
    # OUTLINE: ORCID is required by JOSS for every author. Add it here.
    orcid: 0000-0000-0000-0000
    affiliation: 1
affiliations:
  - name: XBP Europe
    index: 1
date: 23 September 2026
bibliography: paper.bib
---

<!--
OUTLINE STATUS. This is a skeleton, not a submission. JOSS asks for 750-1750
words; the budget per section is in each OUTLINE note. Every figure quoted is
read from a committed artifact, named beside it, so it can be re-checked
before submission. Two things block submission, in order:

1. Research impact (JOSS: "there must be evidence that the software is being
   used for research ... aspirational statements are not sufficient"). We have
   measurements of our own, not use by others. See that section.
2. The author ORCID above, and the author's own sign-off on the AI usage
   disclosure, which JOSS treats as an ethical statement.

Eligibility checked 2026-09-23: public since 2025-11-02 (JOSS minimum is six
months), with development in 2025-11, 2026-04, 2026-08 and 2026-09. The gaps
between those months are the weak point against "ongoing iteration, not a
single burst".

Build the PDF: the "Paper draft" workflow runs on changes under paper/, or
locally with the openjournals/inara Docker image.
-->

# Summary

<!-- OUTLINE: ~150 words, for a non-specialist. What it is, what it is for. -->

Language models are unreliable at exact mathematics. They slip on arithmetic,
algebraic manipulation and anything too large to do in their heads, and they
make these mistakes with confidence. Computer algebra systems don't make those
mistakes, but they need an interface a model can use. `sagemath-mcp` is a
Model Context Protocol [@mcp] server that gives a language model a SageMath
[@sagemath] session. It exposes 40 tools: a general `evaluate_sage` entry point,
33 Sage-backed helpers across calculus, algebra, number theory, combinatorics,
graph and group theory, elliptic curves, coding theory, statistics and
plotting, a `verify_claim` tool that re-checks a stated mathematical claim, and
session and diagnostic tools. Each client gets a dedicated Sage process whose
variables persist across calls, so a model can build a computation up step by
step, the way a person does at the Sage prompt.

# Statement of need

<!-- OUTLINE: ~250 words. The problem, who has it, why existing routes fall
short. Audience: researchers and students who already use an LLM assistant
and SageMath, and tool builders who want exact mathematics behind an agent. -->

Delegating computation to a program improves a model's accuracy on
mathematical problems [@pal; @pot; @toolformer]. Most tool-use work reaches for
Python and SymPy [@sympy]. SageMath covers far more mathematics
(number fields, elliptic curves, modular forms, permutation groups, codes,
combinatorial species), but it is a large, stateful, general-purpose
environment, and in principle a model that can run arbitrary Sage code can do
anything the host process can.

This server addresses three needs together:

- **Exactness with evidence.** Answers come from Sage, not from the model's
  recall. `verify_claim` returns `proved`, `refuted`, `supported` or
  `undecided` together with its evidence, and never reports approximate
  arithmetic as an exact result.
- **State.** Mathematics is incremental. A persistent per-client session, named
  workspaces and an interrupt that keeps variables (as opposed to a restart
  that discards them) match how the system is actually used.
- **Containment.** Model-written code is untrusted input. The server accepts a
  mathematical subset of Sage rather than the whole language (see Software
  design), and it measures what that subset costs.

<!-- OUTLINE: one sentence on who has used it for what, once point 1 of the
status note is resolved. -->

# State of the field

<!-- OUTLINE: ~200 words. JOSS wants why this is a separate package, not a
contribution to an existing one. Keep it factual; cite software by URL. -->

Other MCP servers for SageMath are small and mostly stateless: a
three-tool TypeScript server that is explicitly stateless
[@galoishlee_sagemath], a five-tool server over a Jupyter kernel with named
sessions [@szeider_mcpsage] that backs published neurosymbolic work on graph
constructions [@seka_nesy2026], and wrappers with a handful of tools. The
neighbouring servers draw more attention but wrap other engines: SymPy
[@sympy_mcp], Wolfram|Alpha and Mathematica. None of those surveyed publishes
a measurement of how much legitimate mathematics its interface refuses, which
is the number that makes a code-screening policy accountable.
<!-- OUTLINE: re-read the peers' source before claiming anything about whether
they screen caller code; the 2026-08-24 code read did not record it. -->

Contributing these ideas upstream wouldn't work, because the contribution is
the policy boundary rather than more mathematics. SageMath's own interfaces are
built to execute whatever they are given. The server also uses the modular
passagemath [@passagemath] distribution as an optional runtime, which cuts the
install from a roughly 3 GB container to a roughly 1 GB `pip install`.

<!-- OUTLINE: the Jupyter-kernel design was prototyped and rejected here
(prototypes/jupyter_transport/FINDINGS.md): stock ipykernel executes code the
policy blocks, and startup cost 1010 ms against 463 ms. One sentence. -->

# Software design

<!-- OUTLINE: ~400 words. The trade-offs, not a feature list. This is the
section with the most to say; the risk is running over. -->

**Two locks, and the second is the real boundary.** Caller code is parsed and
checked against a deny-by-default policy: a name is refused unless it appears on
an allowlist or the caller's own code bound it. Imports, `eval`/`exec`, dunder
access, string-path attribute primitives and the Sage helpers that execute,
compile, fetch or unpickle are refused. The allowlist isn't written by hand.
It is generated from the installed Sage by a classifier that stops generation
on any name it cannot place as mathematics, so a dangerous helper added by a
future Sage release stops the build instead of slipping onto the list. The
worker also strips those helpers from its namespace, and the supported deployment is a hardened
non-root container. The AST policy is defence in depth, not the only barrier.

**Measuring the cost of containment.** A policy that refused everything would
pass every security test. The counterweight is a sweep of SageMath's own
documentation: all 432,878 `sage:` doctest examples are pushed through the
validator, and 98.8908% of those in scope are accepted on SageMath 10.9, with
4,153 refused (`doctest-corpus-stats.md`, 2026-09-21). CI fails if acceptance
drops below 98.50%. Executing a 400-docstring sample agreed with Sage's
documented output on all 1,259 comparable examples.

**Adversarial verification.** The security record (`REVIEW_ACTIONS.md`, 95
items) documents every bypass found with its reproduction, fix and regression
test. Generative fuzzers cover the validator, the code-generation gates and
the worker protocol.

**Generated code never trusts caller strings.** The domain helpers build Sage
snippets from templates, and every caller string must pass one of three gates
before it is interpolated. A structural test enforces this.

<!-- OUTLINE: a figure would earn its space here: request flow, from MCP
client to tool to session manager to worker subprocess to AST validation to
exec, with the two locks marked. Source it from the README architecture
diagram. -->

# Research impact statement

<!-- OUTLINE: ~200 words. BLOCKING, see the status note. JOSS requires
evidence of use in research: publications, documented adoption, or
integration in research workflows. What exists today is our own measurement,
which shows the software works but not that anyone depends on it. Collect
before submitting:
  - any paper, thesis or course that used it (ask on sage-devel / Zulip,
    which is on TODO.md anyway);
  - downloads (PyPI, GHCR pulls) and registry listings as supporting, not
    primary, evidence;
  - the conda-forge feedstock once merged.
The measurements below can stay as supporting material. -->

Two committed benchmarks measure what the server changes. On a fixed set of 24
problems scored for mathematical equivalence in Sage, a small model answered
17 correctly by reasoning alone and 24 with Sage compute. The whole difference
was in the compute-heavy tiers, and it included one answer that was wrong but
stated with confidence (`benchmark-stats.md`). On a hard tier of 14 problems a
frontier coding client scored 4/14 without the server and 14/14 with it, using
exactly one tool call per case (`tool-surface-stats.md`).

The server is published on PyPI, as signed container images, and in the
official MCP registry.

# AI usage disclosure

<!-- OUTLINE: JOSS makes this mandatory and treats an incomplete disclosure as
an ethical breach. The draft below is factual from the repository history;
the final assertion is the author's to make, not the tool's. -->

Claude models (Anthropic), used through Claude Code, assisted with a large
share of this software's code, tests and documentation, and with drafting this
paper. Commits carry a `Co-Authored-By` trailer where that assistance occurred.
The security record lists the findings produced by AI-assisted adversarial
review alongside those from human review. <!-- OUTLINE: author to confirm
and complete: "The human author reviewed, edited and validated all
AI-assisted output and made the core design decisions", only if that is
accurate as written. -->

# Acknowledgements

<!-- OUTLINE: the Sage developers; passagemath (Matthias Köppe), including the
upstream Maxima fix (passagemath#2836); anyone who reported issues. Funding,
if any. -->

# References
