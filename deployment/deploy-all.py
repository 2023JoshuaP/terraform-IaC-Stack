#!/usr/bin/env python3
"""Orquesta el despliegue Academy desde este repositorio; no instala herramientas."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def run(command, capture=False, timeout=None):
    result = subprocess.run(command, cwd=ROOT, text=True, check=True,
                            stdout=subprocess.PIPE if capture else None, timeout=timeout)
    return result.stdout.strip() if capture else None


def aws_json(*args):
    return json.loads(run(["aws", *args, "--output", "json"], capture=True))


def tf_outputs(stack):
    data = json.loads(run(["terraform", f"-chdir=stacks/{stack}", "output", "-json"], capture=True))
    return {key: value["value"] for key, value in data.items()}


def safe_plan(plan):
    for resource in plan.get("resource_changes", []):
        if "delete" in resource.get("change", {}).get("actions", []):
            raise ValueError(f"Plan con eliminación/reemplazo: {resource['address']}. Revisar manualmente.")


def nodes_ready(items, desired):
    return sum(
        not item.get("spec", {}).get("unschedulable", False)
        and any(c.get("type") == "Ready" and c.get("status") == "True"
                for c in item.get("status", {}).get("conditions", []))
        for item in items) >= desired


def wait_until(description, check, timeout, interval=15):
    print(f"Esperando {description} (máximo {timeout}s)...", flush=True)
    end = time.monotonic() + timeout
    while True:
        if check():
            return
        remaining = end - time.monotonic()
        if remaining <= 0:
            raise ValueError(f"Tiempo agotado esperando {description}. No se eliminaron recursos.")
        time.sleep(min(interval, remaining))


def image_matches(record, repository):
    image = record.get("image", "")
    return image.startswith(repository + ":") and bool(image[len(repository) + 1:])


class Deployment:
    def __init__(self, args, directory):
        self.args = args
        self.directory = directory
        self.cluster = None

    def kubectl(self, *args, capture=False, timeout=60):
        return run(["kubectl", "--context", self.cluster, *args], capture=capture, timeout=timeout)

    def terraform(self, stack):
        print(f"\n=== Terraform: {stack} ===", flush=True)
        base = ["terraform", f"-chdir=stacks/{stack}"]
        run(base + ["init", "-input=false"])
        run(base + ["validate"])
        plan = self.directory / f"{stack}.tfplan"
        run(base + ["plan", "-input=false", "-var-file=../../config/common.tfvars", f"-out={plan}"])
        # El JSON puede contener secretos: mantenerlo en memoria, no imprimirlo.
        data = json.loads(run(base + ["show", "-json", str(plan)], capture=True))
        safe_plan(data)
        if not self.args.yes and input(f"¿Aplicar el plan de {stack}? Escribir yes: ").strip() != "yes":
            raise ValueError("Cancelado por el operador. Se conservan los recursos ya creados.")
        # apply es bloqueante: espera a EKS/RDS y conserva sus límites nativos.
        run(base + ["apply", "-input=false", str(plan)])

    def build(self, component):
        print(f"\n=== Build AWS: {component} ===", flush=True)
        repository = tf_outputs(component)["repository_url"]
        metadata = ROOT / ".deployment" / f"{component}-build.json"
        record = json.loads(metadata.read_text()) if metadata.exists() else None
        if record and not self.args.rebuild:
            if not image_matches(record, repository):
                raise ValueError(f"Metadata {component} de otro repositorio/cuenta. Revisar o usar --rebuild.")
            repository_name = tf_outputs(component)["repository_name"]
            images = aws_json("ecr", "list-images", "--region", self.args.region,
                              "--repository-name", repository_name).get("imageIds", [])
            tag = record["image"].rsplit(":", 1)[1]
            if any(image.get("imageTag") == tag for image in images):
                print(f"Se reutiliza la imagen publicada: {record['image']}", flush=True)
                return
            job = json.loads(self.kubectl("-n", record["namespace"], "get", "job", record["job"],
                                         "--ignore-not-found", "-o", "json", capture=True) or "{}")
            if not job:
                raise ValueError(f"Sin imagen ni Job {component}. Revisar y usar --rebuild para crear otro intento.")
            if any(c.get("type") in ("Failed", "FailureTarget") and c.get("status") == "True"
                   for c in job.get("status", {}).get("conditions", [])):
                raise ValueError(f"El Job {component} falló. Revisar logs; usar --rebuild tras corregir la causa.")
            print(f"Retomando espera del Job existente: {record['job']}", flush=True)
        else:
            if record:
                shutil.copy2(metadata, self.directory / metadata.name)
            run([sys.executable, "deployment/cloud-build.py", component])
        run([sys.executable, "deployment/wait-build.py", component], timeout=2100)
        record = json.loads(metadata.read_text())
        self.kubectl("-n", record["namespace"], "logs", f"job/{record['job']}", "-c", "build")

    def execute(self):
        identity = aws_json("sts", "get-caller-identity")
        print(f"Cuenta AWS: {identity['Account']} | Región: {self.args.region}", flush=True)
        if not self.args.yes and input("Se crearán recursos con costo. Escribir yes para continuar: ").strip() != "yes":
            raise ValueError("Cancelado antes de preparar el despliegue.")
        prepare = [sys.executable, "deployment/prepare-environment.py", "--region", self.args.region, "--write"]
        for option, value in (("--cluster-role", self.args.cluster_role), ("--node-role", self.args.node_role)):
            if value:
                prepare += [option, value]
        run(prepare)
        for stack in ("backend", "frontend", "network"):
            self.terraform(stack)
        network = tf_outputs("network")
        self.cluster = network["cluster_name"]
        run(["aws", "eks", "update-kubeconfig", "--region", self.args.region,
             "--name", self.cluster, "--alias", self.cluster])
        group = aws_json("eks", "describe-nodegroup", "--region", self.args.region,
                         "--cluster-name", self.cluster, "--nodegroup-name", self.cluster + "-workers")
        desired = group["nodegroup"]["scalingConfig"]["desiredSize"]

        def ready():
            try:
                data = json.loads(self.kubectl("get", "nodes", "-o", "json", capture=True))
                return nodes_ready(data.get("items", []), desired)
            except (subprocess.SubprocessError, json.JSONDecodeError):
                return False

        wait_until(f"{desired} nodos Ready", ready, self.args.ready_timeout)
        run([sys.executable, "deployment/prepare-database.py"])
        self.terraform("database")
        run(["bash", "deployment/install-platform.sh"])
        for component in ("aws-load-balancer-controller", "metrics-server"):
            self.kubectl("-n", "kube-system", "rollout", "status", f"deployment/{component}", "--timeout=600s", timeout=660)
        for component in ("backend", "frontend"):
            self.build(component)
        run([sys.executable, "deployment/deploy-apps.py", "--origin", "http://localhost"])
        for component in ("backend", "frontend"):
            self.kubectl("-n", "cloud-integrador", "rollout", "status", f"deployment/{component}", "--timeout=600s", timeout=660)
        self.kubectl("-n", "cloud-integrador", "wait",
                     "--for=jsonpath={.status.loadBalancer.ingress[0].hostname}",
                     "ingress/cloud-integrador", "--timeout=600s", timeout=660)
        host = self.kubectl("-n", "cloud-integrador", "get", "ingress", "cloud-integrador",
                            "-o", "jsonpath={.status.loadBalancer.ingress[0].hostname}", capture=True)
        if not host or not host.endswith(".elb.amazonaws.com"):
            raise ValueError("Hostname ALB ausente o inesperado; revisar Ingress.")
        origin = "http://" + host
        run([sys.executable, "deployment/deploy-apps.py", "--origin", origin])
        self.kubectl("-n", "cloud-integrador", "rollout", "status", "deployment/backend", "--timeout=600s", timeout=660)

        def web_ready():
            try:
                for path in ("/", "/api/scholarships/get_all"):
                    with urllib.request.urlopen(origin + path, timeout=15) as response:
                        if response.status != 200:
                            return False
                return True
            except (OSError, urllib.error.URLError):
                return False

        # La dirección puede existir antes de que DNS y targets estén disponibles.
        # Solo reintentar GET: no repetir registros/login con efectos secundarios.
        wait_until("DNS y respuestas HTTP del ALB", web_ready, self.args.ready_timeout)
        run([sys.executable, "deployment/smoke-test.py", origin], timeout=300)
        self.kubectl("-n", "cloud-integrador", "get", "pods,hpa,ingress")
        self.kubectl("-n", "cloud-integrador", "top", "pods")
        (self.directory / "result.json").write_text(json.dumps({
            "account": identity["Account"], "region": self.args.region, "origin": origin,
            "smoke_test": "passed"}, indent=2))
        print(f"\nDespliegue verificado: {origin}\nLos recursos siguen activos y generan costos.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--cluster-role", help="Nombre o ARN obtenido del diagnóstico.")
    parser.add_argument("--node-role", help="Nombre o ARN obtenido del diagnóstico.")
    parser.add_argument("--yes", action="store_true", help="Autorizar creación y aplicar planes sin preguntas; nunca permite eliminaciones.")
    parser.add_argument("--rebuild", action="store_true", help="Crear nuevos Jobs en lugar de reutilizar imágenes/Jobs anteriores.")
    parser.add_argument("--ready-timeout", type=int, default=900, help="Espera de nodos y HTTP, en segundos (predeterminado: 900). No limita Terraform.")
    args = parser.parse_args()
    if args.ready_timeout <= 0:
        parser.error("--ready-timeout debe ser positivo")
    os.umask(0o077)
    lock = None
    try:
        for program in ("aws", "terraform", "kubectl", "git", "bash"):
            if not shutil.which(program):
                raise ValueError(f"Falta instalar {program}.")
        helm = os.environ.get("HELM", "helm")
        if not shutil.which(helm):
            raise ValueError("Falta Helm. Instalarlo o definir HELM=/ruta/helm.")
        private = ROOT / ".deployment"
        private.mkdir(mode=0o700, exist_ok=True)
        lock = (private / "deploy-all.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Ya hay otro deploy-all ejecutándose en esta copia.") from None
        directory = private / ("deploy-all-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
        directory.mkdir(mode=0o700)
        print(f"Planes privados y resultado: {directory}", flush=True)
        Deployment(args, directory).execute()
    except (ValueError, OSError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        print(f"\nDespliegue detenido: {error}\nNo hay rollback automático: revisar recursos y costos. "
              "Conservar estados y secretos; corregir el error antes de repetir.", file=sys.stderr)
        return 1
    finally:
        if lock is not None:
            lock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
