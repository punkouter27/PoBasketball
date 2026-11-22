"""web/build.py: one version stamp on both pages, and every response stamped with the commit it was built from
(X-Commit, compared by the workflow and by /diag)."""

import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DIST = ROOT / "web" / "dist"


def test_build_stamps_version_and_commit():
    sha = "0123456789abcdef0123456789abcdef01234567"
    out = subprocess.run(
        [sys.executable, str(ROOT / "web" / "build.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "GITHUB_SHA": sha},
        timeout=600,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    swa = json.loads((DIST / "staticwebapp.config.json").read_text(encoding="utf-8"))
    assert swa["globalHeaders"]["X-Commit"] == sha
    diag = (DIST / "diag.html").read_text(encoding="utf-8")
    assert f'<meta name="po-commit" content="{sha}">' in diag
    checks = json.loads((DIST / "diag_checks.json").read_text(encoding="utf-8"))["checks"]
    assert any(c["kind"] == "commit" for c in checks)
    index = (DIST / "index.html").read_text(encoding="utf-8")
    ver = next(line for line in out.stdout.splitlines() if line.startswith("version v")).split()[-1]
    assert index.count(ver) == 1 and "{{" not in index and "{{" not in diag
