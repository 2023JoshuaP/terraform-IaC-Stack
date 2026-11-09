mock_provider "aws" {}

run "backend_plan" {
  command = plan
  assert {
    condition     = output.repository_name == "cloud-integrador-lab/proceedhub-backend"
    error_message = "El stack backend debe crear solamente su repositorio ECR y política de limpieza."
  }
  assert {
    condition     = aws_ecr_repository.this.image_tag_mutability == "IMMUTABLE" && aws_ecr_repository.this.image_scanning_configuration[0].scan_on_push && !aws_ecr_repository.this.force_delete
    error_message = "ECR debe conservar etiquetas inmutables, escaneo y protección de imágenes al borrar."
  }
}
