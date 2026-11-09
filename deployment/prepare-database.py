#!/usr/bin/env python3
"""Genera inputs locales de RDS y secretos aleatorios, sin mostrarlos en terminal."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]
directory = ROOT / ".deployment"
directory.mkdir(mode=0o700, exist_ok=True)
os.chmod(directory, 0o700)

def write_private(path, data):
    # No truncar un archivo existente: preservar valores y contraseñas del operador.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, indent=2)

secret_file = directory / "secrets.json"
if not secret_file.exists():
    write_private(secret_file, {"DB_PASSWORD": secrets.token_hex(24), "JWT_TOKEN": secrets.token_hex(32)})
credentials = json.loads(secret_file.read_text())
network = json.loads(subprocess.check_output([
    "terraform", f"-chdir={ROOT / 'stacks/network'}", "output", "-json"
], text=True))
values = {
    "vpc_id": network["vpc_id"]["value"],
    "subnet_ids": network["private_subnet_ids"]["value"],
    "source_security_group_id": network["node_security_group_id"]["value"],
    "password": credentials["DB_PASSWORD"],
    "deletion_protection": True,
    "skip_final_snapshot": False,
    "final_snapshot_identifier": f"cloud-integrador-final-{datetime.now(timezone.utc):%Y%m%d%H%M%S}",
    "log_retention_days": 1,
}
destination = ROOT / "stacks/database/deployment.auto.tfvars.json"
if destination.exists():
    previous = json.loads(destination.read_text())
    if any(previous.get(key) != values[key] for key in ("vpc_id", "subnet_ids", "source_security_group_id", "password")):
        raise SystemExit("Los inputs existentes difieren: revisar manualmente sin sobrescribirlos.")
else:
    write_private(destination, values)
print("Inputs de RDS preparados. Secretos conservados en archivos locales privados e ignorados por Git.")
