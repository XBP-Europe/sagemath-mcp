"""The narrow exception to the import ban.

``rewrite_permitted_imports`` turns the few imports that change nothing, and
the vetted ``from <module> import *`` lines, into the names they would bind,
before validation sees the code.
"""

from __future__ import annotations

import ast

from .policy import SECURITY_POLICY, SecurityPolicy


def rewrite_permitted_imports(
    module: ast.Module,
    *,
    offered: frozenset[str] | set[str],
    policy: SecurityPolicy | None = None,
) -> ast.Module:
    """Drop the imports that would change nothing, before anything is validated.

    Callers cannot import, and that rule is load-bearing: an import is how you
    get back everything the namespace scrub removed (item 27). But a great deal
    of what arrives would achieve *nothing* -- a reflex line at the top of a
    snippet, or a name the namespace already holds -- and refusing those costs
    the whole snippet for no gain. Gemini opens numerical work with
    `import numpy as np` and then never uses `np`; that line was worth ignoring,
    not erroring on.

    Three shapes are dropped, and the safety of all three is one argument:
    **nothing is imported, so nothing new becomes reachable.**

    1. `from X import a, b` where every name is already offered. The source
       module is never touched, so what it is does not matter: the caller ends
       up with the object they could already read. An alias is checked against
       the name being *imported*, not the alias, so `from sage.all import os as
       m` is still refused -- that was a real bypass.
    2. `from sage.all import *`, which is what the namespace already is.
    3. A plain `import X` whose bound name is never read in this snippet.

    Everything else is left in place for the validator to refuse, with a message
    that now names the alternative.
    """
    policy = policy or SECURITY_POLICY
    if not policy.enforce_name_allowlist:
        return module

    read: set[str] = {
        node.id
        for node in ast.walk(module)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    read |= {
        segment
        for node in ast.walk(module)
        if isinstance(node, ast.Attribute)
        for segment in attribute_segments(node)
    }

    def replacement(node: ast.Import | ast.ImportFrom) -> list[ast.stmt] | None:
        """The statements to put in place of *node*, or None to leave it alone."""
        bound_by = {(alias.asname or alias.name).split(".", 1)[0] for alias in node.names}

        if any(alias.name == "*" for alias in node.names):
            # Only from the namespace's own source, and only as a no-op.
            if isinstance(node, ast.ImportFrom) and node.module in ("sage.all", "sage"):
                return []
            # A vetted module's star import is expanded to its screened names, so
            # what runs is exactly what was reviewed. The validator then permits
            # the explicit import and the names bind as the caller's own.
            if isinstance(node, ast.ImportFrom) and node.module in policy.star_export_modules:
                screened = sorted(policy.star_export_modules[node.module])
                if screened:
                    expanded = ast.ImportFrom(
                        module=node.module,
                        names=[ast.alias(name=name, asname=None) for name in screened],
                        level=0,
                    )
                    return [ast.copy_location(expanded, node)]
            return None

        if isinstance(node, ast.Import) and not bound_by & read:
            # A plain `import numpy as np` that nothing reads is a reflex line,
            # and dropping it cannot change the result.
            #
            # Deliberately NOT extended to `from X import Y`. That form names a
            # specific object, and a caller who asks for one this server does
            # not offer deserves to be told now rather than on the next call,
            # when the failure has moved to a bare `Y` and says nothing about
            # the import. Measured against SageMath's own doctests, dropping
            # unused from-imports moved acceptance from 98.6% to 91.0% -- 32,000
            # examples whose clear refusal became a confusing one.
            return []

        if isinstance(node, ast.ImportFrom):
            wanted = [alias.name for alias in node.names]
            if all(name in offered for name in wanted):
                # Bind the object the caller could already read. Only an alias
                # needs a statement; without one the name is already correct.
                return [
                    ast.Assign(
                        targets=[ast.Name(id=alias.asname, ctx=ast.Store())],
                        value=ast.Name(id=alias.name, ctx=ast.Load()),
                    )
                    for alias in node.names
                    if alias.asname
                ]
        # `import X` binds a module object, which is a capability even when the
        # name looks familiar: `import sage.misc.persist` is not a no-op.
        return None

    changed = False
    body: list[ast.stmt] = []
    for statement in module.body:
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            substitute = replacement(statement)
            if substitute is not None:
                body.extend(substitute)
                changed = True
                continue
        body.append(statement)

    if not changed:
        return module
    rewritten = ast.Module(body=body, type_ignores=list(module.type_ignores))
    ast.fix_missing_locations(rewritten)
    return rewritten


def attribute_segments(node: ast.Attribute) -> list[str]:
    """Return every dotted segment of an attribute chain, root first.

    Checking only one level let sage.misc.temporary_file.os.getuid() through,
    because func.value was an Attribute rather than a Name. Checking only the
    root is not enough either: there the root is the permitted `sage` and the
    forbidden `os` sits in the middle of the chain.
    """
    segments: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        segments.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        segments.append(current.id)
    segments.reverse()
    return segments
