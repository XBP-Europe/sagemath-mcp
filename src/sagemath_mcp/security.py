"""Security policy and AST validation for Sage worker execution."""

from __future__ import annotations

import ast
import logging
import os
from dataclasses import dataclass, replace

LOGGER = logging.getLogger(__name__)


class SecurityViolation(ValueError):
    """Raised when user code violates the configured security policy."""

    # NOTE: We consistently surface SecurityViolation instances back to the
    # caller to explain why a snippet was blocked. Raising a dedicated type
    # keeps logging/monitoring code straightforward.


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid integer for {name}: {raw}") from exc


def _tuple_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    values = [value.strip() for value in raw.split(",") if value.strip()]
    return tuple(values) if values else default


@dataclass(slots=True)
class SecurityPolicy:
    """Declarative policy describing acceptable Sage user code."""

    enabled: bool = True
    max_source_chars: int = 8_000
    max_ast_nodes: int = 2_500
    max_ast_depth: int = 75
    allow_imports: bool = False
    forbid_global_stmt: bool = True
    forbid_nonlocal_stmt: bool = True
    forbidden_call_names: tuple[str, ...] = (
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "input",
        "globals",
        "locals",
        "vars",
        # Attribute access by name defeats every attribute rule below:
        # getattr(os, 'system')('id') never produces an ast.Attribute node.
        "getattr",
        "setattr",
        "delattr",
        # sage_eval and preparse evaluate a *string* at runtime, long after this
        # validator has approved the AST. They are the sharpest bypass of all,
        # since the payload is invisible at validation time.
        "sage_eval",
        "preparse",
        "sage_input",
    )
    forbidden_attribute_parents: tuple[str, ...] = (
        "os",
        "sys",
        "pathlib",
        "subprocess",
        "shutil",
        "socket",
        "builtins",
    )
    forbidden_attribute_names: tuple[str, ...] = (
        "system",
        "popen",
        "popen2",
        "popen3",
        "remove",
        "rmdir",
        "unlink",
        "rmtree",
        "walk",
        "spawnl",
        "spawnlp",
        "spawnv",
        "spawnvp",
        "execv",
        "execvp",
        "execvpe",
        "fork",
        "forkpty",
    )
    allowed_import_modules: tuple[str, ...] = (
        "math",
        "cmath",
        "sage",
        "sage.all",
        "statistics",
        "base64",
        "io",
    )
    allowed_import_prefixes: tuple[str, ...] = ("sage.",)
    log_violations: bool = True

    @classmethod
    def from_env(cls) -> SecurityPolicy:
        """Load the security policy using environment overrides."""
        defaults = cls()
        return cls(
            enabled=_bool_env("SAGEMATH_MCP_SECURITY_ENABLED", defaults.enabled),
            max_source_chars=_int_env(
                "SAGEMATH_MCP_SECURITY_MAX_SOURCE", defaults.max_source_chars
            ),
            max_ast_nodes=_int_env(
                "SAGEMATH_MCP_SECURITY_MAX_AST_NODES", defaults.max_ast_nodes
            ),
            max_ast_depth=_int_env(
                "SAGEMATH_MCP_SECURITY_MAX_AST_DEPTH", defaults.max_ast_depth
            ),
            allow_imports=_bool_env("SAGEMATH_MCP_SECURITY_ALLOW_IMPORTS", defaults.allow_imports),
            forbid_global_stmt=_bool_env(
                "SAGEMATH_MCP_SECURITY_FORBID_GLOBAL", defaults.forbid_global_stmt
            ),
            forbid_nonlocal_stmt=_bool_env(
                "SAGEMATH_MCP_SECURITY_FORBID_NONLOCAL", defaults.forbid_nonlocal_stmt
            ),
            log_violations=_bool_env(
                "SAGEMATH_MCP_SECURITY_LOG_VIOLATIONS", defaults.log_violations
            ),
            allowed_import_modules=_tuple_env(
                "SAGEMATH_MCP_SECURITY_ALLOWED_IMPORTS", defaults.allowed_import_modules
            ),
            allowed_import_prefixes=_tuple_env(
                "SAGEMATH_MCP_SECURITY_ALLOWED_IMPORT_PREFIXES",
                defaults.allowed_import_prefixes,
            ),
        )


SECURITY_POLICY = SecurityPolicy.from_env()


def _max_depth(node: ast.AST, depth: int = 0) -> int:
    child_depths = [_max_depth(child, depth + 1) for child in ast.iter_child_nodes(node)]
    if not child_depths:
        return depth
    return max(child_depths)


def _format_violation(message: str, code: str | None) -> str:
    if not code:
        return message
    snippet = code.strip().splitlines()
    if snippet:
        snippet = snippet[:3]
        joined = " / ".join(line.strip() for line in snippet if line.strip())
        return f"{message} [snippet: {joined}]"
    return message


def _raise_violation(
    message: str, *, code: str | None, policy: SecurityPolicy | None
) -> None:
    formatted = _format_violation(message, code)
    if (policy or SECURITY_POLICY).log_violations:
        LOGGER.warning("Blocked Sage code: %s", formatted)
    raise SecurityViolation(message)


