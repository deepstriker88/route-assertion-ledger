"""Reproducible maximum-operation packaged CLI benchmark; synthetic inputs only."""
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    paths, records, required = {}, [], {}
    codes = (200, 201, 400, 404, 500)
    for i in range(1000):
        path = f"/resource/{i}/{{id}}"
        operation = f"GET {path}"
        paths[path] = {"get": {"responses": {str(c): {} for c in codes}}}
        records.extend({"operation": operation, "status": c, "asserted": True} for c in codes)
        required[operation] = list(codes)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        archive = tmp / "route-assertion-ledger.pyz"
        subprocess.run([sys.executable, str(ROOT / "build_zipapp.py"), str(archive)],
                       check=True, timeout=10)
        inputs = (("spec.json", {"openapi": "3.1.0", "paths": paths}),
                  ("evidence.json", records),
                  ("policy.json", {"required_statuses": required, "assert_all_observed": True}))
        for name, value in inputs:
            (tmp / name).write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
        times = []
        for i in range(3):
            start = time.monotonic()
            result = subprocess.run([sys.executable, str(archive), str(tmp / "spec.json"),
                                     str(tmp / "evidence.json"), "--policy", str(tmp / "policy.json"),
                                     "--html", str(tmp / f"report-{i}.html")],
                                    capture_output=True, check=True, timeout=15)
            times.append(time.monotonic() - start)
            data = json.loads(result.stdout)
            if not data["ok"] or data["summary"]["covered"] != 1000 or data["summary"]["observations"] != 5000:
                raise RuntimeError("benchmark result mismatch")
        rss = None
        try:
            import resource
            rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
            if sys.platform == "darwin":
                rss /= 1024
        except ImportError:
            pass
        print(json.dumps({"python": sys.version.split()[0], "platform": sys.platform,
                          "operations": 1000, "records": 5000,
                          "input_bytes": sum((tmp / name).stat().st_size for name, _ in inputs),
                          "package_bytes": archive.stat().st_size, "runs_seconds": times,
                          "median_seconds": statistics.median(times),
                          "max_child_rss_kib": rss, "result": "passed"}, indent=2))


if __name__ == "__main__":
    main()
