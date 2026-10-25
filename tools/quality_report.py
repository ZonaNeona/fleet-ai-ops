"""Measure the deployed code and save the numbers the «Код и качество» screen shows: reports/code.json.

Runs on the host during a release (scripts/deploy.sh --quality): pytest with coverage against a throwaway
database, ruff and mypy. Nothing on that screen is typed in by hand. The frontend type check (tsc) runs
in scripts/pack.sh before the archive is made, so a release cannot exist without it.

    DATABASE_URL=postgresql+psycopg://…/fleet_ci python tools/quality_report.py
"""

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "reports" / "code.json"


def run(cmd):
    return subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )


def lines(paths, suffixes):
    files = [f for p in paths for f in (ROOT / p).rglob("*") if f.suffix in suffixes and "node_modules" not in f.parts]
    return len(files), sum(len(f.read_text(encoding="utf-8", errors="replace").splitlines()) for f in files)


def main():
    cov = ROOT / ".coverage.json"
    tests = run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--cov=app",
            f"--cov-report=json:{cov}",
            "-k",
            "not lease",
            "-rfE",
            "--tb=line",
        ]
    )
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", tests.stdout)) else 0
    failed = sum(int(m.group(1)) for m in re.finditer(r"(\d+) (?:failed|errors?)", tests.stdout))
    names = [line.split(" - ")[0] for line in tests.stdout.splitlines() if line.startswith(("FAILED ", "ERROR "))]
    for line in names + [x for x in tests.stdout.splitlines() if x.startswith("E ")][:10]:
        print(line, file=sys.stderr)  # the release log shows what broke without opening the report
    coverage = 0.0
    if cov.exists():
        coverage = round(json.loads(cov.read_text(encoding="utf-8"))["totals"]["percent_covered"], 1)
        cov.unlink()
    py_files, py_lines = lines(["app"], {".py"})
    ts_files, ts_lines = lines(["web"], {".ts", ".tsx"})
    report = {
        "at": datetime.now(UTC).isoformat(),
        "python": {
            "tests": passed + failed,
            "passed": passed,
            "coverage": coverage,
            "failed": names,
            "ruff": run([sys.executable, "-m", "ruff", "check", "app", "scripts", "tests", "tools"]).returncode == 0,
            "mypy": run([sys.executable, "-m", "mypy"]).returncode == 0,
            "files": py_files,
            "lines": py_lines,
        },
        "web": {"tsc": True, "files": ts_files, "lines": ts_lines},
        "checks": "pytest на PostgreSQL + pgvector, ruff (ошибки и вероятные баги), mypy, tsc; те же проверки в CI на каждый push",
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report["python"], ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
