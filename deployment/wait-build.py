#!/usr/bin/env python3
"""Espera eventos del Job (watch, no sondeo) y falla si la construcción no termina bien."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("component", choices=["backend", "frontend"])
args = parser.parse_args()
record = json.loads((ROOT / ".deployment" / f"{args.component}-build.json").read_text())
cluster = subprocess.check_output([
    "terraform", f"-chdir={ROOT / 'stacks/network'}", "output", "-raw", "cluster_name"
], text=True).strip()
base = ["kubectl", "--context", cluster, "-n", record["namespace"]]
watch = subprocess.Popen(base + ["get", "job", record["job"], "--watch", "--request-timeout=35m", "-o",
    'jsonpath={"succeeded="}{.status.succeeded}{" failed="}{.status.failed}{" conditions="}{.status.conditions[*].type}{"\\n"}'],
    stdout=subprocess.PIPE, text=True)
code = 1
try:
    for line in watch.stdout:
        if "succeeded=1 " in line or "Complete" in line:
            print(f"Build {args.component} completado en AWS: {record['image']}", flush=True)
            code = 0
            break
        if "failed=1 " in line or "Failed" in line or "FailureTarget" in line:
            print(f"Build {args.component} falló; revisar logs del Job {record['job']}.", flush=True)
            break
finally:
    watch.terminate()
    watch.wait()
if code:
    subprocess.run(base + ["logs", f"job/{record['job']}", "-c", "build", "--tail=80"])
sys.exit(code)
