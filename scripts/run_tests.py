"""Project test launcher with named suites.

Examples:
    .venv/Scripts/python.exe scripts/run_tests.py fast
    .venv/Scripts/python.exe scripts/run_tests.py non-telegram
    .venv/Scripts/python.exe scripts/run_tests.py real-copilot
    .venv/Scripts/python.exe scripts/run_tests.py all --include-real
"""

from __future__ import annotations

import argparse
import os
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


NON_TELEGRAM_TESTS = [
    "tests.test_research_service",
    "tests.test_copilot_provider_sessions",
    "tests.test_chat_application_service",
    "tests.test_google_api_clients_setup",
    "tests.test_google_drive_client",
    "tests.test_google_oauth_clients",
    "tests.test_voice_input_service",
    "tests.test_non_telegram_session_scenarios",
    "tests.test_session_routing",
]

REAL_COPILOT_TESTS = [
    "tests.test_real_copilot_research_integration",
]


def build_suite_names(suite_name: str, include_real: bool) -> list[str]:
    normalized = suite_name.strip().lower()

    if normalized in {"fast", "unit", "non-telegram", "local"}:
        return list(NON_TELEGRAM_TESTS)

    if normalized == "real-copilot":
        return list(REAL_COPILOT_TESTS)

    if normalized == "all":
        selected = list(NON_TELEGRAM_TESTS)
        if include_real:
            selected.extend(REAL_COPILOT_TESTS)
        return selected

    raise ValueError(f"Unknown suite: {suite_name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run project test suites")
    parser.add_argument(
        "suite",
        nargs="?",
        default="fast",
        choices=["fast", "unit", "non-telegram", "local", "real-copilot", "all"],
        help="Named test suite to run",
    )
    parser.add_argument(
        "--include-real",
        action="store_true",
        help="Include real Copilot integration tests when suite is 'all'",
    )
    parser.add_argument(
        "--verbosity",
        type=int,
        default=2,
        choices=[0, 1, 2],
        help="unittest runner verbosity",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print selected tests without executing them",
    )
    args = parser.parse_args()

    suite_names = build_suite_names(args.suite, args.include_real)

    if args.suite == "real-copilot" or (args.suite == "all" and args.include_real):
        os.environ.setdefault("RUN_REAL_COPILOT_INTEGRATION", "1")

    print(f"Selected suite: {args.suite}")
    for test_name in suite_names:
        print(f" - {test_name}")

    if args.list:
        return 0

    suite = unittest.defaultTestLoader.loadTestsFromNames(suite_names)
    result = unittest.TextTestRunner(verbosity=args.verbosity).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())