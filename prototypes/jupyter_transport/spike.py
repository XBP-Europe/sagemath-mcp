"""Evaluate a Jupyter-kernel transport against the current subprocess worker.

Answers four questions with measurements rather than argument:
  1. Does the AST policy survive the move, including from a second client?
  2. What does a kernel cost to start, compared with the current worker?
  3. Does interrupt preserve state, as it now does with SIGINT?
  4. Do large payloads survive, the failure that produced the 8 MiB stream limit?
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from queue import Empty

from jupyter_client import BlockingKernelClient, KernelManager
from jupyter_client.kernelspec import KernelSpec

HERE = Path(__file__).resolve().parent


def start_kernel(guarded: bool) -> KernelManager:
    if guarded:
        argv = ["sage", "-python", "-m", "guarded_kernel", "-f", "{connection_file}"]
    else:
        argv = ["sage", "-python", "-m", "ipykernel_launcher", "-f", "{connection_file}"]
    km = KernelManager()
    km._kernel_spec = KernelSpec(
        resource_dir="", argv=argv, display_name="Sage", language="python"
    )
    # The guarded kernel is a module in this directory.
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{HERE}:{env.get('PYTHONPATH', '')}"
    km.start_kernel(cwd=str(HERE), env=env)
    return km


def run(client, code: str, timeout: int = 60) -> dict:
    """Execute and collect both iopub output and the shell reply.

    The shell reply matters: a kernel that refuses in do_execute reports it as
    the reply status, and nothing is emitted on iopub. Reading only iopub makes
    a refusal look identical to a statement that produced no value.
    """
    mid = client.execute(code, silent=False, store_history=False)
    out = {"result": None, "error": None, "stdout": "", "reply": None}
    end = time.time() + timeout
    while time.time() < end:
        try:
            msg = client.get_iopub_msg(timeout=5)
        except Empty:
            break
        if msg["parent_header"].get("msg_id") != mid:
            continue
        t, c = msg["msg_type"], msg["content"]
        if t == "stream" and c["name"] == "stdout":
            out["stdout"] += c["text"]
        elif t == "execute_result":
            out["result"] = c["data"].get("text/plain")
        elif t == "error":
            out["error"] = f"{c['ename']}: {c['evalue'][:70]}"
        elif t == "status" and c["execution_state"] == "idle":
            break
    try:
        reply = client.get_shell_msg(timeout=10)
        content = reply["content"]
        out["reply"] = content.get("status")
        if content.get("status") == "error" and not out["error"]:
            out["error"] = f"{content.get('ename')}: {str(content.get('evalue'))[:70]}"
    except Empty:
        pass
    return out


BLOCKED = "import os\nos.getuid()"


def q1_policy_survives() -> None:
    print("\n1. Does the AST policy survive the move?")
    for label, guarded in (("stock ipykernel", False), ("guarded kernel", True)):
        km = start_kernel(guarded)
        kc = km.client()
        kc.start_channels()
        kc.wait_for_ready(timeout=90)
        legit = run(kc, "2 + 2")
        blocked = run(kc, BLOCKED)
        atk = BlockingKernelClient()
        atk.load_connection_file(km.connection_file)
        atk.start_channels()
        atk.wait_for_ready(timeout=90)
        second = run(atk, BLOCKED)
        def verdict(r):
            return f"REFUSED ({r['error'][:34]})" if r["error"] else f"EXECUTED {r['result']}"

        print(f"   {label:16} legit={legit['result']}")
        print(f"   {'':16}   same client : {verdict(blocked)}")
        print(f"   {'':16}   2nd client  : {verdict(second)}")
        atk.stop_channels()
        kc.stop_channels()
        km.shutdown_kernel(now=True)


def q2_startup_cost() -> None:
    print("\n2. What does startup cost?")
    start = time.perf_counter()
    km = start_kernel(True)
    kc = km.client()
    kc.start_channels()
    kc.wait_for_ready(timeout=90)
    run(kc, "from sage.all import *")
    kernel_ms = (time.perf_counter() - start) * 1000
    kc.stop_channels()
    km.shutdown_kernel(now=True)

    sys.path.insert(0, "/workspace/src")
    from sagemath_mcp.config import SageSettings
    from sagemath_mcp.session import SageSession

    async def worker_start() -> float:
        session = SageSession("bench", SageSettings(force_python_worker=False))
        begin = time.perf_counter()
        await session.evaluate("1", want_latex=False, capture_stdout=False)
        elapsed = (time.perf_counter() - begin) * 1000
        await session.shutdown()
        return elapsed

    worker_ms = asyncio.run(worker_start())
    print(f"   jupyter kernel ready : {kernel_ms:8.0f} ms")
    print(f"   current worker ready : {worker_ms:8.0f} ms")
    print(f"   delta                : {kernel_ms - worker_ms:+8.0f} ms")


def q3_interrupt_keeps_state() -> None:
    print("\n3. Does interrupt preserve state?")
    km = start_kernel(True)
    kc = km.client()
    kc.start_channels()
    kc.wait_for_ready(timeout=90)
    run(kc, "treasure = 12345")
    kc.execute("x = 0\nfor i in range(10**9):\n    x += i\nx", silent=False)
    time.sleep(1.5)
    km.interrupt_kernel()
    time.sleep(1.0)
    # Drain whatever the interrupted execution emitted.
    while True:
        try:
            kc.get_iopub_msg(timeout=2)
        except Empty:
            break
    kept = run(kc, "treasure")
    print(f"   after interrupt, treasure = {kept['result']}  "
          f"({'preserved' if kept['result'] == '12345' else 'LOST'})")
    kc.stop_channels()
    km.shutdown_kernel(now=True)


def q4_large_payload() -> None:
    print("\n4. Do large payloads survive?")
    km = start_kernel(True)
    kc = km.client()
    kc.start_channels()
    kc.wait_for_ready(timeout=90)
    for size in (100_000, 2_000_000):
        got = run(kc, f"'x' * {size}")
        length = len(got["result"] or "")
        print(f"   {size:>9,} chars -> returned {length:>9,}  "
              f"({'ok' if length >= size else 'TRUNCATED/FAILED'})")
    kc.stop_channels()
    km.shutdown_kernel(now=True)


if __name__ == "__main__":
    q1_policy_survives()
    q2_startup_cost()
    q3_interrupt_keeps_state()
    q4_large_payload()
