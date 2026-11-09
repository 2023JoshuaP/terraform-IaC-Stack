#!/usr/bin/env python3
"""Elimina un solo pod y comprueba su reemplazo. Puede haber interrupción con una réplica."""
import json
import time
from common import capture, directory, json_command, KUBECTL, NAMESPACE

base = KUBECTL + ["-n", NAMESPACE]
before = json_command(base + ["get", "pods", "-l", "app=backend", "-o", "json"])
pods = [pod for pod in before["items"] if not pod["metadata"].get("deletionTimestamp")]
if len(pods) != 1:
    raise SystemExit("Esta demostración requiere exactamente un pod backend antes de empezar; no eliminar varios pods.")
old = pods[0]["metadata"]["name"]
old_uid = pods[0]["metadata"]["uid"]
capture("recovery-before", base + ["get", "pods", "-l", "app=backend", "-o", "wide"])
started = time.monotonic()
capture("recovery-delete", base + ["delete", "pod", old, "--wait=true", "--timeout=90s"])
capture("recovery-ready", base + ["wait", "--for=condition=Ready", "pod", "-l", "app=backend", "--timeout=300s"], timeout=320)
after = json_command(base + ["get", "pods", "-l", "app=backend", "-o", "json"])
new = [pod for pod in after["items"] if pod["metadata"]["uid"] != old_uid and not pod["metadata"].get("deletionTimestamp")]
if not new:
    raise SystemExit("No se encontró un reemplazo con UID diferente; revisar eventos.")
result = {"old_pod": old, "old_uid": old_uid, "new_pod": new[0]["metadata"]["name"],
          "new_uid": new[0]["metadata"]["uid"], "observed_seconds": round(time.monotonic() - started, 2)}
(directory() / "recovery-result.json").write_text(json.dumps(result, indent=2))
capture("recovery-after", base + ["get", "pods", "-l", "app=backend", "-o", "wide"])
capture("recovery-events", base + ["get", "events", "--sort-by=.lastTimestamp"])
print(json.dumps(result, indent=2))
