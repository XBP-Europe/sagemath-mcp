#!/usr/bin/env python3
"""Standalone runner for CLI integration tests with rich reporting.

Usage::

    python -m tests.cli_integration.run_cli_tests --cli both --parallel
    python -m tests.cli_integration.run_cli_tests --cli claude --domain calculus
    python -m tests.cli_integration.run_cli_tests --cli gemini --domain algebra,number_theory
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from tests.cli_integration.cli_config import (  # noqa: E402
    ensure_docker_container,
    setup_claude_mcp_config,
    setup_gemini_mcp_config,
)
from tests.cli_integration.runner import run_claude, run_gemini  # noqa: E402
from tests.cli_integration.test_cases import ALL_TEST_CASES, DOMAINS, MathTestCase  # noqa: E402
from tests.cli_integration.validate import ValidationResult, validate  # noqa: E402


def _run_single(
    cli_name: str,
    runner_fn,
    case: MathTestCase,
) -> tuple[str, MathTestCase, ValidationResult]:
    """Run a single test case and return (cli_name, case, result)."""
    try:
        output, elapsed = runner_fn(case.prompt, timeout=case.timeout_seconds)
        result = validate(output, case, elapsed)
    except subprocess.TimeoutExpired:
        result = ValidationResult(
            status="TIMEOUT",
            matched_substring=None,
            response_excerpt=f"Timed out after {case.timeout_seconds}s",
            elapsed_seconds=float(case.timeout_seconds),
        )
    except RuntimeError as exc:
        result = ValidationResult(
            status="SKIP",
            matched_substring=None,
            response_excerpt=str(exc),
            elapsed_seconds=0.0,
        )
    return cli_name, case, result


def _print_results(
    cli_name: str,
    results: list[tuple[MathTestCase, ValidationResult]],
) -> int:
    """Print a formatted table and return the number of failures."""
    print(f"\n{'=' * 72}")
    print(f"CLI: {cli_name}")
    print(f"{'=' * 72}")
    print(
        f"{'Domain':<20} {'Tool':<28} {'ID':<10} {'Status':<12} {'Time':>6}"
    )
    print("-" * 72)

    failures = 0
    for case, result in results:
        status = result.status
        marker = {
            "PASS": "\033[32mPASS\033[0m",
            "SOFT_PASS": "\033[33mSOFT\033[0m",
            "FAIL": "\033[31mFAIL\033[0m",
            "ERROR": "\033[31mERROR\033[0m",
            "TIMEOUT": "\033[31mTIMEOUT\033[0m",
            "SKIP": "\033[90mSKIP\033[0m",
        }.get(status, status)
        time_str = f"{result.elapsed_seconds:.1f}s"
        print(
            f"{case.domain:<20} {case.tool_name:<28} {case.id:<10} "
            f"{marker:<21} {time_str:>6}"
        )
        if status in ("FAIL", "ERROR", "TIMEOUT"):
            failures += 1
            if result.response_excerpt:
                excerpt = result.response_excerpt[:120].replace("\n", " ")
                print(f"  \033[90m-> {excerpt}\033[0m")

    pass_count = sum(1 for _, r in results if r.status == "PASS")
    soft_count = sum(1 for _, r in results if r.status == "SOFT_PASS")
    fail_count = sum(1 for _, r in results if r.status in ("FAIL", "ERROR"))
    timeout_count = sum(1 for _, r in results if r.status == "TIMEOUT")
    skip_count = sum(1 for _, r in results if r.status == "SKIP")
    total = len(results)

    print("-" * 72)
    print(
        f"Summary: {pass_count}/{total} PASS, {soft_count} SOFT, "
        f"{fail_count} FAIL, {timeout_count} TIMEOUT, {skip_count} SKIP"
    )
    print("=" * 72)
    return failures


def _save_results(
    cli_name: str,
    results: list[tuple[MathTestCase, ValidationResult]],
) -> None:
    """Write JSON results to tests/cli_integration/results/."""
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    path = results_dir / f"{cli_name}_{timestamp}.json"
    data = [
        {
            "id": case.id,
            "tool": case.tool_name,
            "domain": case.domain,
            "status": result.status,
            "matched": result.matched_substring,
            "elapsed_seconds": result.elapsed_seconds,
            "excerpt": result.response_excerpt[:300],
        }
        for case, result in results
    ]
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Results saved to {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CLI integration tests")
    parser.add_argument(
        "--cli",
        choices=["claude", "gemini", "both"],
        default="both",
        help="Which CLI to test (default: both)",
    )
    parser.add_argument(
        "--domain",
        default=None,
        help="Comma-separated domain filter (e.g. calculus,algebra). Default: all.",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Run Claude and Gemini in parallel (default: sequential).",
    )
    args = parser.parse_args()

    # Filter test cases by domain
    if args.domain:
        domains = [d.strip() for d in args.domain.split(",")]
        cases = []
        for d in domains:
            if d not in DOMAINS:
                print(f"Unknown domain: {d}. Available: {', '.join(DOMAINS)}")
                return 1
            cases.extend(DOMAINS[d])
    else:
        cases = ALL_TEST_CASES

    print(f"Running {len(cases)} test cases")
    print(f"CLI: {args.cli}")
    if args.domain:
        print(f"Domains: {args.domain}")

    # Setup
    print("\nEnsuring Docker container is running...")
    try:
        ensure_docker_container()
    except Exception as exc:
        print(f"Docker setup failed: {exc}")
        print("Falling back to local uv-based server (pure Python, no real Sage)")

    restorers = []
    cli_runners: dict[str, callable] = {}

    if args.cli in ("claude", "both"):
        print("Configuring Claude Code CLI...")
        restorers.append(setup_claude_mcp_config())
        cli_runners["claude"] = run_claude

    if args.cli in ("gemini", "both"):
        print("Configuring Gemini CLI...")
        restorers.append(setup_gemini_mcp_config())
        cli_runners["gemini"] = run_gemini

    total_failures = 0

    try:
        if args.parallel and len(cli_runners) > 1:
            # Run both CLIs in parallel
            all_futures = []
            total_tasks = len(cases) * len(cli_runners)
            completed_count = 0
            with ThreadPoolExecutor(max_workers=2) as pool:
                for cli_name, runner_fn in cli_runners.items():
                    for case in cases:
                        future = pool.submit(_run_single, cli_name, runner_fn, case)
                        all_futures.append(future)

                # Collect results grouped by CLI
                cli_results: dict[str, list[tuple[MathTestCase, ValidationResult]]] = {
                    name: [] for name in cli_runners
                }
                _STATUS_MARKERS = {
                    "PASS": "\033[32mPASS\033[0m",
                    "SOFT_PASS": "\033[33mSOFT\033[0m",
                    "FAIL": "\033[31mFAIL\033[0m",
                    "ERROR": "\033[31mERROR\033[0m",
                    "TIMEOUT": "\033[31mTIMEOUT\033[0m",
                    "SKIP": "\033[90mSKIP\033[0m",
                }
                for future in as_completed(all_futures):
                    cli_name, case, result = future.result()
                    cli_results[cli_name].append((case, result))
                    completed_count += 1
                    marker = _STATUS_MARKERS.get(result.status, result.status)
                    print(
                        f"  [{completed_count}/{total_tasks}] {cli_name} | "
                        f"{case.domain:<16} {case.id:<10} "
                        f"{marker} ({result.elapsed_seconds:.1f}s)"
                    )

            for cli_name, results in cli_results.items():
                # Sort by original case order
                case_order = {c.id: i for i, c in enumerate(cases)}
                results.sort(key=lambda x: case_order.get(x[0].id, 999))
                total_failures += _print_results(cli_name, results)
                _save_results(cli_name, results)
        else:
            # Sequential with live progress
            for cli_name, runner_fn in cli_runners.items():
                results = []
                for i, case in enumerate(cases, 1):
                    print(
                        f"  [{i}/{len(cases)}] {cli_name} | {case.domain:<16} "
                        f"{case.id:<10} ...",
                        end="",
                        flush=True,
                    )
                    _, _, result = _run_single(cli_name, runner_fn, case)
                    marker = {
                        "PASS": "\033[32mPASS\033[0m",
                        "SOFT_PASS": "\033[33mSOFT\033[0m",
                        "FAIL": "\033[31mFAIL\033[0m",
                        "ERROR": "\033[31mERROR\033[0m",
                        "TIMEOUT": "\033[31mTIMEOUT\033[0m",
                        "SKIP": "\033[90mSKIP\033[0m",
                    }.get(result.status, result.status)
                    print(f" {marker} ({result.elapsed_seconds:.1f}s)")
                    results.append((case, result))
                total_failures += _print_results(cli_name, results)
                _save_results(cli_name, results)

    finally:
        print("\nRestoring CLI configurations...")
        for restore in restorers:
            try:
                restore()
            except Exception as exc:
                print(f"Warning: restore failed: {exc}")

    return 1 if total_failures > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
