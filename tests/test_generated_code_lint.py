"""Static checks over the Sage code that server.py generates.

These run without a Sage runtime, so they execute in the fast unit job and
catch whole bug classes in milliseconds rather than waiting for the integration
job to evaluate anything.

Each check corresponds to a defect that actually shipped:

* ``^`` in a generated template that is executed as Python, where it means XOR
  rather than exponentiation. geometry_operation computed the 3-4-5 triangle
  distance as sqrt(-3).
* ``save(_buf)`` on a Sage graphics object, which requires a filesystem path
  and rejects a BytesIO. All three plot tools were non-functional.
* A documented example that no test exercises, which is how issue #12 survived:
  ``solve_ode`` rejected the exact input its own docstring advertised.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SERVER_PATH = Path(__file__).resolve().parents[1] / "src" / "sagemath_mcp" / "server.py"
TESTS_DIR = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def server_source() -> str:
    return SERVER_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def server_tree(server_source: str) -> ast.Module:
    return ast.parse(server_source)


def _field_description_strings(tree: ast.Module) -> list[str]:
    """Every string that makes up a Field(description=...) value.

    Descriptions are frequently split across implicitly concatenated literals,
    so each piece is collected individually.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Field"):
            continue
        for keyword in node.keywords:
            if keyword.arg != "description":
                continue
            for sub in ast.walk(keyword.value):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    found.append(sub.value)
    return found


def _non_code_strings(tree: ast.Module) -> set[str]:
    """Strings where a ``^`` is legitimate and is not generated Python.

    Three sources: tool and parameter documentation, which quotes Sage syntax;
    regular expressions, where ``^`` anchors rather than XORs; and docstrings.
    """
    excluded = set(_field_description_strings(tree))

    for node in ast.walk(tree):
        # description= on @mcp.tool(...) as well as on Field(...)
        if isinstance(node, ast.Call):
            func = node.func
            is_compile = isinstance(func, ast.Attribute) and func.attr == "compile"
            # Error messages are prose shown to the caller, never executed, and
            # they legitimately mention notation such as 2^53.
            is_error = isinstance(func, ast.Name) and func.id in {
                "ToolError", "ValueError", "RuntimeError", "SageProcessError",
            }
            for keyword in node.keywords:
                if keyword.arg == "description":
                    for sub in ast.walk(keyword.value):
                        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                            excluded.add(sub.value)
            if is_compile or is_error:
                for arg in node.args:
                    for sub in ast.walk(arg):
                        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                            excluded.add(sub.value)
        # Docstrings describe behaviour; they are never executed.
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                excluded.add(doc)
    return excluded


