// Outcome benchmark for the SageMath MCP server.
//
// Measures the core credibility claim the roadmap asks for: does the model get
// more mathematics right when it can run Sage, versus reasoning alone? Two arms
// over a fixed case set (benchmarks/cases.json):
//   - no_tools : the model must answer by reasoning only, no execution.
//   - sage     : the model may run Sage (docker exec sage-mcp) to compute/verify.
// Each cohort's answers are then scored INDEPENDENTLY for mathematical
// equivalence in the same Sage, never string-matched.
//
// Run:  Workflow({ scriptPath: "benchmarks/outcome_benchmark.workflow.js",
//                  args: <parsed cases.json> })
// The case set is passed in as `args` so the script has a fixed, seeded input.
//
// Honest limitation: "no_tools" is prompt-enforced (the subagent is told not to
// execute anything and self-reports zero tool calls), not hard tool-gated. The
// rigorous 3-arm version -- no-tools / evaluate_sage-only / full-catalogue with
// real tool gating -- is the tests/cli_integration harness, which runs under the
// CLI nightlies with API keys. This measures the model in the loop as much as
// the server, and is never CI-gated.

export const meta = {
  name: 'outcome-benchmark',
  description: 'Measure the math-accuracy delta from Sage compute vs reasoning alone on a fixed case set',
  phases: [
    { title: 'Solve', detail: 'each (tier, arm) cohort solves its problems' },
    { title: 'Score', detail: 'check every answer for equivalence in Sage' },
  ],
}

const cases = args.cases
const tiers = [...new Set(cases.map((c) => c.tier))]
const arms = ['no_tools', 'sage']

// The subject under test is a fast, lower-tier model on purpose: a frontier
// model solves this whole set unaided (zero delta), so it cannot show what the
// tool adds. Both arms use the SAME subject -- the only variable is Sage access.
// Scoring is a separate concern (reliable equivalence-checking), so the judge is
// a step up. Override via args.subjectModel / args.judgeModel.
const SUBJECT_MODEL = args.subjectModel || 'haiku'
const JUDGE_MODEL = args.judgeModel || 'sonnet'

const SOLVE_SCHEMA = {
  type: 'object',
  properties: {
    answers: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          answer: { type: 'string' },
          refused: { type: 'boolean' },
          confident: { type: 'boolean' },
          tool_calls: { type: 'integer' },
        },
        required: ['id', 'answer', 'refused', 'confident', 'tool_calls'],
      },
    },
  },
  required: ['answers'],
}

const SCORE_SCHEMA = {
  type: 'object',
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          correct: { type: 'boolean' },
          note: { type: 'string' },
        },
        required: ['id', 'correct'],
      },
    },
  },
  required: ['verdicts'],
}

function solvePrompt(tierCases, arm) {
  const probs = tierCases.map((c) => `[${c.id}] ${c.problem}`).join('\n')
  if (arm === 'no_tools') {
    return (
      'You are being evaluated on UNAIDED mathematical ability. Solve each ' +
      'problem by reasoning and hand computation ONLY. Do NOT run any command, ' +
      'script, calculator, or computer-algebra system -- no Bash, no code ' +
      'execution of any kind, no docker. Work each out yourself.\n\n' +
      `Problems:\n${probs}\n\n` +
      'Return one entry per problem: id, answer (the FINAL answer only, as a ' +
      'plain mathematical expression -- e.g. "213", "e - 2", ' +
      '"{2, 2-sqrt(2), 2+sqrt(2)}"), refused (true only if you truly cannot ' +
      'produce any answer), confident (true if you believe it is correct), ' +
      'tool_calls (0 -- you must not execute anything in this arm).'
    )
  }
  return (
    'You are solving mathematics problems and you HAVE a SageMath CAS. Run it ' +
    "with:  docker exec sage-mcp sage -c '<sage code>'  (print the result). Use " +
    'it to compute AND to verify every answer; prefer exact results.\n\n' +
    `Problems:\n${probs}\n\n` +
    'Return one entry per problem: id, answer (the FINAL answer only, as a ' +
    'plain mathematical expression matching Sage form -- e.g. "34/5", "e - 2", ' +
    '"{2, 2-sqrt(2), 2+sqrt(2)}"), refused (true only if you cannot produce ' +
    'any answer), confident (true if you verified it in Sage), tool_calls (how ' +
    'many times you invoked Sage for that problem).'
  )
}

