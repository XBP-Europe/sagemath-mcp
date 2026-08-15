"""The symbolic variables this server predefines.

SageMath's own REPL predefines `x` and nothing else. This server predefines four,
which is a deliberate departure: the specialised tools have always declared
`x, y, z, t` in their generated prelude, so `differentiate_expression("x^2*y^3")`
worked while the identical mathematics through `evaluate_sage` failed with "name
'y' is not defined". Two paths disagreeing about which symbols exist is worse
than either convention on its own, and the tools' convention is the one that
matches what callers write.

The trade is real and small: a mistyped `y` becomes a symbolic variable instead
of an error. That is already true of `x` in Sage itself.

Four and no more. `n` is numerical approximation, `i` is the Gaussian imaginary
unit, and `e`, `I` and `pi` are constants -- predefining any of those would
shadow a real object rather than fill an empty name. `y`, `z` and `t` are unbound
in a fresh Sage namespace, which is what makes them safe to claim.

Kept in a module of its own so the worker can import it without pulling in
FastMCP: the worker is a subprocess whose startup cost is on every session.
"""

from __future__ import annotations

PREDEFINED_SYMBOLS: tuple[str, ...] = ("x", "y", "z", "t")
