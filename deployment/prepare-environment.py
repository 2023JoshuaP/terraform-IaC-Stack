#!/usr/bin/env python3
"""Descubre y prepara inputs de Academy. No crea recursos ni modifica permisos IAM."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("access_ip", ROOT / "deployment/update-access-ip.py")
access_ip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(access_ip)


def aws(*args):
    result = subprocess.run(["aws", *args, "--output", "json"], text=True, capture_output=True)
    if result.returncode:
        raise ValueError(result.stderr.strip())
    return json.loads(result.stdout)


def trusts(role, service):
    # Los roles vinculados a servicios son internos de AWS, no roles del proyecto.
    if "/aws-service-role/" in role.get("Arn", "") or role.get("Path", "").startswith("/aws-service-role/"):
        return False
    for statement in role.get("AssumeRolePolicyDocument", {}).get("Statement", []):
        principal = statement.get("Principal", {})
        services = principal.get("Service", []) if isinstance(principal, dict) else []
        actions = statement.get("Action", [])
        services = [services] if isinstance(services, str) else services
        actions = [actions] if isinstance(actions, str) else actions
        if (statement.get("Effect") == "Allow" and service in services
                and "sts:AssumeRole" in actions):
            return True
    return False


def permissions(role, kind, partition, account, region, name):
    # Una comprobación previa, no una prueba exhaustiva de todas las API del despliegue.
    repositories = [f"arn:{partition}:ecr:{region}:{account}:repository/{name}/{suffix}"
                    for suffix in ("proceedhub-backend", "hamukhub-frontend")]
    if kind == "cluster":
        checks = [("EKS/red", ["ec2:DescribeInstances", "ec2:DescribeSubnets",
                              "ec2:DescribeSecurityGroups"], ["*"])]
    else:
        checks = [
            ("Arranque/EKS", ["ec2:DescribeInstances", "ec2:DescribeSubnets",
                              "ec2:DescribeNetworkInterfaces", "eks:DescribeCluster"], ["*"]),
            ("Autenticación ECR", ["ecr:GetAuthorizationToken"], ["*"]),
            ("Lectura/publicación ECR", ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer",
                "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload",
                "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage"], repositories),
            ("Controlador ALB", ["elasticloadbalancing:DescribeLoadBalancers",
                "elasticloadbalancing:CreateLoadBalancer", "elasticloadbalancing:CreateTargetGroup",
                "elasticloadbalancing:CreateListener", "elasticloadbalancing:RegisterTargets"], ["*"]),
        ]
    results = []
    for label, actions, resources in checks:
        try:
            result = aws("iam", "simulate-principal-policy", "--policy-source-arn", role["Arn"],
                         "--action-names", *actions, "--resource-arns", *resources)
            evaluations = result.get("EvaluationResults", [])
            unknown = not evaluations
            denied = []
            for evaluation in evaluations:
                if evaluation.get("MissingContextValues"):
                    unknown = True
                elif evaluation.get("EvalDecision") != "allowed":
                    denied.append(evaluation["EvalActionName"] + ":" + evaluation.get("EvalDecision", "unknown"))
                for resource in evaluation.get("ResourceSpecificResults", []):
                    if resource.get("MissingContextValues"):
                        unknown = True
                    elif resource.get("EvalResourceDecision") != "allowed":
                        denied.append(evaluation["EvalActionName"] + ":" + resource.get("EvalResourceDecision", "unknown"))
            state = "denied" if denied else "unknown" if unknown else "allowed"
            results.append({"group": label, "status": state, "details": sorted(set(denied))})
        except ValueError:
            results.append({"group": label, "status": "unknown",
                            "details": ["Simulación IAM no disponible con esta identidad."]})
    return results


def choose(candidates, requested, acknowledge):
    if requested:
        selected = next((r for r in candidates if requested in (r["arn"], r["name"])), None)
        if selected is None:
            raise ValueError(f"El rol {requested} no pertenece a la cuenta o no tiene la confianza esperada.")
        if selected["status"] == "denied":
            raise ValueError(f"El rol {requested} tiene acciones comprobadas no permitidas; no se escribirá.")
        if selected["status"] == "unknown" and not acknowledge:
            raise ValueError("Permisos no verificables: especificar --allow-unverified para aceptar explícitamente esa incertidumbre.")
        return selected["arn"]
    allowed = [r for r in candidates if r["status"] == "allowed"]
    if len(allowed) != 1:
        raise ValueError("No hay un único candidato comprobado. Revisar el informe y elegir con --cluster-role/--node-role.")
    return allowed[0]["arn"]


def assignment(text, key, value):
    pattern = rf"(?m)^([ \t]*{re.escape(key)}[ \t]*=[ \t]*)([^\r\n]*?)([ \t]*(?:#[^\r\n]*)?)$"
    updated, count = re.subn(pattern, lambda m: m[1] + json.dumps(value) + m[3], text)
    if count != 1:
        raise ValueError(f"Se esperaba una asignación de una línea para {key}; no se escribió nada.")
    return updated


def guard_states(account, cluster_role=None, node_role=None):
    for stack in ("network", "backend", "frontend", "database"):
        path = ROOT / "stacks" / stack / "terraform.tfstate"
        if not path.exists():
            continue
        state = json.loads(path.read_text())
        for resource in state.get("resources", []):
            for instance in resource.get("instances", []):
                attrs = instance.get("attributes", {})
                # No imprimir atributos: el estado puede contener contraseñas.
                accounts = re.findall(r"arn:[^:]+:[^:]*:[^:]*:(\d{12}):", json.dumps(attrs))
                registry = attrs.get("registry_id")
                if any(a != account for a in accounts) or (registry and registry != account):
                    raise ValueError(f"El estado de {stack} contiene otra cuenta. Usar otra copia de trabajo con estados propios.")
                expected = cluster_role if resource.get("type") == "aws_eks_cluster" else node_role if resource.get("type") == "aws_eks_node_group" else None
                key = "role_arn" if resource.get("type") == "aws_eks_cluster" else "node_role_arn"
                if expected and attrs.get(key) != expected:
                    raise ValueError("Hay EKS desplegado con otro rol. No se cambiarán sus roles automáticamente.")


def write_private(path, text, backup):
    if path.exists():
        shutil.copy2(path, backup / (path.parent.name + "-" + path.name))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", help="Por defecto: entorno/perfil AWS; si no existe, us-east-1.")
    parser.add_argument("--cluster-role", help="Nombre o ARN; obligatorio si hay varios candidatos.")
    parser.add_argument("--node-role", help="Nombre o ARN; obligatorio si hay varios candidatos.")
    parser.add_argument("--allow-unverified", action="store_true", help="Aceptar simulación desconocida solo para roles elegidos explícitamente.")
    parser.add_argument("--write", action="store_true", help="Guardar inputs tras comprobaciones. Por defecto solo diagnostica.")
    args = parser.parse_args()
    try:
        identity = aws("sts", "get-caller-identity")
        account = identity["Account"]
        partition = identity["Arn"].split(":")[1]
        configured = subprocess.run(["aws", "configure", "get", "region"], capture_output=True, text=True).stdout.strip()
        region = args.region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or configured or "us-east-1"
        guard_states(account)
        with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=15) as response:
            address = access_ip.public_ipv4(response.read(128).decode("ascii"))
        common = ROOT / "config/common.tfvars"
        common_text = (common if common.exists() else common.with_suffix(".tfvars.example")).read_text()
        match = re.search(r'(?m)^name\s*=\s*"([a-z][a-z0-9-]{2,39})"', common_text)
        if not match:
            raise ValueError("No se pudo identificar name en common.tfvars; se requiere una asignación literal de una línea.")
        name = match[1]
        print(f"Cuenta: {account}; región: {region}; IPv4: {address}; proyecto: {name}", flush=True)
        print("Comprobación parcial mediante simulación IAM: no garantiza el despliegue ni todas las restricciones SCP.", flush=True)
        roles = aws("iam", "list-roles")["Roles"]
        report = {"account": account, "region": region, "ip": address, "candidates": {}}
        for kind, service in (("cluster", "eks.amazonaws.com"), ("node", "ec2.amazonaws.com")):
            candidates = []
            for role in roles:
                if not role["Arn"].startswith(f"arn:{partition}:iam::{account}:role/") or not trusts(role, service):
                    continue
                checks = permissions(role, kind, partition, account, region, name)
                status = "denied" if any(c["status"] == "denied" for c in checks) else "unknown" if any(c["status"] == "unknown" for c in checks) else "allowed"
                candidates.append({"name": role["RoleName"], "arn": role["Arn"], "status": status, "checks": checks})
                print(f"{kind}: {role['RoleName']} → {status}", flush=True)
                for check in checks:
                    if check["status"] != "allowed":
                        print(f"  {check['group']}: {check['status']} {'; '.join(check['details'])}", flush=True)
            report["candidates"][kind] = candidates
        if not args.write:
            print("Solo diagnóstico. No se modificaron archivos ni recursos. Usar --write para preparar inputs.")
            return
        cluster = choose(report["candidates"]["cluster"], args.cluster_role, args.allow_unverified)
        node = choose(report["candidates"]["node"], args.node_role, args.allow_unverified)
        guard_states(account, cluster, node)
        zones = aws("ec2", "describe-availability-zones", "--region", region,
                    "--filters", "Name=state,Values=available", "Name=zone-type,Values=availability-zone")
        available = sorted(z["ZoneName"] for z in zones["AvailabilityZones"] if z.get("OptInStatus") != "not-opted-in")
        if len(available) < 2:
            raise ValueError("Se requieren dos zonas disponibles.")
        network = ROOT / "stacks/network/terraform.tfvars"
        text = (network if network.exists() else network.with_suffix(".tfvars.example")).read_text()
        text = access_ip.updated_config(text, address)
        for key, value in {"create_iam_roles": False, "existing_cluster_role_arn": cluster,
                           "existing_node_role_arn": node, "existing_alb_role_arn": None}.items():
            text = assignment(text, key, value)
        # No cambiar región ni zonas de infraestructura que ya tiene estado.
        state = ROOT / "stacks/network/terraform.tfstate"
        active = state.exists() and bool(json.loads(state.read_text()).get("resources"))
        current_region = re.search(r'(?m)^aws_region\s*=\s*"([^"\n]+)"', common_text)
        if active:
            if not current_region or current_region[1] != region:
                raise ValueError("No se cambiará la región con network desplegado.")
        else:
            text = assignment(text, "availability_zones", available[:2])
        common_text = assignment(common_text, "aws_region", region)
        pending = {common: common_text, network: text}
        for stack in ("backend", "frontend", "database"):
            target = ROOT / "stacks" / stack / "terraform.tfvars"
            if not target.exists():
                pending[target] = target.with_suffix(".tfvars.example").read_text()
        backup = ROOT / ".deployment" / ("environment-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
        backup.mkdir(parents=True, mode=0o700)
        for target, content in pending.items():
            write_private(target, content, backup)
        write_private(backup / "discovery.json", json.dumps(report, indent=2), backup)
        print(f"Inputs preparados y respaldo privado en {backup}.")
        print("No se crearon recursos ni se ejecutó Terraform. Revisar plan antes de aplicar.")
    except (ValueError, OSError, UnicodeError, KeyError) as error:
        raise SystemExit(f"Preparación detenida: {error}") from None


if __name__ == "__main__":
    main()