function scorePrompt(tierCases, solved) {
  const answers = (solved && solved.answers) || []
  const rows = tierCases
    .map((c) => {
      const a = answers.find((x) => x.id === c.id) || { answer: '(no answer)', refused: true }
      return (
        `[${c.id}] problem: ${c.problem}\n` +
        `  gold (Sage form): ${c.gold_sage}   check-type: ${c.check}\n` +
        `  model answer: ${a.answer}`
      )
    })
    .join('\n')
  return (
    'Score each model answer for MATHEMATICAL EQUIVALENCE to the gold, using ' +
    "SageMath. Run checks with:  docker exec sage-mcp sage -c '<code>'  and print " +
    'a clear True/False. Be strict -- numerically close but not equal is WRONG.\n\n' +
    'Rules by check-type:\n' +
    '- numeric: correct iff bool(SR(model) == SR(gold)) is True (exact ' +
    'rational/integer equality; parse the model answer, strip $ and commas).\n' +
    '- symbolic: correct iff bool((SR(model) - SR(gold)).simplify_full() == 0).\n' +
    '- set: parse both as sets; correct iff equal as sets (compare exact ' +
    'symbolic values, or sorted high-precision numerics element-wise).\n' +
    '- A missing, unparseable, or refused answer is NOT correct.\n\n' +
    'Return one verdict per problem: id, correct (bool), note (the Sage check ' +
    'you ran and its True/False result).\n\n' +
    rows
  )
}

phase('Solve')
const cohorts = tiers.flatMap((t) => arms.map((arm) => ({ t, arm })))

const results = await pipeline(
  cohorts,
  ({ t, arm }) => {
    const tc = cases.filter((c) => c.tier === t)
    return agent(solvePrompt(tc, arm), {
      label: `solve:${t}:${arm}`,
      phase: 'Solve',
      schema: SOLVE_SCHEMA,
      agentType: 'general-purpose',
      model: SUBJECT_MODEL,
      effort: 'low',
    }).then((sol) => ({ t, arm, sol }))
  },
  ({ t, arm, sol }) => {
    const tc = cases.filter((c) => c.tier === t)
    if (!sol) return { t, arm, sol: null, sc: null }
    return agent(scorePrompt(tc, sol), {
      label: `score:${t}:${arm}`,
      phase: 'Score',
      schema: SCORE_SCHEMA,
      agentType: 'general-purpose',
      model: JUDGE_MODEL,
    }).then((sc) => ({ t, arm, sol, sc }))
  },
)

// --- aggregate ---
const perProblem = []
for (const r of results.filter(Boolean)) {
  const { t, arm, sol, sc } = r
  const answers = (sol && sol.answers) || []
  const verdicts = (sc && sc.verdicts) || []
  for (const c of cases.filter((x) => x.tier === t)) {
    const a = answers.find((x) => x.id === c.id) || {
      answer: null,
      refused: true,
      confident: false,
      tool_calls: 0,
    }
    const v = verdicts.find((x) => x.id === c.id) || { correct: false, note: 'no verdict' }
    perProblem.push({
      id: c.id,
      tier: t,
      arm,
      answer: a.answer,
      refused: !!a.refused,
      confident: !!a.confident,
      tool_calls: a.tool_calls || 0,
      correct: !!v.correct,
      wrong_confident: !!a.confident && !v.correct && !a.refused,
    })
  }
}

function tally(rows) {
  const total = rows.length
  const correct = rows.filter((r) => r.correct).length
  const refused = rows.filter((r) => r.refused).length
  const wrongConfident = rows.filter((r) => r.wrong_confident).length
  const toolCalls = rows.reduce((s, r) => s + (r.tool_calls || 0), 0)
  return { total, correct, refused, wrongConfident, toolCalls }
}

const summary = { overall: {}, byTier: {} }
for (const arm of arms) summary.overall[arm] = tally(perProblem.filter((r) => r.arm === arm))
for (const t of tiers) {
  summary.byTier[t] = {}
  for (const arm of arms) {
    summary.byTier[t][arm] = tally(perProblem.filter((r) => r.arm === arm && r.tier === t))
  }
}

log(
  `no_tools ${summary.overall.no_tools.correct}/${summary.overall.no_tools.total}` +
    ` vs sage ${summary.overall.sage.correct}/${summary.overall.sage.total}`,
)

return { tiers, arms, subjectModel: SUBJECT_MODEL, judgeModel: JUDGE_MODEL, perProblem, summary }
