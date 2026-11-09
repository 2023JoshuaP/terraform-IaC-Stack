resource "aws_db_subnet_group" "this" {
  name       = "${var.name}-database"
  subnet_ids = var.subnet_ids
}

resource "aws_cloudwatch_log_group" "postgresql" {
  name              = "/aws/rds/instance/${var.name}-postgres/postgresql"
  retention_in_days = var.log_retention_days
}

resource "aws_db_instance" "this" {
  identifier                      = "${var.name}-postgres"
  engine                          = "postgres"
  engine_version                  = var.engine_version
  instance_class                  = var.instance_class
  allocated_storage               = var.allocated_storage
  storage_type                    = "gp3"
  storage_encrypted               = true
  db_name                         = var.db_name
  username                        = var.username
  password                        = var.password
  port                            = 5432
  db_subnet_group_name            = aws_db_subnet_group.this.name
  vpc_security_group_ids          = [aws_security_group.this.id]
  publicly_accessible             = false
  multi_az                        = false
  backup_retention_period         = 1
  auto_minor_version_upgrade      = true
  allow_major_version_upgrade     = false
  apply_immediately               = false
  deletion_protection             = var.deletion_protection
  skip_final_snapshot             = var.skip_final_snapshot
  final_snapshot_identifier       = var.final_snapshot_identifier
  copy_tags_to_snapshot           = true
  enabled_cloudwatch_logs_exports = ["postgresql"]

  lifecycle {
    precondition {
      condition     = var.skip_final_snapshot || try(length(var.final_snapshot_identifier) > 0, false)
      error_message = "Proporcionar un identificador único de snapshot final o aprobar explícitamente omitirlo."
    }
  }
  depends_on = [aws_cloudwatch_log_group.postgresql]
}
