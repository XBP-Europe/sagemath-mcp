# Tier 3 prototype: Jupyter kernel transport

**Recommendation: do not adopt now.** The problems that motivated it have since been
solved more cheaply, and the move would cost a permanent custom kernel plus a local
network surface the current design does not have.

Reproduce with `sage -python spike.py` inside the Sage container.

## Why this was on the roadmap

[szeider/mcp-sage](https://github.com/szeider/mcp-sage) drives Sage through the Jupyter
kernel protocol and cites "reliable prompt detection, clean separation of stdout / stderr
/ return values, native interrupt support, and robust multi-line input". Those were real
gaps against a hand-rolled JSON-over-stdio worker, and a framing bug in ours surfaced as
recently as v0.4.0.

## What the prototype measured

| Question | Result |
|----------|--------|
| Does the AST policy survive? | **Only with a custom kernel.** Stock ipykernel executes blocked code. |
| Startup cost | **1010 ms** vs **463 ms** for the current worker (+547 ms, 2.2×) |
| Interrupt preserves state? | Yes — and so does the SIGINT implementation already shipped |
| Large payloads | 2 MB round-trips fine — as it now does over stdio with an 8 MiB limit |

### The policy finding, in detail

A Jupyter kernel listens on five TCP ports on 127.0.0.1, authenticated by an HMAC key in
a connection file (mode 0600). Any process able to read that file can execute code in the
kernel. Measured against a stock kernel, with a second client attaching using only the
connection file:

```
stock ipykernel   same client : EXECUTED 1001      # import os; os.getuid()
                  2nd client  : EXECUTED 1001
guarded kernel    same client : REFUSED (SecurityViolation: Import statements...)
                  2nd client  : REFUSED (SecurityViolation: Import statements...)
```

So client-side validation would be **advisory only**: the socket is a second door.

**IPython's `ast_transformers` cannot be used as the gate.** A transformer that raises is
not a veto. IPython emits a `UserWarning`, executes the original code anyway, and
silently unregisters the transformer:

```
install  -> 'installed'
1st run  -> UserWarning: AST transformer <...> threw an error ... ; result 42
2nd run  -> result 42
transformers left -> 0
```

That leaves exactly one way to keep the sandbox: subclass the kernel and validate in
`do_execute`, as `guarded_kernel.py` does. It works, and it closes the socket bypass —
but it means owning a kernel subclass and tracking ipykernel's internals indefinitely.

## Why not now

**The motivating benefits are already banked.** Interrupt with state preservation shipped
in Tier 2 using plain SIGINT, and is verified against a real Sage runtime. The framing
failure was fixed by sizing the stream limit to 8 MiB. Multi-line input already works.
Of the four cited advantages, the only one left is that ZMQ framing has no arbitrary
ceiling where ours has a large one.

**The costs are concrete.** Startup more than doubles, on a path users wait for. Two
heavy dependencies join the runtime. Most importantly the sandbox — the project's main
differentiator against every peer — would depend on a kernel subclass rather than on the
worker having no other input than its own stdin.

**The threat model gets worse, not better.** Today a worker has no listening socket at
all; to inject code you must already control the server process. With kernels, every
session opens local ports, and a same-user process can execute *validated* code in
another session's namespace. Pipes make that structurally impossible. One question is
**RESOLVED (2026-08-14) — see `debug_probe.py`.** Measured against the guarded
kernel in the Sage container, with debugpy 1.8.20 and ipykernel 7.2.0 present:

| probe | result |
|-------|--------|
| kernel advertises `debugger` | **True** — the claim below that it does not was wrong |
| `debug_request` reaches the debugger | yes, `debugInfo` answers `success: True` |
| `initialize` | `success: False` |
| `attach` | empty reply |
| `debugInfo` body | `isStarted: False` |
| `evaluate` (the DAP command that runs code) | no reply body, nothing evaluated |
| `execute_request` with the same payload | refused, `SecurityViolation` |

So **no bypass**: the debug session never starts, and `evaluate` executes nothing,
while the ordinary door stays guarded. Two caveats worth keeping. The surface is
*advertised and reachable* — a failure to start is not a refusal by design, and a
future ipykernel that starts more readily would reopen the question. And a negative
result is not proof: it says this sequence did not evaluate, not that none can. If
the transport is ever adopted, turn the debugger off explicitly rather than relying
on it failing to start.

The original note, now known to be wrong on the advertising point:

`debugpy` is present in Sage's Python, and although the guarded kernel
does not advertise `debugger`, whether a crafted `debug_request` can evaluate outside
`do_execute` was not established.

## What would change the answer

- **Rich display.** Kernels emit `display_data` with `image/png` and `text/latex`
  natively. The plot tools currently hand-roll base64 PNGs and `plot3d_expression` had to
  sample a surface manually because `Graphics3d` has no in-memory export. A kernel makes
  that the transport's job.
- **Notebook interoperability**, or exposing the same session to a Jupyter front end.
- **Other language kernels** through one interface, which is roughly what
  [scicompute-mcp](https://github.com/sanshanjianke/scicompute-mcp) does with multiple
  backends.

Those are reasons about capability. Adopting for robustness alone is no longer justified.

## Files

- `guarded_kernel.py` — kernel subclass validating in `do_execute`; the only approach
  found that keeps the policy intact
- `spike.py` — the measurement harness

Note on the harness: an early version read only iopub and reported a refusal as
`EXECUTED None`, because a kernel refusing in `do_execute` reports it in the **shell
reply** and emits nothing on iopub. It now reads both. Worth knowing before trusting any
similar measurement.


## What the other Jupyter-based server does (2026-08-14)

`szeider/mcp-sage` adopted this transport, so it is worth reading against these
findings. It is 369 lines and runs the **stock** `ipykernel_launcher`.

- **No policy at all.** No AST validation anywhere in it: `os.system` and the rest
  execute. That is the cost this prototype refused to pay, and they simply did not
  pay it -- which confirms the choice rather than undermining it.
- **It does not harvest rich display.** Output handling reads `text/plain` from
  `execute_result` and streams; there is no `image/png` path. Rich display is the
  one argument for revisiting the kernel, and the project that adopted the kernel
  is not using it.
- **It carries a GAP crash-loop guard**: repeated "Gap crashed" on stderr triggers
  an interrupt after three, to stop a fork bomb from `structure_description()`.
  That is a real operational lesson, and the reason we are not exposed to it is
  structural: `group_operation` offers six fixed operations and
  `structure_description` is not among them, while `evaluate_sage` runs under a
  timeout that restarts the worker. Measured here: `SymmetricGroup(6)` and a
  cyclic group return in under a second, the session survives, and no stray `gap`
  process is left behind.
