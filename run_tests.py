"""
run_tests.py — Main entry point for Derived Value Test Framework
================================================================

Usage examples:
  python run_tests.py                        # UAT, all tests
  python run_tests.py --env uat              # UAT, all tests
  python run_tests.py --env prod             # PROD, all tests
  python run_tests.py --env uat --tc tc01_tc05       # UAT, specific test file
  python run_tests.py --env prod --tc tc01_tc05      # PROD, TC-01..05 only
  python run_tests.py --env uat --no-report          # run without opening browser

Report is saved to:  reports/<env>_<timestamp>/index.html
"""

import argparse
import os
import subprocess
import sys
import shutil
from datetime import datetime


ALLURE_RESULTS_DIR = "allure-results"
REPORTS_BASE_DIR   = "reports"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_allure() -> str | None:
    """Return the allure executable path, or None if not found."""
    return shutil.which("allure")


def _banner(msg: str):
    width = len(msg) + 4
    print("\n" + "=" * width, flush=True)
    print(f"  {msg}", flush=True)
    print("=" * width + "\n", flush=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Derived Value Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--env",
        choices=["uat", "prod"],
        default="uat",
        help="Target environment (default: uat)",
    )
    parser.add_argument(
        "--tc",
        default="all",
        metavar="MODULE",
        help="Test module to run, e.g. tc01_tc05  (default: all tests)",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Skip Allure report generation and browser launch",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Wipe allure-results before running (fresh run)",
    )
    args = parser.parse_args()

    # ── Pre-flight ────────────────────────────────────────────────────────────
    env_file = os.path.join("environments", f"{args.env}.env")
    if not os.path.exists(env_file):
        print(f"[ERROR] Environment file not found: {env_file}")
        print(f"        Create it or use --env uat / --env prod")
        sys.exit(1)

    timestamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir   = os.path.join(REPORTS_BASE_DIR, f"{args.env}_{timestamp}")
    test_path    = "tests/" if args.tc == "all" else f"tests/test_{args.tc}.py"

    if not os.path.exists(test_path.rstrip("/")):
        print(f"[ERROR] Test path not found: {test_path}")
        sys.exit(1)

    # ── Clean previous results ────────────────────────────────────────────────
    if args.clean and os.path.exists(ALLURE_RESULTS_DIR):
        shutil.rmtree(ALLURE_RESULTS_DIR)
        print(f"[INFO] Cleaned {ALLURE_RESULTS_DIR}/", flush=True)

    os.makedirs(ALLURE_RESULTS_DIR, exist_ok=True)
    os.makedirs(REPORTS_BASE_DIR,   exist_ok=True)

    # ── Run pytest ────────────────────────────────────────────────────────────
    _banner(f"Running tests  |  env={args.env.upper()}  |  suite={args.tc}")

    pytest_cmd = [
        sys.executable, "-m", "pytest",
        test_path,
        f"--env={args.env}",
        f"--alluredir={ALLURE_RESULTS_DIR}",
        "--tb=short",
        "-v",
        "-n", "auto",          # run test files in parallel (requires pytest-xdist)
        "--dist", "loadfile",  # keep tests from the same file on the same worker
    ]

    print(f"[CMD] {' '.join(pytest_cmd)}\n", flush=True)
    sys.stdout.flush()
    pytest_result = subprocess.run(pytest_cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
    exit_code = pytest_result.returncode

    # ── Generate Allure HTML report ───────────────────────────────────────────
    if args.no_report:
        _banner("Tests complete — report generation skipped (--no-report)")
        sys.exit(exit_code)

    allure_bin = _find_allure()
    if not allure_bin:
        _banner("Allure CLI not found — skipping HTML report")
        print("  Install Allure CLI to generate reports:")
        print("    scoop install allure    (Windows/Scoop)")
        print("    brew install allure     (Mac/Homebrew)")
        print("    npm i -g allure-commandline")
        print(f"\n  Raw results are in: {ALLURE_RESULTS_DIR}/")
        sys.exit(exit_code)

    _banner(f"Generating Allure report -> {report_dir}/")

    allure_cmd = [
        allure_bin, "generate",
        ALLURE_RESULTS_DIR,
        "--output", report_dir,
        "--clean",
        "--name", f"Derived Value Validation — {args.env.upper()} — {timestamp}",
    ]

    print(f"[CMD] {' '.join(allure_cmd)}\n", flush=True)
    sys.stdout.flush()
    gen_result = subprocess.run(allure_cmd, cwd=os.path.dirname(os.path.abspath(__file__)))

    if gen_result.returncode != 0:
        print("[ERROR] Allure report generation failed.")
        sys.exit(exit_code)

    report_index = os.path.join(report_dir, "index.html")
    print(f"\n[DONE] Report saved: {report_index}", flush=True)

    # ── Serve via allure open (required — file:// blocks JS in modern browsers) ─
    print("[INFO] Starting Allure web server — report will open in browser ...", flush=True)
    print("[INFO] Press Ctrl+C to stop the server when done.\n", flush=True)
    sys.stdout.flush()

    subprocess.run(
        [allure_bin, "open", report_dir],
        cwd=os.path.dirname(os.path.abspath(__file__))
    )

    # Exit with pytest's exit code so CI/CD picks up failures
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
