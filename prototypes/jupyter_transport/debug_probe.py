"""Does a crafted debug_request evaluate code outside do_execute?

The open question from FINDINGS.md. The guarded kernel enforces the AST policy in
``do_execute``, which covers every execute_request whatever client sent it. The
debugger is a different door: ``debug_request`` arrives on the CONTROL channel and
is handled by ipykernel's Debugger, not by ``do_execute``. If DAP's ``evaluate``
works there, the policy is bypassed entirely and the kernel transport can never be
adopted without shutting the debugger off.

debugpy 1.8.20 and ipykernel 7.2.0 are both present in Sage's Python, so the
question is not hypothetical.

Run inside the Sage container:

    cd /workspace/prototypes/jupyter_transport
    PYTHONPATH=/workspace/src sage -python debug_probe.py
"""

from __future__ import annotations

import queue

from jupyter_client import BlockingKernelClient
from spike import start_kernel

# Reading a real uid is proof enough, and harmless.
PAYLOAD = "__import__('os').getuid()"


def control(client: BlockingKernelClient, command: str, arguments: dict | None = None,
            *, seq: int = 1, timeout: int = 20) -> dict:
    """Send one debug_request on the control channel and return the reply."""
    content = {
        "type": "request",
        "seq": seq,
        "command": command,
        "arguments": arguments or {},
    }
    msg = client.session.msg("debug_request", content)
    client.control_channel.send(msg)
    while True:
        try:
            reply = client.get_control_msg(timeout=timeout)
        except queue.Empty:
            return {"__timeout__": True}
        if reply["parent_header"].get("msg_id") == msg["header"]["msg_id"]:
            return reply["content"]


def main() -> int:
    km = start_kernel(guarded=True)
    client: BlockingKernelClient = km.client()
    client.start_channels()
    client.wait_for_ready(timeout=180)

    findings: list[tuple[str, str]] = []
    try:
        # 1. Does the kernel admit to a debugger at all?
        info = client.session.msg("kernel_info_request", {})
        client.shell_channel.send(info)
        reply = client.get_shell_msg(timeout=60)
        supports = reply["content"].get("supported_features", [])
        findings.append(("advertises debugger", str("debugger" in supports)))

        # 2. Is the debugger reachable regardless of what it advertises?
        init = control(client, "initialize", {
            "clientID": "probe", "adapterID": "probe",
            "pathFormat": "path", "linesStartAt1": True, "columnsStartAt1": True,
            "supportsVariableType": True, "supportsRunInTerminalRequest": False,
            "locale": "en",
        }, seq=1)
        reachable = not init.get("__timeout__") and bool(init)
        findings.append(("initialize answered", f"{reachable} {str(init)[:110]}"))

        # initialize may refuse until the session is attached, so follow the
        # documented sequence rather than concluding from one refusal.
        attach = control(client, "attach", {"justMyCode": False}, seq=10)
        findings.append(("attach", str(attach)[:110]))
        info = control(client, "debugInfo", {}, seq=11)
        findings.append(("debugInfo", str(info)[:110]))

        # 3. The actual question: evaluate, which is the DAP command that runs code.
        result = control(client, "evaluate", {
            "expression": PAYLOAD, "context": "repl", "frameId": 0,
        }, seq=2)
        body = result.get("body", {}) if isinstance(result, dict) else {}
        evaluated = bool(result.get("success")) and "result" in body
        findings.append((
            "evaluate outside do_execute",
            f"success={result.get('success')} {str(result)[:100]}",
        ))

        # 4. dumpCell writes caller-supplied text to a file the kernel will run.
        dumped = control(client, "dumpCell", {"code": PAYLOAD}, seq=3)
        findings.append((
            "dumpCell accepted",
            f"success={dumped.get('success')} {str(dumped.get('body', ''))[:60]}",
        ))

        # 5. And the control: the ordinary door is guarded.
        execute = client.session.msg("execute_request", {
            "code": PAYLOAD, "silent": False, "store_history": False,
            "user_expressions": {}, "allow_stdin": False,
        })
        client.shell_channel.send(execute)
        execute_reply = client.get_shell_msg(timeout=60)["content"]
        findings.append((
            "execute_request (the guarded door)",
            f"{execute_reply.get('status')} {execute_reply.get('ename', '')}",
        ))

        print()
        for label, value in findings:
            print(f"  {label:36} {value}")
        print()
        print(f"  VERDICT: {'BYPASS' if evaluated else 'no bypass via evaluate'}")
        return 0 if not evaluated else 1
    finally:
        client.stop_channels()
        km.shutdown_kernel(now=True)


if __name__ == "__main__":
    raise SystemExit(main())
