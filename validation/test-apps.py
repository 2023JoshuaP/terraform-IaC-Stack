#!/usr/bin/env python3
"""Ejecuta pruebas en EKS y recupera reportes JUnit/JaCoCo sin credenciales locales en pods."""
import argparse
from datetime import datetime, timezone
import base64
import io
import json
import subprocess
import tarfile
import xml.etree.ElementTree as ET
from common import directory, KUBECTL, ROOT, redact

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("component", choices=["backend", "frontend"])
args = parser.parse_args()
component = args.component
record = json.loads((ROOT / ".deployment" / f"{component}-build.json").read_text())
repo = "ProceedHub" if component == "backend" else "HamukHub"
job_name = f"tests-{component}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}"
base = KUBECTL + ["-n", "cloud-build"]
test_command = ("gradle --no-daemon --max-workers=2 -Dorg.gradle.jvmargs=-Xmx1024m test jacocoTestReport"
                if component == "backend" else "npm ci && npm test -- --test-reporter=junit > /tmp/node-junit.txt")
archive_command = ("tar -czf /tmp/reports.tar.gz -C /workspace/build test-results reports" if component == "backend" else
                   "mkdir -p /workspace/build/test-results; cp /tmp/node-junit.txt /workspace/build/test-results/node.xml; tar -czf /tmp/reports.tar.gz -C /workspace/build test-results")
script = f"""
chmod +x gradlew 2>/dev/null || true
# Gradle 9.1.0 ya está instalado en la imagen; coincide con el wrapper del repo.
set +e
{test_command}
RESULT=$?
{archive_command}
ARCHIVE=$?
if [ "$ARCHIVE" -ne 0 ]; then exit 2; fi
echo TEST_REPORT_BEGIN
base64 /tmp/reports.tar.gz
echo TEST_REPORT_END
echo TEST_EXIT_CODE=$RESULT
exit "$RESULT"
"""
job = {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": job_name, "namespace": "cloud-build"},
       "spec": {"backoffLimit": 0, "activeDeadlineSeconds": 900, "ttlSecondsAfterFinished": 3600,
                "template": {"spec": {"restartPolicy": "Never", "automountServiceAccountToken": False,
                    "securityContext": {"runAsUser": 10001, "runAsGroup": 10001, "fsGroup": 10001, "runAsNonRoot": True},
                    "initContainers": [{"name": "checkout", "image": "alpine:3.22", "securityContext": {"runAsUser": 0, "runAsNonRoot": False},
                        "command": ["sh", "-ec", """
apk add --no-cache git ca-certificates
git init /workspace
git -C /workspace remote add origin "$REPOSITORY"
git -C /workspace fetch --depth 1 origin "$REVISION"
git -C /workspace checkout --detach FETCH_HEAD
chown -R 10001:10001 /workspace
"""], "env": [{"name": "REPOSITORY", "value": f"https://github.com/Natzgun/{repo}.git"},
                              {"name": "REVISION", "value": record["commit"]}],
                        "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"}]}],
                    "containers": [{"name": "tests", "image": "gradle:9.1.0-jdk25" if component == "backend" else "node:22-alpine",
                        "workingDir": "/workspace", "command": ["sh", "-c", script],
                        "env": [{"name": "HOME", "value": "/tmp"}, {"name": "GRADLE_USER_HOME", "value": "/tmp/gradle"},
                                {"name": "npm_config_cache", "value": "/tmp/npm"}],
                        "resources": {"requests": {"cpu": "500m", "memory": "1536Mi"}, "limits": {"cpu": "2", "memory": "3Gi"}},
                        "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"}]}],
                    "volumes": [{"name": "workspace", "emptyDir": {}}]}}}}
subprocess.run(KUBECTL + ["apply", "-f", "-"], input=json.dumps(job), text=True, check=True)
print(f"Pruebas {component} iniciadas en AWS para commit {record['commit']}", flush=True)
watch = subprocess.Popen(base + ["get", "job", job_name, "--watch", "--request-timeout=20m", "-o",
    'jsonpath={"succeeded="}{.status.succeeded}{" failed="}{.status.failed}{" conditions="}{.status.conditions[*].type}{"\\n"}'],
    stdout=subprocess.PIPE, text=True)
success = False
try:
    for line in watch.stdout:
        if "succeeded=1 " in line or "Complete" in line:
            success = True
            break
        if "failed=1 " in line or "Failed" in line or "FailureTarget" in line:
            break
finally:
    watch.terminate()
    watch.wait()
logs = subprocess.check_output(base + ["logs", f"job/{job_name}", "-c", "tests"], text=True)
destination = directory() / f"tests-{component}" / job_name
destination.mkdir(parents=True, exist_ok=True)
if "TEST_REPORT_BEGIN\n" not in logs or "\nTEST_REPORT_END" not in logs:
    (destination / "execution.log").write_text(redact(logs))
    raise SystemExit(f"No hubo reportes; revisar {destination / 'execution.log'}")
before, remaining = logs.split("TEST_REPORT_BEGIN\n", 1)
encoded, after = remaining.split("\nTEST_REPORT_END", 1)
(destination / "execution.log").write_text(redact(before + after))
blob = base64.b64decode(encoded)
(destination / "reports.tar.gz").write_bytes(blob)
with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
    archive.extractall(destination, filter="data")
for artifact in destination.rglob("*"):
    if artifact.is_file() and artifact.suffix in (".xml", ".html", ".txt", ".log"):
        artifact.write_text(redact(artifact.read_text()))
# El archivo descargable también contiene únicamente las versiones redactadas.
with tarfile.open(destination / "reports.tar.gz", "w:gz") as archive:
    for name in ("test-results", "reports"):
        if (destination / name).exists():
            archive.add(destination / name, arcname=name)

totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
for path in (destination / "test-results").rglob("*.xml"):
    text = path.read_text()
    # npm imprime un encabezado antes del documento JUnit.
    if "<testsuites" in text:
        text = text[text.index("<testsuites"):]
    elif "<?xml" in text:
        text = text[text.index("<?xml"):]
    root = ET.fromstring(text)
    # Node emite testcase directamente bajo testsuites; Gradle usa testsuite.
    cases = list(root.iter("testcase"))
    totals["tests"] += len(cases)
    for key, tag in (("failures", "failure"), ("errors", "error"), ("skipped", "skipped")):
        totals[key] += sum(case.find(tag) is not None for case in cases)
summary = {"component": component, "commit": record["commit"], "job": job_name, "job_succeeded": success,
           "report_directory": str(destination.relative_to(directory())), **totals}
coverage_file = destination / "reports/jacoco/test/jacocoTestReport.xml"
if coverage_file.exists():
    report = ET.parse(coverage_file).getroot()
    summary["coverage"] = {counter.get("type"): {"covered": int(counter.get("covered")), "missed": int(counter.get("missed"))}
                           for counter in report.findall("counter")}
(destination / "summary.json").write_text(json.dumps(summary, indent=2))
(destination.parent / "summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2), flush=True)
if not success or totals["tests"] == 0 or totals["failures"] or totals["errors"]:
    raise SystemExit("Pruebas no satisfactorias: consultar los reportes reales.")
