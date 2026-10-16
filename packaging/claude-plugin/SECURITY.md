# Security Policy

This plugin starts the SageMath MCP server with `uvx`, pinned to the release
named in `.claude-plugin/plugin.json`. It contains no code of its own, so its
security is the server's: the full policy, the security model and the record of
past findings are in the repository's
[SECURITY.md](https://github.com/XBP-Europe/sagemath-mcp/blob/main/SECURITY.md).

What the plugin runs: the server, on your machine, with your user's privileges.
Code the model sends passes a deny-by-default validator before Sage runs it, but
that validator is not an operating-system boundary. For untrusted input or a
shared host, run the container image instead (see the main README).

## Reporting a Vulnerability

Please report privately, not in a public issue:

- [Report a vulnerability](https://github.com/XBP-Europe/sagemath-mcp/security/advisories/new)
  through GitHub's private vulnerability reporting. Only you and the maintainers
  can see the report.
- Or email: 5gxma24v1@mozmail.com

Include the code you sent, the tool you sent it to, what came back, and the
plugin version. We aim to acknowledge reports within 3 business days.
