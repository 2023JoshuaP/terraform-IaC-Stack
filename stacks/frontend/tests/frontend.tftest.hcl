mock_provider "aws" {}

run "frontend_plan" {
  command = plan
  assert {
    condition     = output.repository_name == "cloud-integrador-lab/hamukhub-frontend"
    error_message = "El stack frontend debe crear solamente su repositorio ECR y política de limpieza."
  }
  assert {
    condition     = aws_ecr_repository.this.image_tag_mutability == "IMMUTABLE" && aws_ecr_repository.this.image_scanning_configuration[0].scan_on_push && !aws_ecr_repository.this.force_delete
    error_message = "ECR debe conservar etiquetas inmutables, escaneo y protección de imágenes al borrar."
  }
}
