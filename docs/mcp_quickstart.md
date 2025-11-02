# MCP Quickstart & Prompt Cookbook

This guide offers ready-to-use snippets for LLM-driven clients.

## Connection Summary

- **Tool:** `evaluate_sage` (general Sage code with optional `latex`, `capture_stdout`, `timeout`).
- **Helpers:** `calculate_expression`, `solve_equation`, `differentiate_expression`,
  `integrate_expression`, `matrix_multiply`, `statistics_summary`.
- **Session Management:** `reset_sage_session`, `cancel_sage_session`.
- **Resources:** `resource://sagemath/session/all`, `resource://sagemath/monitoring/metrics`.
- **Deployment:** Local development via `uv run sagemath-mcp`, Docker Compose on `http://127.0.0.1:8314/mcp`,
  or the Helm chart (`charts/sagemath-mcp`) which exposes the MCP endpoint through a Kubernetes Service.

## Example Prompts

### Evaluate a Multi-Step Workflow

```json
{
  "tool": "evaluate_sage",
  "arguments": {
    "code": "var('x'); f = sin(x)**3; diff(f, x)"
  }
}
```

```
{
  "tool": "evaluate_sage",
  "arguments": {
    "code": "integral(diff(sin(x)**3, x), x)"
  }
}
```

### Equation Solving Helper

```json
{
  "tool": "solve_equation",
  "arguments": {
    "equation": "x^2 - 5*x + 6 = 0",
    "variable": "x"
  }
}
```

### Matrix Multiplication

```json
{
  "tool": "matrix_multiply",
  "arguments": {
    "matrix_a": [[1, 2], [3, 4]],
    "matrix_b": [[5, 6], [7, 8]]
  }
}
```

### Statistics Summary

```json
{
  "tool": "statistics_summary",
  "arguments": {
    "data": [1, 2, 3, 4, 5]
  }
}
```

### Monitoring Snapshot

```json
{
  "resource": "resource://sagemath/monitoring/metrics"
}
```

## Usage Tips

- Reuse the same MCP session for cumulative calculations; Sage state persists until `reset_sage_session`.
- Prefer Sage primitives (`var`, `matrix`, polynomial rings) over raw imports.
- Disable `capture_stdout` in `evaluate_sage` for loops unless you need console output.
- Use the helper tools where possible—they return clean JSON structures.
