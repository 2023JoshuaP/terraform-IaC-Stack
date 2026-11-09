resource "aws_cloudwatch_log_group" "eks" {
  name              = "/aws/eks/${var.name}/cluster"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "insights" {
  for_each          = var.enable_container_insights ? toset(["application", "dataplane", "host", "performance"]) : toset([])
  name              = "/aws/containerinsights/${var.name}/${each.value}"
  retention_in_days = var.log_retention_days
}

resource "aws_eks_addon" "observability" {
  count                       = var.enable_container_insights ? 1 : 0
  cluster_name                = aws_eks_cluster.this.name
  addon_name                  = "amazon-cloudwatch-observability"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "PRESERVE"
  depends_on                  = [aws_eks_node_group.this, aws_cloudwatch_log_group.insights]
}
