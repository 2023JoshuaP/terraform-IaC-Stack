#!/usr/bin/env bash
# Valores para stacks/network/terraform.tfvars — copiar/pegar desde la sección final.
aws iam list-roles --output text \
  --query "Roles[].Arn | [?contains(@, 'LabEks') || ends_with(@, ':role/LabRole')]"

echo "
# ── Pega en stacks/network/terraform.tfvars ──
eks_public_access_cidrs = [\"$(curl -s https://checkip.amazonaws.com)/32\"]
app_access_cidrs        = [\"$(curl -s https://checkip.amazonaws.com)/32\"]

create_iam_roles          = false
existing_cluster_role_arn = \"$(aws iam list-roles --output text --query "Roles[].Arn | [?contains(@, 'LabEksClusterRole')] | [0]")\"
existing_node_role_arn    = \"$(aws iam list-roles --output text --query "Roles[].Arn | [?contains(@, 'LabEksNodeRole')] | [0]")\"
existing_alb_role_arn     = \"$(aws iam list-roles --output text --query "Roles[].Arn | [?ends_with(@, ':role/LabRole')] | [0]")\""
