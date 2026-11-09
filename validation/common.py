"""Utilidades de evidencia: solo registrar resultados reales, con hora y comando."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = "cloud-integrador-lab"
NAMESPACE = "cloud-integrador"
KUBECTL = ["kubectl", "--context", CONTEXT]


def redact(text):
    return re.sub(r"(Using generated security password:\s*)\S+", r"\1[REDACTED]", text)


def directory():
    pointer = ROOT / ".deployment/evidence-run.json"
    if not pointer.exists():
        name = "run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = ROOT / "evidence" / name
        destination.mkdir(parents=True)
        pointer.write_text(json.dumps({"directory": str(destination.relative_to(ROOT))}))
    return ROOT / json.loads(pointer.read_text())["directory"]


def capture(label, command, check=True, timeout=120):
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    text = (f"UTC: {datetime.now(timezone.utc).isoformat()}\n"
            f"$ {' '.join(command)}\nExit code: {result.returncode}\n\n{redact(result.stdout)}")
    (directory() / f"{label}.txt").write_text(text)
    print(text, flush=True)
    if check and result.returncode:
        raise RuntimeError(f"Falló {label}; ver evidencia del comando.")
    return result


def json_command(command):
    return json.loads(subprocess.check_output(command, text=True))
