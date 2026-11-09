resource "aws_security_group" "this" {
  name_prefix = "${var.name}-postgres-"
  description = "PostgreSQL access only from EKS node security group"
  vpc_id      = var.vpc_id
}

# Sin Security Groups for Pods, todos los pods de estos nodos comparten este origen.
# No implica aislamiento exclusivo del backend a nivel de pod.
resource "aws_vpc_security_group_ingress_rule" "postgresql" {
  security_group_id            = aws_security_group.this.id
  referenced_security_group_id = var.source_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
