resource "aws_security_group" "alb" {
  name_prefix = "${var.name}-alb-"
  description = "Public application entry point; restricted to approved CIDRs"
  vpc_id      = aws_vpc.this.id
  tags        = { Name = "${var.name}-alb" }
}

# HTTP solo para demostración sin datos reales. Para producción configurar ACM/HTTPS.
resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  for_each          = toset(var.app_access_cidrs)
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_egress_rule" "alb_to_pods" {
  for_each                     = toset(["8080", "8086"])
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = tonumber(each.value)
  to_port                      = tonumber(each.value)
}

# Managed node groups adjuntan el security group primario del clúster a los nodos.
resource "aws_vpc_security_group_ingress_rule" "alb_to_nodes" {
  for_each                     = toset(["8080", "8086"])
  security_group_id            = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = tonumber(each.value)
  to_port                      = tonumber(each.value)
}
