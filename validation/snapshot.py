#!/usr/bin/env python3
"""Captura estado, métricas, logs y configuración no sensible para la demostración."""
import argparse
from common import capture, directory, KUBECTL, NAMESPACE, ROOT

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--prefix", default="baseline")
args = parser.parse_args()
commands = {
    "nodes": KUBECTL + ["get", "nodes", "-o", "wide"],
    "workloads": KUBECTL + ["-n", NAMESPACE, "get", "pods,deployments,services,hpa,ingress", "-o", "wide"],
    "cpu-memory": KUBECTL + ["-n", NAMESPACE, "top", "pods", "--containers"],
    "hpa-description": KUBECTL + ["-n", NAMESPACE, "describe", "hpa"],
    "events": KUBECTL + ["-n", NAMESPACE, "get", "events", "--sort-by=.lastTimestamp"],
    "backend-logs": KUBECTL + ["-n", NAMESPACE, "logs", "deployment/backend", "--tail=60", "--timestamps=true"],
    "frontend-logs": KUBECTL + ["-n", NAMESPACE, "logs", "deployment/frontend", "--tail=30", "--timestamps=true"],
    "probes-resources": KUBECTL + ["-n", NAMESPACE, "get", "deployments", "-o", "json"],
    "rds": ["aws", "rds", "describe-db-instances", "--region", "us-east-1", "--db-instance-identifier", "cloud-integrador-lab-postgres",
            "--query", "DBInstances[].{Name:DBInstanceIdentifier,Status:DBInstanceStatus,Engine:Engine,Version:EngineVersion,Class:DBInstanceClass,PubliclyAccessible:PubliclyAccessible,Encrypted:StorageEncrypted,BackupDays:BackupRetentionPeriod,DeletionProtection:DeletionProtection}", "--output", "json"],
    "cloudwatch": ["aws", "logs", "describe-log-groups", "--region", "us-east-1", "--log-group-name-prefix", "/aws/",
                   "--query", "logGroups[?contains(logGroupName, 'cloud-integrador')].{Name:logGroupName,RetentionDays:retentionInDays,StoredBytes:storedBytes}", "--output", "json"],
}
for name, command in commands.items():
    capture(f"{args.prefix}-{name}", command, check=False)
capture(f"{args.prefix}-functional", ["python3", str(ROOT / "deployment/smoke-test.py"),
    "http://k8s-cloudint-cloudint-a2d2afe605-1137396884.us-east-1.elb.amazonaws.com"])
print(f"Evidencias guardadas en {directory()}")
