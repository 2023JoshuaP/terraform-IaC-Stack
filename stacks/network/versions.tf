terraform {
  required_version = ">= 1.16.0, < 2.0.0"
  # Estado propio de network en esta carpeta. No compartirlo con los otros stacks.
  backend "local" {}
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
