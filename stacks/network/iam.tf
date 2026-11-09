data "aws_partition" "current" {}

locals {
  cluster_role_arn = var.create_iam_roles ? aws_iam_role.cluster[0].arn : var.existing_cluster_role_arn
  node_role_arn    = var.create_iam_roles ? aws_iam_role.nodes[0].arn : var.existing_node_role_arn
  alb_role_arn     = var.create_iam_roles ? aws_iam_role.alb[0].arn : var.existing_alb_role_arn
  oidc_host        = replace(aws_eks_cluster.this.identity[0].oidc[0].issuer, "https://", "")
  policy_prefix    = "arn:${data.aws_partition.current.partition}:iam::aws:policy"
}

resource "aws_iam_role" "cluster" {
  count = var.create_iam_roles ? 1 : 0
  name  = "${var.name}-eks"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "eks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "cluster" {
  count      = var.create_iam_roles ? 1 : 0
  role       = aws_iam_role.cluster[0].name
  policy_arn = "${local.policy_prefix}/AmazonEKSClusterPolicy"
}

resource "aws_iam_role" "nodes" {
  count = var.create_iam_roles ? 1 : 0
  name  = "${var.name}-nodes"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "nodes" {
  for_each = var.create_iam_roles ? toset(concat([
    "AmazonEKSWorkerNodePolicy", "AmazonEC2ContainerRegistryReadOnly", "AmazonEKS_CNI_Policy"
  ], var.enable_container_insights ? ["CloudWatchAgentServerPolicy"] : [])) : toset([])
  role       = aws_iam_role.nodes[0].name
  policy_arn = "${local.policy_prefix}/${each.value}"
}

resource "aws_iam_openid_connect_provider" "this" {
  count          = var.create_iam_roles ? 1 : 0
  url            = aws_eks_cluster.this.identity[0].oidc[0].issuer
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_role" "alb" {
  count = var.create_iam_roles ? 1 : 0
  name  = "${var.name}-alb"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = aws_iam_openid_connect_provider.this[0].arn }
      Condition = {
        StringEquals = {
          "${local.oidc_host}:aud" = "sts.amazonaws.com"
          "${local.oidc_host}:sub" = "system:serviceaccount:kube-system:aws-load-balancer-controller"
        }
      }
    }]
  })
}

resource "aws_iam_policy" "alb" {
  count       = var.create_iam_roles ? 1 : 0
  name        = "${var.name}-alb"
  description = "AWS Load Balancer Controller v2.14.1 upstream policy"
  policy      = file("${path.module}/policies/alb-controller.json")
}

resource "aws_iam_role_policy_attachment" "alb" {
  count      = var.create_iam_roles ? 1 : 0
  role       = aws_iam_role.alb[0].name
  policy_arn = aws_iam_policy.alb[0].arn
}
