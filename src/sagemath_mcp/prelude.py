"""The prelude every generated snippet starts with.

It declares the predefined symbols and the tool's own variables in ``_locals``,
the namespace the template's ``sage_eval`` calls resolve against.
"""

from __future__ import annotations

import textwrap
from collections.abc import Iterable

from ._artifacts import ALLOWED_CALLER_NAMES
from .gates import validated_identifier
from .security import (
    _GREEK_NAMES,
    _SYMBOL_SHAPE,
)
from .symbols import PREDEFINED_SYMBOLS

# Symbol-shaped names SageMath already defines, which must never be turned into
# a fresh variable: `e` is Euler's number, `I` the imaginary unit, and `gamma`,
# `zeta`, `beta`, `psi`, `sigma`, `eta` and `tau` are functions. Auto-declaring
# any of them would shadow real mathematics with an empty symbol.
# The Greek alphabet as single characters, which is how a physicist writes it.
# `_GREEK_NAMES` covers the spelled-out forms (`alpha`, `omega`); these are the
# letters themselves, and `str.isalpha()` calls them letters while
# `_SYMBOL_SHAPE` -- deliberately `^[a-zA-Z]_?\d?$` -- does not.
_GREEK_LETTERS = frozenset(
    "\u03b1\u03b2\u03b3\u03b4\u03b5\u03b6\u03b7\u03b8\u03b9\u03ba\u03bb\u03bc"
    "\u03bd\u03be\u03bf\u03c0\u03c1\u03c2\u03c3\u03c4\u03c5\u03c6\u03c7\u03c8"
    "\u03c9"
    "\u0391\u0392\u0393\u0394\u0395\u0396\u0397\u0398\u0399\u039a\u039b\u039c"
    "\u039d\u039e\u039f\u03a0\u03a1\u03a3\u03a4\u03a5\u03a6\u03a7\u03a8\u03a9"
    "\u03d1\u03d5\u03d6\u03f1\u03f5"
)


# Symbol-shaped names SageMath already defines, which must never be turned into
# a fresh variable: `e` is Euler's number, `I` the imaginary unit, and `gamma`,
# `zeta`, `beta`, `psi`, `sigma`, `eta` and `tau` are functions. So are five of
# the Greek letters -- capital gamma, zeta, pi, sigma and psi -- which is why
# the letters are
# filtered through the allowlist rather than trusted wholesale. Declaring any of
# them would shadow real mathematics with an empty symbol.
_SYMBOL_SHAPED_ALREADY_OFFERED = frozenset(
    name for name in ALLOWED_CALLER_NAMES
    if _SYMBOL_SHAPE.match(name) or name in _GREEK_NAMES or name in _GREEK_LETTERS
)


_DECLARABLE_GREEK_LETTERS = _GREEK_LETTERS - set(ALLOWED_CALLER_NAMES)


def sage_prelude(extra_locals: Iterable[str] | None = None) -> str:
    names = list(PREDEFINED_SYMBOLS)
    if extra_locals:
        # Every name lands inside a quoted string in the generated prelude, so
        # validate here rather than at each of the 33 call sites.
        names.extend(validated_identifier(n, "variable") for n in extra_locals)
    locals_list = ", ".join(f"'{n}'" for n in dict.fromkeys(names))
    excluded = ", ".join(f"'{n}'" for n in sorted(_SYMBOL_SHAPED_ALREADY_OFFERED))
    greek = ", ".join(
        f"'{n}'" for n in sorted(_GREEK_NAMES | _DECLARABLE_GREEK_LETTERS)
    )
    return textwrap.dedent(
        rf"""
        from sage.all import *
        from sage.all import sage_eval

        class _SymbolLocals(dict):
            # SageMath declares a variable when it *parses a string* into the
            # symbolic ring -- `SR("a*b + a")` creates `a` and `b` -- and not
            # when it runs code, where `w + 1` is a NameError. These tools take
            # a mathematical expression as a string, which is SR's contract, so
            # they behave like SR.
            #
            # Narrower than SR in one way that matters. SR will invent any
            # identifier: `SR("sinn(x)")` returns `sinn(x)` and `SR("pi2*2")`
            # returns `2*pi2`, so a typo becomes a symbol and the caller gets a
            # confident wrong answer. Only symbol-shaped names are declared here
            # -- a letter with an optional index, or a Greek name -- so `a`,
            # `b`, `w` and `x_2` are variables and `sinn`, `foobar` and `pi2`
            # are still errors.
            #
            # The Greek alphabet is here as letters as well as names, because
            # that is how a physicist writes it -- but only the letters
            # SageMath does not already define: five of them are its gamma,
            # zeta, pi, sigma and psi, and shadowing those was a real
            # regression before the allowlist filtered them out.
            #
            # KeyError rather than a symbol is the important branch: it is what
            # lets the lookup fall through to the namespace, so `matrix`, `QQ`
            # and `sin` resolve normally.
            _excluded = frozenset([{excluded}])
            _greek = frozenset([{greek}])

            def __missing__(self, name):
                if name in self._excluded or name.startswith('_'):
                    raise KeyError(name)
                shaped = name in self._greek
                if not shaped:
                    body = name.replace('_', '', 1) if '_' in name[1:] else name
                    # ASCII, mirroring `_SYMBOL_SHAPE` on the Python side: a
                    # letter, then an optional underscore and digit. Python's
                    # `isalpha()` is true for the Greek letters too,
                    # so without the ascii test this declared a fresh symbol
                    # for SageMath's own pi and turned `pi.n()` into "cannot
                    # evaluate symbolic expression numerically". Two
                    # implementations of one rule, disagreeing. The Greek
                    # letters come back through the set above, filtered.
                    head = body[:1]
                    shaped = (
                        len(body) <= 2 and head.isascii() and head.isalpha()
                        and (len(body) == 1 or body[1:].isdigit())
                    )
                if not shaped:
                    raise KeyError(name)
                created = var(name)
                self[name] = created
                return created

        _locals = _SymbolLocals({{name: var(name) for name in [{locals_list}]}})
        """
    )
