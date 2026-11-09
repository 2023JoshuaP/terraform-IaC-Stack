mock_provider "aws" {
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
}

variables {
  eks_public_access_cidrs = ["203.0.113.10/32"]
  app_access_cidrs        = ["203.0.113.10/32"]
  create_iam_roles        = true
  existing_cluster_role_arn = null
  existing_node_role_arn    = null
  existing_alb_role_arn     = null
}

run "network_plan" {
  command = plan
  assert {
    condition     = length(aws_subnet.public) == 2 && length(aws_subnet.private) == 2
    error_message = "Deben existir dos subredes públicas y dos privadas."
  }
  assert {
    condition     = aws_eks_cluster.this.vpc_config[0].endpoint_private_access && aws_eks_cluster.this.vpc_config[0].public_access_cidrs == toset(["203.0.113.10/32"])
    error_message = "EKS requiere acceso privado y acceso público restringido."
  }
}

run "existing_lab_roles" {
  command = plan
  variables {
    create_iam_roles          = false
    existing_cluster_role_arn = "arn:aws:iam::123456789012:role/TestClusterRole"
    existing_node_role_arn    = "arn:aws:iam::123456789012:role/TestNodeRole"
    existing_alb_role_arn     = "arn:aws:iam::123456789012:role/TestAlbRole"
  }
  assert {
    condition     = length(aws_iam_role.cluster) == 0 && length(aws_iam_role.nodes) == 0 && length(aws_iam_role.alb) == 0 && output.alb_role_arn == "arn:aws:iam::123456789012:role/TestAlbRole"
    error_message = "Al reutilizar roles no deben crearse roles nuevos."
  }
}

run "reject_open_api" {
  command = plan
  variables {
    eks_public_access_cidrs = ["0.0.0.0/0"]
  }
  expect_failures = [var.eks_public_access_cidrs]
}

run "lab_without_irsa" {
  command = plan
  variables {
    create_iam_roles          = false
    existing_cluster_role_arn = "arn:aws:iam::123456789012:role/TestClusterRole"
    existing_node_role_arn    = "arn:aws:iam::123456789012:role/LabRole"
    existing_alb_role_arn     = null
  }
  assert {
    condition     = length(aws_iam_role.alb) == 0 && output.alb_role_arn == null
    error_message = "El modo Lab debe permitir roles existentes sin crear un rol IRSA."
  }
}

run "reject_invalid_scaling" {
  command = plan
  variables {
    node_scaling = { min = 2, desired = 1, max = 3 }
  }
  expect_failures = [var.node_scaling]
}
