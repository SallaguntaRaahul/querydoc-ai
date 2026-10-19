"""Launch the Streamlit app headlessly, wait for its health endpoint and the
first page render, then stop it. Writes results/streamlit/launch.json.

Usage:  python scripts/check_streamlit.py [--port 8599]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def get(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 - localhost only
        return resp.status, resp.read().decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8599)
    ap.add_argument("--timeout", type=float, default=120)
    args = ap.parse_args()
    env = {**os.environ, "QUERYDOC_DATA_DIR": str(ROOT / "results" / "tmp" / "streamlit_workspace")}
    cmd = [sys.executable, "-m", "streamlit", "run", str(ROOT / "app" / "main.py"),
           "--server.headless", "true", "--server.port", str(args.port), "--browser.gatherUsageStats", "false"]
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    started = time.perf_counter()
    result = {"command": " ".join(cmd[1:]), "healthy": False, "page_served": False}
    try:
        while time.perf_counter() - started < args.timeout:
            if proc.poll() is not None:
                break
            try:
                status, body = get(f"http://localhost:{args.port}/_stcore/health")
                if status == 200 and body.strip() == "ok":
                    result["healthy"] = True
                    result["seconds_to_healthy"] = round(time.perf_counter() - started, 2)
                    status, html = get(f"http://localhost:{args.port}/")
                    result["page_served"] = status == 200 and "<div id=\"root\">" in html
                    break
            except OSError:
                time.sleep(0.5)
    finally:
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
    result["log_tail"] = out[-2000:] if out else ""
    result["timestamp_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    dest = ROOT / "results" / "streamlit"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "launch.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "log_tail"}, indent=2))
    return 0 if result["healthy"] and result["page_served"] else 1


if __name__ == "__main__":
    sys.exit(main())
