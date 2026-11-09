#!/usr/bin/env python3
"""Valida IaC, demuestra una actualización reversible de etiqueta y solo PLANIFICA borrado."""
import json
import subprocess
from common import capture, directory, ROOT

for stack in ("backend", "frontend", "network", "database"):
    tf = ["terraform", f"-chdir={ROOT / 'stacks' / stack}"]
    capture(f"iac-{stack}-validate", tf + ["validate", "-no-color"])
    capture(f"iac-{stack}-tests", tf + ["test", "-no-color"], timeout=180)
    capture(f"iac-{stack}-baseline-plan", tf + ["plan", "-input=false", "-no-color", "-detailed-exitcode",
            "-var-file=../../config/common.tfvars"], timeout=180)

tf = ["terraform", f"-chdir={ROOT / 'stacks/backend'}"]
repository_arn = subprocess.check_output(tf + ["output", "-raw", "repository_arn"], text=True).strip()
tags = json.loads(subprocess.check_output(["aws", "ecr", "list-tags-for-resource", "--region", "us-east-1",
                                         "--resource-arn", repository_arn], text=True))["tags"]
variables = {tag["Key"]: tag["Value"] for tag in tags if tag["Key"] not in ("ManagedBy", "Stack")}
variables["EvidenceRun"] = directory().name
plan_file = ROOT / ".deployment/evidence-tag-update.tfplan"
restore_file = ROOT / ".deployment/evidence-tag-restore.tfplan"


def verify_tag_only(path):
    data = json.loads(subprocess.check_output(tf + ["show", "-json", str(path)], text=True))
    for change in data.get("resource_changes", []):
        actions = change["change"]["actions"]
        if actions == ["no-op"]:
            continue
        if change["address"] != "aws_ecr_repository.this" or actions != ["update"]:
            raise RuntimeError("La demostración propuso cambios fuera de la etiqueta ECR; no aplicar.")
        before, after = change["change"]["before"], change["change"]["after"]
        changed = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
        if not changed <= {"tags", "tags_all"}:
            raise RuntimeError(f"Cambios inesperados: {changed}. No aplicar.")


capture("iac-tag-update-plan", tf + ["plan", "-input=false", "-no-color", "-var-file=../../config/common.tfvars",
        "-var", "tags=" + json.dumps(variables), "-out=" + str(plan_file)], timeout=180)
verify_tag_only(plan_file)
try:
    capture("iac-tag-update-apply", tf + ["apply", "-input=false", "-no-color", str(plan_file)], timeout=180)
finally:
    # Volver a la configuración declarada habitual, incluso si la operación anterior falla.
    capture("iac-tag-restore-plan", tf + ["plan", "-input=false", "-no-color", "-var-file=../../config/common.tfvars",
            "-out=" + str(restore_file)], timeout=180)
    verify_tag_only(restore_file)
    capture("iac-tag-restore-apply", tf + ["apply", "-input=false", "-no-color", str(restore_file)], timeout=180)

for stack in ("backend", "frontend", "database", "network"):
    tf = ["terraform", f"-chdir={ROOT / 'stacks' / stack}"]
    capture(f"iac-{stack}-destroy-PLAN-ONLY", tf + ["plan", "-destroy", "-input=false", "-no-color",
            "-var-file=../../config/common.tfvars"], timeout=180)
print("Actualización de etiqueta demostrada y revertida. NO se ejecutó terraform destroy.", flush=True)
