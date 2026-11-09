#!/usr/bin/env python3
"""k6 remoto y observación temporal real de HPA/CPU/memoria. No cambia réplicas manualmente."""
import csv
from datetime import datetime, timezone
import io
import json
import subprocess
import time
from common import capture, directory, json_command, KUBECTL, NAMESPACE, ROOT

name = "k6-login-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
namespace = "cloud-build"
script = (ROOT / "validation/load.js").read_text()
objects = [
    {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": name, "namespace": namespace}, "data": {"load.js": script}},
    {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name, "namespace": namespace},
     "spec": {"backoffLimit": 0, "activeDeadlineSeconds": 300, "ttlSecondsAfterFinished": 3600,
              "template": {"spec": {"restartPolicy": "Never", "automountServiceAccountToken": False,
                  "securityContext": {"runAsNonRoot": True, "runAsUser": 12345, "runAsGroup": 12345},
                  "containers": [{"name": "k6", "image": "grafana/k6:1.3.0", "args": ["run", "/scripts/load.js"],
                      "resources": {"requests": {"cpu": "250m", "memory": "128Mi"}, "limits": {"cpu": "1", "memory": "512Mi"}},
                      "volumeMounts": [{"name": "script", "mountPath": "/scripts", "readOnly": True}]}],
                  "volumes": [{"name": "script", "configMap": {"name": name}}]}}}},
]
for obj in objects:
    subprocess.run(KUBECTL + ["apply", "-f", "-"], input=json.dumps(obj), text=True, check=True)
print(f"Carga acotada iniciada: {name}. Máximo 16 login/s, 180 segundos, un usuario sintético.", flush=True)
print("Se observará también la reducción automática de réplicas, sin scale manual.", flush=True)

base = KUBECTL + ["-n", NAMESPACE]
started = time.monotonic()
finished_at = None
rows = []
scale_up_recorded = False
success = False
destination = directory()


def cpu_milli(value):
    if value.endswith("n"):
        return float(value[:-1]) / 1e6
    if value.endswith("u"):
        return float(value[:-1]) / 1e3
    if value.endswith("m"):
        return float(value[:-1])
    return float(value) * 1000


def memory_mib(value):
    for suffix, factor in (("Ki", 1 / 1024), ("Mi", 1), ("Gi", 1024)):
        if value.endswith(suffix):
            return float(value[:-len(suffix)]) * factor
    return float(value) / 1024**2


while time.monotonic() - started < 480:
    now = time.monotonic()
    hpa = json_command(base + ["get", "hpa", "backend", "-o", "json"])["status"]
    pods = json_command(base + ["get", "pods", "-o", "json"])["items"]
    metrics = json_command(KUBECTL + ["get", "--raw", f"/apis/metrics.k8s.io/v1beta1/namespaces/{NAMESPACE}/pods"])["items"]
    cpu = next((item["resource"]["current"].get("averageUtilization") for item in hpa.get("currentMetrics", [])
                if item.get("resource", {}).get("name") == "cpu"), None)
    backend_names = {pod["metadata"]["name"] for pod in pods if pod["metadata"].get("labels", {}).get("app") == "backend"}
    usage = [container["usage"] for item in metrics if item["metadata"]["name"] in backend_names for container in item["containers"]]
    ready = sum(1 for pod in pods if pod["metadata"]["name"] in backend_names and not pod["metadata"].get("deletionTimestamp")
                and any(condition["type"] == "Ready" and condition["status"] == "True" for condition in pod["status"].get("conditions", [])))
    row = {"utc": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": round(now - started, 1),
           "backend_current": hpa.get("currentReplicas"), "backend_desired": hpa.get("desiredReplicas"),
           "backend_ready": ready, "backend_cpu_percent": cpu,
           "backend_cpu_millicores": round(sum(cpu_milli(item["cpu"]) for item in usage), 2) if usage else None,
           "backend_memory_mib": round(sum(memory_mib(item["memory"]) for item in usage), 2) if usage else None,
           "phase": "cooldown" if finished_at is not None else "load"}
    rows.append(row)
    (destination / "load-timeseries.json").write_text(json.dumps(rows, indent=2))
    print(json.dumps(row), flush=True)
    if not scale_up_recorded and (hpa.get("currentReplicas", 1) > 1 or hpa.get("desiredReplicas", 1) > 1):
        capture("load-scale-up", base + ["get", "pods,hpa", "-o", "wide"])
        scale_up_recorded = True
    job = json_command(KUBECTL + ["-n", namespace, "get", "job", name, "-o", "json"])
    status = job.get("status", {})
    done = status.get("succeeded", 0) > 0 or status.get("failed", 0) > 0
    if done and finished_at is None:
        finished_at = time.monotonic()
        success = status.get("succeeded", 0) > 0
        logs = subprocess.check_output(KUBECTL + ["-n", namespace, "logs", f"job/{name}", "-c", "k6"], text=True)
        (destination / "load-k6.log").write_text(logs)
        if "K6_SUMMARY_BEGIN\n" in logs:
            summary = json.loads(logs.split("K6_SUMMARY_BEGIN\n", 1)[1].split("\nK6_SUMMARY_END", 1)[0])
            (destination / "load-k6-summary.json").write_text(json.dumps(summary, indent=2))
        print(f"k6 terminó; éxito={success}. Observando cooldown automático.", flush=True)
    if finished_at is not None and time.monotonic() - finished_at >= 130 and hpa.get("currentReplicas") == 1 and hpa.get("desiredReplicas") == 1:
        break
    # Muestreo de telemetría con cadencia explícita; no es espera por un proceso local.
    time.sleep(10)

with (destination / "load-timeseries.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
result = {"job": name, "k6_succeeded": success, "scale_up_observed": scale_up_recorded,
          "max_replicas": max(row["backend_current"] or 0 for row in rows),
          "scaled_back_to_one": finished_at is not None and rows[-1]["backend_current"] == 1 and rows[-1]["backend_desired"] == 1,
          "samples": len(rows), "observed_seconds": rows[-1]["elapsed_seconds"],
          "target": "POST /api/users/login via Service interno, aplicación y RDS reales"}
(destination / "load-result.json").write_text(json.dumps(result, indent=2))
capture("load-final-hpa", base + ["describe", "hpa", "backend"])
capture("load-final-events", base + ["get", "events", "--sort-by=.lastTimestamp"])
print(json.dumps(result, indent=2), flush=True)
if not success or not scale_up_recorded or not result["scaled_back_to_one"]:
    raise SystemExit("La evidencia no cumple todas las condiciones: revisar métricas y umbrales, sin asumir éxito.")
