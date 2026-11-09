#!/usr/bin/env python3
"""Despliega imágenes ya construidas en EKS, RDS y un Ingress ALB restringido."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "cloud-integrador"


def outputs(stack):
    raw = subprocess.check_output(["terraform", f"-chdir={ROOT / 'stacks' / stack}", "output", "-json"], text=True)
    return {key: data["value"] for key, data in json.loads(raw).items()}


def objects(network, database, images, credentials, origin):
    def metadata(name, **extra):
        return {"name": name, "namespace": NAMESPACE, **extra}

    config = {
        "PORT": "8086", "DB_URL": database["jdbc_url"], "DB_USERNAME": database["username"],
        "JWT_EXPIRATION": "3600000", "CORS_ALLOWED_ORIGINS": origin,
        "SPRING_JPA_SHOW_SQL": "false", "SPRING_JPA_HIBERNATE_DDL_AUTO": "update",
        "JAVA_TOOL_OPTIONS": "-XX:MaxRAMPercentage=70.0 -Djava.io.tmpdir=/tmp",
        "SERVER_SHUTDOWN": "graceful",
    }
    result = [
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NAMESPACE}},
        {"apiVersion": "v1", "kind": "Secret", "metadata": metadata("backend-secrets"),
         "type": "Opaque", "data": {}},
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": metadata("backend-config"), "data": config},
    ]
    # Se usa data en lugar de stringData para server-side apply estable.
    import base64
    result[1]["data"] = {key: base64.b64encode(value.encode()).decode() for key, value in credentials.items()}
    for component in ("backend", "frontend"):
        backend = component == "backend"
        port = 8086 if backend else 8080
        path = "/api/scholarships/get_all" if backend else "/"
        container = {
            "name": component, "image": images[component], "imagePullPolicy": "IfNotPresent",
            "ports": [{"name": "http", "containerPort": port}],
            "resources": {"requests": {"cpu": "250m" if backend else "100m", "memory": "512Mi" if backend else "64Mi"},
                          "limits": {"cpu": "1" if backend else "500m", "memory": "1Gi" if backend else "128Mi"}},
            "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]}},
            "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
            "startupProbe": {"tcpSocket": {"port": "http"}, "periodSeconds": 5, "failureThreshold": 60},
            "readinessProbe": {"httpGet": {"path": path, "port": "http"}, "periodSeconds": 10, "timeoutSeconds": 5},
            "livenessProbe": {"tcpSocket": {"port": "http"}, "periodSeconds": 20},
        }
        if backend:
            container["envFrom"] = [{"configMapRef": {"name": "backend-config"}}, {"secretRef": {"name": "backend-secrets"}}]
        pod_metadata = {"labels": {"app": component}}
        if backend:
            pod_metadata["annotations"] = {"checksum/config": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()}
        result.extend([
            {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": metadata(component), "spec": {
                "revisionHistoryLimit": 2, "selector": {"matchLabels": {"app": component}},
                "strategy": {"type": "RollingUpdate", "rollingUpdate": {"maxSurge": 1, "maxUnavailable": 0}},
                "template": {"metadata": pod_metadata, "spec": {
                    "automountServiceAccountToken": False,
                    "securityContext": {"runAsNonRoot": True, "runAsUser": 10001 if backend else 101,
                                        "runAsGroup": 10001 if backend else 101, "fsGroup": 10001 if backend else 101,
                                        "seccompProfile": {"type": "RuntimeDefault"}},
                    "containers": [container], "volumes": [{"name": "tmp", "emptyDir": {"sizeLimit": "128Mi"}}],
                }}}},
            {"apiVersion": "v1", "kind": "Service", "metadata": metadata(component, annotations={
                "alb.ingress.kubernetes.io/healthcheck-path": path,
                "alb.ingress.kubernetes.io/success-codes": "200",
            }), "spec": {"type": "ClusterIP", "selector": {"app": component},
                        "ports": [{"name": "http", "port": 8086 if backend else 80, "targetPort": "http"}]}},
            {"apiVersion": "autoscaling/v2", "kind": "HorizontalPodAutoscaler", "metadata": metadata(component),
             "spec": {"scaleTargetRef": {"apiVersion": "apps/v1", "kind": "Deployment", "name": component},
                      "minReplicas": 1, "maxReplicas": 3,
                      "metrics": [{"type": "Resource", "resource": {"name": "cpu", "target": {
                          "type": "Utilization", "averageUtilization": 60 if backend else 70}}}],
                      "behavior": {"scaleDown": {"stabilizationWindowSeconds": 120}}}},
        ])
    result.append({"apiVersion": "networking.k8s.io/v1", "kind": "Ingress", "metadata": metadata("cloud-integrador", annotations={
        "alb.ingress.kubernetes.io/scheme": "internet-facing", "alb.ingress.kubernetes.io/target-type": "ip",
        "alb.ingress.kubernetes.io/listen-ports": '[{"HTTP":80}]',
        "alb.ingress.kubernetes.io/subnets": ",".join(network["public_subnet_ids"]),
        "alb.ingress.kubernetes.io/security-groups": network["alb_security_group_id"],
        "alb.ingress.kubernetes.io/manage-backend-security-group-rules": "false",
    }), "spec": {"ingressClassName": "alb", "rules": [{"http": {"paths": [
        {"path": "/api", "pathType": "Prefix", "backend": {"service": {"name": "backend", "port": {"number": 8086}}}},
        {"path": "/", "pathType": "Prefix", "backend": {"service": {"name": "frontend", "port": {"number": 80}}}},
    ]}}]}})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True, help="http://localhost solo para bootstrap; luego el origen HTTP del ALB.")
    args = parser.parse_args()
    origin = urlsplit(args.origin)
    if origin.scheme != "http" or not origin.hostname or origin.path or origin.query or origin.fragment or origin.username:
        raise SystemExit("Este piloto usa origen HTTP sin ruta, usuario ni barra final. Configurar HTTPS antes de datos reales.")
    network, database = outputs("network"), outputs("database")
    cluster = network["cluster_name"]
    images = {}
    for component in ("backend", "frontend"):
        record = json.loads((ROOT / ".deployment" / f"{component}-build.json").read_text())
        repository_url, tag = record["image"].rsplit(":", 1)
        repository_name = outputs(component)["repository_name"]
        # ECR es la fuente de verdad: los Jobs terminados se eliminan por TTL.
        digest = subprocess.check_output([
            "aws", "ecr", "describe-images", "--region", network["aws_region"],
            "--repository-name", repository_name, "--image-ids", f"imageTag={tag}",
            "--query", "imageDetails[0].imageDigest", "--output", "text"
        ], text=True).strip()
        if not digest.startswith("sha256:"):
            raise SystemExit(f"La imagen {component} todavía no se publicó correctamente en ECR.")
        images[component] = f"{repository_url}@{digest}"
    credentials = json.loads((ROOT / ".deployment/secrets.json").read_text())
    for obj in objects(network, database, images, credentials, args.origin):
        subprocess.run(["kubectl", "--context", cluster, "apply", "--server-side", "--field-manager=cloud-integrador", "-f", "-"],
                       input=json.dumps(obj), text=True, check=True)
    print("Aplicación enviada a EKS. Revisar rollout, Ingress y disponibilidad real antes de darla por lista.")


if __name__ == "__main__":
    main()
