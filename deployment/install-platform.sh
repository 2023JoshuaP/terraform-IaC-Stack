#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELM="${HELM:-helm}"
cluster="$(terraform -chdir="$ROOT/stacks/network" output -raw cluster_name)"
region="$(terraform -chdir="$ROOT/stacks/network" output -raw aws_region)"
vpc="$(terraform -chdir="$ROOT/stacks/network" output -raw vpc_id)"

"$HELM" repo add eks https://aws.github.io/eks-charts --force-update
"$HELM" repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/ --force-update
"$HELM" repo update

# Modo exclusivo del Learner Lab: el nodo usa LabRole y el controlador obtiene
# sus credenciales mediante IMDS. No se modifica IAM ni se simula un rol IRSA.
"$HELM" upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  --version 1.14.1 --namespace kube-system --kube-context "$cluster" \
  --set-string "clusterName=$cluster" --set-string "region=$region" --set-string "vpcId=$vpc" \
  --set hostNetwork=true --set dnsPolicy=ClusterFirstWithHostNet --set replicaCount=1 \
  --set serviceAccount.create=true --set enableWaf=false --set enableWafv2=false --set enableShield=false \
  --wait --timeout 10m

"$HELM" upgrade --install metrics-server metrics-server/metrics-server \
  --version 3.13.0 --namespace kube-system --kube-context "$cluster" --wait --timeout 10m
