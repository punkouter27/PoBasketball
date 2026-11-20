"""Refresh docs/phase_reports/A8_determinism.md from a fresh A8 run (GPU). Opt-in: the pytest test never writes it.

uv run python tools/a8_determinism_report.py
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import test_determinism as a8  # noqa: E402

OUT = ROOT.parent / "docs" / "phase_reports" / "A8_determinism.md"

if __name__ == "__main__":
    text = a8.report_markdown(a8.measure())
    OUT.write_text(text, encoding="utf-8")
    print(text)
    print(f"wrote {OUT}")
