output "address" {
  value = aws_db_instance.this.address
}
output "db_name" {
  value = aws_db_instance.this.db_name
}

output "username" {
  value = var.username
}

output "jdbc_url" {
  value = "jdbc:postgresql://${aws_db_instance.this.address}:5432/${aws_db_instance.this.db_name}?sslmode=require"
}
