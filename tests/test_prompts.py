"""The MCP prompts steer a client toward verified, stateful use.

They return plain instruction text (never executed), so the tests just render
each one and check it names the tool that makes the difference.
"""

from __future__ import annotations

from fastmcp import Client

from sagemath_mcp import server


async def _render(name: str, args: dict) -> str:
    async with Client(server.mcp) as client:
        result = await client.get_prompt(name, args)
        return "".join(
            m.content.text for m in result.messages if hasattr(m.content, "text")
        )


async def test_prompts_are_registered():
    async with Client(server.mcp) as client:
        names = {p.name for p in await client.list_prompts()}
    assert {"prove_and_verify", "solve_and_check", "explore_object"} <= names


async def test_prove_and_verify_points_at_verify_claim():
    text = await _render("prove_and_verify", {"claim": "sin(x)^2 + cos(x)^2 == 1"})
    assert "verify_claim" in text
    assert "sin(x)^2 + cos(x)^2 == 1" in text


async def test_solve_and_check_asks_for_a_check():
    text = await _render("solve_and_check", {"problem": "the real roots of x^3 - 2*x + 1"})
    assert "x^3 - 2*x + 1" in text
    assert "check" in text.lower()


async def test_explore_object_keeps_state_in_evaluate_sage():
    text = await _render("explore_object", {"construction": "the elliptic curve y^2 = x^3 - x"})
    assert "y^2 = x^3 - x" in text
    assert "evaluate_sage" in text
