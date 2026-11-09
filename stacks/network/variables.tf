variable "name" {
  type    = string
  default = "cloud-integrador-lab"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,39}$", var.name))
    error_message = "Usar 3–40 caracteres en minúsculas, números o guiones, comenzando por letra."
  }
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
  validation {
    condition     = can(cidrnetmask(var.vpc_cidr)) && can(cidrsubnet(var.vpc_cidr, 8, 11))
    error_message = "Indicar un CIDR IPv4 con capacidad para las subredes del proyecto."
  }
}

variable "availability_zones" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b"]
  validation {
    condition     = length(var.availability_zones) == 2 && length(distinct(var.availability_zones)) == 2
    error_message = "Se requieren dos zonas diferentes de la región configurada."
  }
}

variable "eks_public_access_cidrs" {
  description = "IP públicas de administradores/runners, en formato CIDR."
  type        = list(string)
  validation {
    condition = length(var.eks_public_access_cidrs) > 0 && alltrue([
      for cidr in var.eks_public_access_cidrs : can(cidrnetmask(cidr)) && !endswith(cidr, "/0")
    ])
    error_message = "Proporcionar CIDR IPv4 restringidos, nunca /0."
  }
}

variable "app_access_cidrs" {
  description = "Visitantes autorizados al futuro ALB."
  type        = list(string)
  validation {
    condition = length(var.app_access_cidrs) > 0 && alltrue([
      for cidr in var.app_access_cidrs : can(cidrnetmask(cidr)) && !endswith(cidr, "/0")
    ])
    error_message = "Proporcionar CIDR IPv4 restringidos, nunca /0."
  }
}

variable "kubernetes_version" {
  description = "Confirmar soporte estándar y disponibilidad en AWS antes de aplicar."
  type        = string
  default     = "1.35"
}

variable "node_instance_types" {
  type    = list(string)
  default = ["t3.medium"]
  validation {
    condition     = length(var.node_instance_types) > 0
    error_message = "Indicar al menos un tipo de instancia x86_64 compatible con EKS."
  }
}

variable "node_scaling" {
  type    = object({ min = number, desired = number, max = number })
  default = { min = 1, desired = 2, max = 3 }
  validation {
    condition = var.node_scaling.min >= 1 && var.node_scaling.min <= var.node_scaling.desired && var.node_scaling.desired <= var.node_scaling.max && alltrue([
      for value in values(var.node_scaling) : value == floor(value)
    ])
    error_message = "Usar enteros con 1 <= min <= desired <= max."
  }
}

variable "create_iam_roles" {
  description = "false para usar roles ya autorizados por AWS Academy."
  type        = bool
  default     = true
}

variable "existing_cluster_role_arn" {
  type    = string
  default = null
}

variable "existing_node_role_arn" {
  type    = string
  default = null
}

variable "existing_alb_role_arn" {
  description = "Rol IRSA opcional. En el Lab se puede omitir si el controlador usa credenciales de un nodo autorizado mediante hostNetwork."
  type        = string
  default     = null
}

variable "cluster_admin_principal_arns" {
  description = "Usuarios/roles IAM adicionales, no sesiones STS. El creador ya tiene acceso."
  type        = set(string)
  default     = []
}

variable "enable_container_insights" {
  type    = bool
  default = false
}

variable "log_retention_days" {
  type    = number
  default = 7
  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90], var.log_retention_days)
    error_message = "Usar una retención soportada: 1, 3, 5, 7, 14, 30, 60 o 90."
  }
}
