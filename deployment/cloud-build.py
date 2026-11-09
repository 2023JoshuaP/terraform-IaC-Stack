#!/usr/bin/env python3
"""Construye en EKS y publica en ECR. No necesita Docker local ni copia credenciales."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def tf(stack, name):
    return subprocess.check_output([
        "terraform", f"-chdir={ROOT / 'stacks' / stack}", "output", "-raw", name
    ], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=["backend", "frontend"])
    args = parser.parse_args()
    component = args.component
    cluster = tf("network", "cluster_name")
    region = tf("network", "aws_region")
    kubectl = ["kubectl", "--context", cluster]

    def apply(obj):
        subprocess.run(kubectl + ["apply", "-f", "-"], input=json.dumps(obj), text=True, check=True)

    repo = "ProceedHub" if component == "backend" else "HamukHub"
    url = f"https://github.com/Natzgun/{repo}.git"
    sha = subprocess.check_output(["git", "ls-remote", url, "refs/heads/main"], text=True).split()[0]
    tag = f"{sha[:12]}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}"
    image = f"{tf(component, 'repository_url')}:{tag}"
    job_name = f"build-{component}-{tag[-14:]}"
    namespace = "cloud-build"
    apply({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace}})
    apply({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {
        "name": f"build-{component}", "namespace": namespace
    }, "data": {
        "Dockerfile": (ROOT / "deployment" / f"{component}.Dockerfile").read_text(),
        "nginx.conf": (ROOT / "deployment/nginx.conf").read_text()
    }})
    job = {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": job_name, "namespace": namespace},
        "spec": {"backoffLimit": 0, "activeDeadlineSeconds": 1800, "ttlSecondsAfterFinished": 600,
            "template": {"metadata": {"labels": {"app": job_name}}, "spec": {
                # Excepción de laboratorio: usa IMDS del nodo LabRole, no credenciales del usuario.
                "hostNetwork": True, "dnsPolicy": "ClusterFirstWithHostNet",
                "automountServiceAccountToken": False, "restartPolicy": "Never",
                "initContainers": [
                    {"name": "checkout", "image": "alpine:3.22", "command": ["sh", "-ec", """
apk add --no-cache git ca-certificates
git init /workspace
git -C /workspace remote add origin "$REPOSITORY"
git -C /workspace fetch --depth 1 origin "$REVISION"
git -C /workspace checkout --detach FETCH_HEAD
cp /build-config/Dockerfile /workspace/Dockerfile
cp /build-config/nginx.conf /workspace/nginx.conf
"""], "env": [{"name": "REPOSITORY", "value": url}, {"name": "REVISION", "value": sha}],
                        "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"},
                                         {"name": "config", "mountPath": "/build-config", "readOnly": True}]},
                    {"name": "registry-auth", "image": "public.ecr.aws/aws-cli/aws-cli:2.31.0",
                        "command": ["sh", "-ec", """
PASSWORD="$(aws ecr get-login-password --region "$AWS_REGION")"
AUTH="$(printf 'AWS:%s' "$PASSWORD" | base64 | tr -d '\\n')"
umask 077
printf '{"auths":{"%s":{"auth":"%s"}}}' "$REGISTRY" "$AUTH" > /docker/config.json
"""], "env": [{"name": "AWS_REGION", "value": region},
                                  {"name": "REGISTRY", "value": image.split("/")[0]}],
                        "volumeMounts": [{"name": "docker", "mountPath": "/docker"}]}
                ],
                "containers": [{"name": "build", "image": "moby/buildkit:v0.26.2",
                    "securityContext": {"privileged": True},
                    "command": ["sh", "-ec", """
buildctl-daemonless.sh build --frontend dockerfile.v0 \
  --local context=/workspace --local dockerfile=/workspace \
  --output "type=image,name=$IMAGE,push=true"
"""], "env": [{"name": "IMAGE", "value": image}, {"name": "DOCKER_CONFIG", "value": "/docker"}],
                    "resources": {"requests": {"cpu": "1", "memory": "2Gi", "ephemeral-storage": "4Gi"},
                                  "limits": {"cpu": "2", "memory": "3Gi", "ephemeral-storage": "10Gi"}},
                    "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"},
                                     {"name": "docker", "mountPath": "/docker", "readOnly": True}]}],
                "volumes": [{"name": "workspace", "emptyDir": {}}, {"name": "docker", "emptyDir": {}},
                            {"name": "config", "configMap": {"name": f"build-{component}"}}]
            }}}
    }
    apply(job)
    # Se guarda solo metadata no sensible. Revisar el estado antes de desplegar la imagen.
    destination = ROOT / ".deployment"
    destination.mkdir(exist_ok=True)
    (destination / f"{component}-build.json").write_text(json.dumps({
        "job": job_name, "image": image, "commit": sha, "namespace": namespace
    }, indent=2))
    print(f"Construcción iniciada en AWS: {job_name}\nImagen prevista: {image}")
    print(f"Ver logs: kubectl --context {cluster} -n {namespace} logs -f job/{job_name} -c build")


if __name__ == "__main__":
    main()
