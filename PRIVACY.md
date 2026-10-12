# Privacy

sagemath-mcp is software you run yourself: on your machine, in your container or
on your cluster. XBP Europe operates no service behind it and receives nothing
from it.

## What the server sends

Nothing. The server contains no telemetry, analytics or update checks, and makes
no outbound network connections. `lookup_sage_doc` returns documentation links;
it does not fetch them.

Installing it does use the network, through the tool you install with: `uv` or
`pip` download the package and the Sage runtime from PyPI, conda from
conda-forge, and Docker the image from GitHub Container Registry. Those services'
own privacy policies apply to those downloads.

## What it keeps, and where

Everything stays where the server runs:

- **Session state.** Each session's Sage variables live in memory in its worker
  process and are gone when the session ends, is reset, or is culled after
  `SAGEMATH_MCP_IDLE_TTL` seconds of inactivity.
- **Journals, only if you turn them on.** With `SAGEMATH_MCP_PERSIST_SESSIONS=true`,
  the code each session ran is written to `SAGEMATH_MCP_PERSIST_DIR` (if that is
  unset, nothing is written) so a restarted worker can replay it. It is off by default,
  and `reset_sage_session` deletes a session's journal.
- **Logs.** The server logs to standard error. By default
  (`SAGEMATH_MCP_SECURITY_LOG_VIOLATIONS=true`) a refused snippet is logged with
  its code, and anything a Sage worker writes to its own standard error, such as
  a warning or a traceback, is relayed to the log. The code of accepted calls and
  their results are not logged. Where the logs go is decided by whatever started
  the server: your MCP client, Docker or Kubernetes.
- **Metrics.** Counters and latencies are kept in memory and exposed only
  through the server's own monitoring resource. Over HTTP, `/health` reports the
  version and the number of active sessions, nothing about their contents.

## Your MCP client

The questions you ask and the results the tools return pass through the MCP
client and the language model you use with it. Their handling is governed by
that client's and that model provider's privacy policies, not by this project.

## Contact

Questions about this statement: open an issue at
<https://github.com/XBP-Europe/sagemath-mcp/issues>. For a security concern, use
the private reporting route in [SECURITY.md](SECURITY.md).