def trusted_policy(policy: SecurityPolicy | None = None) -> SecurityPolicy:
    """Policy for code this server generates itself.

    The helper tools build their Sage snippets around sage_eval, which is
    forbidden to callers precisely because it evaluates a string after this
    validator has approved the AST. Server-generated code is not attacker
    controlled, so it may use it -- but only after the *user* fragments
    interpolated into it have been validated in their own right. See
    server._validated_expression.

    Everything else in the policy still applies: generated code cannot import
    os, reach dunders, or call the other forbidden builtins.
    """
    base = policy or SECURITY_POLICY
    relaxed = tuple(name for name in base.forbidden_call_names if name not in _TRUSTED_CALLS)
    return replace(base, forbidden_call_names=relaxed)


# Evaluation entry points the server itself needs, and callers must not have.
_TRUSTED_CALLS = frozenset({"sage_eval", "preparse", "sage_input"})


def _is_dunder(name: str) -> bool:
    """True for names like __class__, __globals__, __builtins__."""
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _attribute_segments(node: ast.Attribute) -> list[str]:
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


def _is_allowed_import(module: str, policy: SecurityPolicy) -> bool:
    module = module or ""
    if module in policy.allowed_import_modules:
        return True
    return any(module.startswith(prefix) for prefix in policy.allowed_import_prefixes)


def validate_module(
    module: ast.Module, *, code: str | None = None, policy: SecurityPolicy | None = None
) -> None:
    """Validate *module* against the configured security policy."""
    policy = policy or SECURITY_POLICY
    if not policy.enabled:
        return

    source_length = len(code or "")
    if source_length > policy.max_source_chars:
        _raise_violation(
            f"Sage code exceeds maximum length ({source_length} > {policy.max_source_chars})",
            code=code,
            policy=policy,
        )

    node_count = sum(1 for _ in ast.walk(module))
    if node_count > policy.max_ast_nodes:
        _raise_violation(
            f"Sage code exceeds maximum AST node count ({node_count} > {policy.max_ast_nodes})",
            code=code,
            policy=policy,
        )

    depth = _max_depth(module)
    if depth > policy.max_ast_depth:
        _raise_violation(
            f"Sage code exceeds maximum AST depth ({depth} > {policy.max_ast_depth})",
            code=code,
            policy=policy,
        )

    for node in ast.walk(module):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and not policy.allow_imports:
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module] if node.module is not None else []
            if not modules:
                _raise_violation(
                    "Relative imports are disabled for Sage executions",
                    code=code,
                    policy=policy,
                )
            if not all(_is_allowed_import(mod, policy) for mod in modules):
                _raise_violation(
                    "Import statements are disabled for Sage executions",
                    code=code,
                    policy=policy,
                )
        if isinstance(node, ast.Global) and policy.forbid_global_stmt:
            _raise_violation(
                "Global statements are not permitted in Sage executions",
                code=code,
                policy=policy,
            )
        if isinstance(node, ast.Nonlocal) and policy.forbid_nonlocal_stmt:
            _raise_violation(
                "Nonlocal statements are not permitted in Sage executions",
                code=code,
                policy=policy,
            )
        # Dunder access is the shortest path out of the sandbox:
        # ().__class__.__bases__[0].__subclasses__() reaches subprocess.Popen,
        # and __builtins__ reaches __import__ by attribute or by subscript.
        # Blocking the whole namespace closes both in one rule.
        if isinstance(node, ast.Attribute) and _is_dunder(node.attr):
            _raise_violation(
                f"Access to dunder attribute '{node.attr}' is blocked",
                code=code,
                policy=policy,
            )
        if isinstance(node, ast.Name) and _is_dunder(node.id):
            _raise_violation(
                f"Access to dunder name '{node.id}' is blocked",
                code=code,
                policy=policy,
            )

        # A forbidden module is forbidden entirely. Requiring the attribute to
        # ALSO be on a list of eighteen names meant os.system was blocked while
        # os.listdir, os.environ and os.chmod were not -- and the README claimed
        # subprocess.*, pathlib.* and socket.* were blocked when none of them were.
        if isinstance(node, ast.Attribute):
            # Any segment, not just the root: sage.misc.temporary_file.os.getuid()
            # is rooted at the permitted `sage` and reaches os in the middle.
            for segment in _attribute_segments(node)[:-1]:
                if segment in policy.forbidden_attribute_parents:
                    _raise_violation(
                        f"Access through '{segment}' is blocked "
                        f"('{segment}' is not permitted in Sage executions)",
                        code=code,
                        policy=policy,
                    )
                    break

        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in policy.forbidden_call_names:
                _raise_violation(
                    f"Call to forbidden function '{func.id}' is blocked",
                    code=code,
                    policy=policy,
                )
            # Kept for bare calls such as system(...) that arrive via a star
            # import rather than through a module attribute.
            if isinstance(func, ast.Attribute) and func.attr in policy.forbidden_attribute_names:
                _raise_violation(
                    f"Call to forbidden attribute '{func.attr}' is blocked",
                    code=code,
                    policy=policy,
                )

    if policy.log_violations:
        LOGGER.debug(
            "Sage security validation passed (length=%s, nodes=%s, depth=%s)",
            source_length,
            node_count,
            depth,
        )


def validate_code(code: str, policy: SecurityPolicy | None = None) -> None:
    """Parse *code* and validate it against the policy."""
    try:
        module = ast.parse(code, mode="exec", type_comments=True)
    except SyntaxError as exc:  # pragma: no cover - already surfaced elsewhere
        raise SecurityViolation(f"Invalid Python syntax: {exc}") from exc
    validate_module(module, code=code, policy=policy)
