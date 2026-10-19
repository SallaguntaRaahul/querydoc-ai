"""Production-style launch check: build the frontend, start one FastAPI process
serving UI + API on a spare port (temporary workspace), verify the health
endpoint, the SPA shell, a client-side route and the OpenAPI docs, then stop.
Writes results/app/launch.json.

Usage: python scripts/check_app.py [--port 8199] [--skip-build]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def get(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=10) as r:  # noqa: S310 - localhost only
        return r.status, r.read().decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8199)
    ap.add_argument("--skip-build", action="store_true")
    args = ap.parse_args()
    node_bin = Path.home() / ".nvm" / "versions" / "node" / f"v{(ROOT / 'frontend' / '.nvmrc').read_text().strip()}" / "bin"
    env = {**os.environ, "PATH": f"{node_bin}:{os.environ['PATH']}"}
    result: dict[str, object] = {}
    if not args.skip_build:
        t = time.perf_counter()
        b = subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", env=env, capture_output=True, text=True)
        result["frontend_build"] = {"ok": b.returncode == 0, "seconds": round(time.perf_counter() - t, 1)}
        if b.returncode:
            print(b.stdout[-2000:], b.stderr[-2000:])
            return 1
    tmp = Path(tempfile.mkdtemp(prefix="qd-launch-"))
    env.update({"QUERYDOC_DATA_DIR": str(tmp), "QUERYDOC_LOAD_MODELS_ON_STARTUP": "false"})
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port)]
    proc = subprocess.Popen(cmd, cwd=ROOT / "backend", env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{args.port}"
    started = time.perf_counter()
    try:
        while time.perf_counter() - started < 180:
            if proc.poll() is not None:
                break
            try:
                status, body = get(f"{base}/api/v1/health")
                health = json.loads(body)
                result["backend_healthy"] = status == 200 and health["status"] in {"ok", "degraded"}
                result["seconds_to_healthy"] = round(time.perf_counter() - started, 2)
                s, html = get(f"{base}/")
                result["spa_served"] = s == 200 and '<div id="root">' in html
                s2, html2 = get(f"{base}/chat/some-conversation")
                result["spa_route_fallback"] = s2 == 200 and '<div id="root">' in html2
                s3, spec = get(f"{base}/api/openapi.json")
                result["openapi_paths"] = len(json.loads(spec)["paths"]) if s3 == 200 else 0
                break
            except OSError:
                time.sleep(0.5)
    finally:
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        shutil.rmtree(tmp, ignore_errors=True)
    result["log_tail"] = (out or "")[-1500:]
    result["command"] = "python scripts/check_app.py"
    result["timestamp_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    dest = ROOT / "results" / "app"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "launch.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "log_tail"}, indent=2))
    ok = all(result.get(k) for k in ("backend_healthy", "spa_served", "spa_route_fallback"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
