"""web/build.py: one version stamp on both pages, and every response stamped with the commit it was built from
(X-Commit, compared by the workflow and by /diag); the policies the page runs; the demo-mode timer (web/idle.js)."""

import json
import os
import pathlib
import shutil
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
    # every policy replay ships its ONNX policy and the recorded obs/action the page feeds it
    replays = json.loads((DIST / "data" / "replays.json").read_text(encoding="utf-8"))
    with_policy = [rp for rp in replays if rp["policy"]]
    assert with_policy, "no replay carries its policy"
    for rp in with_policy:
        assert (DIST / rp["policy"]).is_file()
        data = json.loads((DIST / "data" / f"{rp['name']}.json").read_text(encoding="utf-8"))
        assert len(data["obs"]) == len(data["action"]) == rp["frames"]
        assert len(data["obs"][0]) == 125 and len(data["action"][0]) == 29


def test_demo_timer_ignores_long_frames():
    """web/idle.test.mjs: 30 s idle starts demo mode; frames > 0.25 s do not count; input ends it."""
    node = shutil.which("node")
    assert node, "node is needed for the web viewer's JS tests (GitHub runners have it)"
    out = subprocess.run(
        [node, "--test", "--test-reporter=tap", str(ROOT / "web" / "idle.test.mjs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
    assert "# pass 3" in out.stdout and "# fail 0" in out.stdout, out.stdout[-2000:]