def test_no_caret_in_generated_python(server_tree: ast.Module) -> None:
    """``^`` must not appear in generated code outside documentation.

    User expressions are safe because they go through sage_eval, whose
    preparser turns ``^`` into exponentiation. Code the server builds itself is
    executed as plain Python, where ``^`` is XOR and silently produces a wrong
    number instead of an error.
    """
    documentation = _non_code_strings(server_tree)

    offenders: list[str] = []
    for node in ast.walk(server_tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        text = node.value
        if "^" not in text or text in documentation:
            continue
        offenders.append(f"line {node.lineno}: {text.strip()[:90]!r}")

    assert not offenders, (
        "'^' means XOR in generated Python, not exponentiation. Use '**', or "
        "route the expression through sage_eval:\n" + "\n".join(f"  - {o}" for o in offenders)
    )


def test_no_sage_save_to_buffer(server_source: str) -> None:
    """Sage's save() needs a path and rejects a BytesIO.

    2D graphics render in memory via .matplotlib().savefig(); 3D is sampled and
    drawn through matplotlib's 3D axes. Neither may call save() on a buffer.
    """
    offenders = [
        f"line {number}: {line.strip()[:90]}"
        for number, line in enumerate(server_source.splitlines(), start=1)
        if re.search(r"(?<!fig)\.save\(\s*_buf", line)
    ]
    assert not offenders, (
        "Sage save() requires a filesystem path and raises "
        "'expected str, bytes or os.PathLike object' for a BytesIO. Render "
        "through matplotlib instead:\n" + "\n".join(f"  - {o}" for o in offenders)
    )


# Fragments that look like examples but are prose, enum listings, or values
# whose spelling is not what a caller passes.
_NOT_AN_EXAMPLE = re.compile(
    r"^(?:[\w ]+:|One of|Operation|Distribution name|Code constructor|Base ring|"
    r"Variable names|Polynomials|Sage group constructor|Graph constructor)",
)


def _documented_examples(tree: ast.Module) -> set[str]:
    """Quoted example values embedded in Field descriptions."""
    examples: set[str] = set()
    for text in _field_description_strings(tree):
        if not re.search(r"e\.g\.|like", text):
            continue
        # Quoted fragments are the examples: 'x^2 - 1 = 0', 'PetersenGraph', ...
        for quoted in re.findall(r"'([^']{2,})'", text):
            if _NOT_AN_EXAMPLE.match(quoted):
                continue
            examples.add(quoted.strip())
    return examples


def test_every_documented_example_is_exercised(server_tree: ast.Module) -> None:
    """Anything the tools advertise must appear in a test.

    This is the guard that makes issue #12 structurally impossible. #12 was a
    documented spelling that had never been executed by a test, and the
    documented-example suite then found six more of the same kind. Enforcing
    the link mechanically beats relying on reviewer diligence.
    """
    examples = _documented_examples(server_tree)
    assert examples, "no documented examples were extracted; the parser has drifted"

    corpus = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(TESTS_DIR.glob("test_*.py"))
    )

    missing = sorted(example for example in examples if example not in corpus)
    assert not missing, (
        "These examples are advertised in a tool's Field description but never "
        "exercised by a test. Add a case, or stop documenting the spelling:\n"
        + "\n".join(f"  - {example!r}" for example in missing)
    )


# Modules the README's security table promises are blocked wholesale. The table
# previously claimed subprocess.*, pathlib.* and socket.* while the validator
# allowed every one of them, so this asserts the promise against the code.
README_BLOCKED_MODULES = ["os", "sys", "subprocess", "shutil", "socket", "pathlib"]

README_BLOCKED_BUILTINS = [
    "eval", "exec", "compile", "open", "input", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "sage_eval", "preparse", "sage_input",
]


def test_readme_security_table_matches_the_policy() -> None:
    """Every protection the README advertises must actually be enforced."""
    import ast as _ast

    from sagemath_mcp.security import SECURITY_POLICY, SecurityViolation, validate_module

    def rejects(code: str) -> bool:
        try:
            validate_module(_ast.parse(code), code=code, policy=SECURITY_POLICY)
        except SecurityViolation:
            return True
        return False

    unenforced: list[str] = []
    for module in README_BLOCKED_MODULES:
        # An arbitrary attribute, not one of the historically named ones.
        if not rejects(f"{module}.some_arbitrary_attribute"):
            unenforced.append(f"{module}.* is documented as blocked but is allowed")
    for builtin in README_BLOCKED_BUILTINS:
        if not rejects(f"{builtin}('x')"):
            unenforced.append(f"{builtin}() is documented as blocked but is allowed")
        # Call position is not enough. This test used to check only the spelling
        # above, which is why `f = open` survived it: the README said "blocked"
        # and the test agreed, while an alias walked straight through.
        for spelling, label in (
            (f"f = {builtin}", "alias assignment"),
            (f"(lambda f={builtin}: f)()", "lambda default"),
            (f"[{builtin}][0]", "container literal"),
        ):
            if not rejects(spelling):
                unenforced.append(f"{builtin} is reachable by {label}: {spelling!r}")
    for payload in ("().__class__", "obj.__globals__", "__builtins__.__import__"):
        if not rejects(payload):
            unenforced.append(f"dunder access {payload!r} is documented as blocked but is allowed")

    assert not unenforced, "README promises protections the policy does not enforce:\n" + "\n".join(
        f"  - {item}" for item in unenforced
    )


def test_readme_documents_the_modules_the_policy_blocks() -> None:
    """The reverse direction: no silently-enforced module missing from the docs."""
    from sagemath_mcp.security import SECURITY_POLICY

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    missing = [
        module
        for module in SECURITY_POLICY.forbidden_attribute_parents
        if f"`{module}`" not in readme
    ]
    assert not missing, f"policy blocks modules the README never mentions: {missing}"
