mock_provider "aws" {}

variables {
  vpc_id                    = "vpc-0123456789abcdef0"
  subnet_ids                = ["subnet-0123456789abcdef0", "subnet-0123456789abcdef1"]
  source_security_group_id  = "sg-0123456789abcdef0"
  password                  = "OnlyForMockTests-12345!"
  final_snapshot_identifier = "cloud-integrador-test-final"
}

run "database_plan" {
  command = plan
  assert {
    condition     = !aws_db_instance.this.publicly_accessible && aws_db_instance.this.storage_encrypted
    error_message = "RDS debe ser privado y cifrado."
  }
  assert {
    condition     = aws_db_instance.this.deletion_protection && !aws_db_instance.this.skip_final_snapshot && aws_db_instance.this.backup_retention_period >= 1
    error_message = "RDS requiere protección de borrado, snapshot final y backups."
  }
  assert {
    condition     = aws_vpc_security_group_ingress_rule.postgresql.referenced_security_group_id == var.source_security_group_id && aws_vpc_security_group_ingress_rule.postgresql.from_port == 5432 && aws_vpc_security_group_ingress_rule.postgresql.to_port == 5432
    error_message = "Permitir solo PostgreSQL desde el security group autorizado."
  }
}

run "reject_invalid_vpc" {
  command = plan
  variables {
    vpc_id = "REEMPLAZAR"
  }
  expect_failures = [var.vpc_id]
}

run "require_final_snapshot_name" {
  command = plan
  variables {
    final_snapshot_identifier = null
  }
  expect_failures = [aws_db_instance.this]
}
