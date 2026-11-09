variable "name" {
  type    = string
  default = "cloud-integrador-lab"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "vpc_id" {
  description = "Output vpc_id de network, o VPC existente compatible."
  type        = string
  validation {
    condition     = can(regex("^vpc-[a-f0-9]+$", var.vpc_id))
    error_message = "Proporcionar un ID de VPC válido."
  }
}

variable "subnet_ids" {
  description = "Output private_subnet_ids de network; dos subredes privadas en zonas distintas."
  type        = list(string)
  validation {
    condition     = length(distinct(var.subnet_ids)) >= 2 && alltrue([for id in var.subnet_ids : can(regex("^subnet-[a-f0-9]+$", id))])
    error_message = "Proporcionar al menos dos IDs de subredes privadas diferentes."
  }
}

variable "source_security_group_id" {
  description = "Output node_security_group_id de network, autorizado a conectarse a PostgreSQL."
  type        = string
  validation {
    condition     = can(regex("^sg-[a-f0-9]+$", var.source_security_group_id))
    error_message = "Proporcionar un security group válido del origen autorizado."
  }
}

variable "instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "engine_version" {
  description = "null selecciona la versión predeterminada disponible de AWS."
  type        = string
  default     = null
}

variable "db_name" {
  type    = string
  default = "proceedhub"
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{0,62}$", var.db_name))
    error_message = "Usar un nombre alfanumérico en minúsculas que empiece por letra."
  }
}

variable "username" {
  type    = string
  default = "hubadmin"
}

variable "password" {
  description = "Inyectar con TF_VAR_password; proteger el estado porque contiene este valor."
  type        = string
  sensitive   = true
  validation {
    condition     = length(var.password) >= 16 && length(var.password) <= 128 && can(regex("^[!-~]+$", var.password)) && !can(regex("[/@\" ]", var.password))
    error_message = "Usar 16–128 caracteres ASCII imprimibles, sin espacios, /, @ ni comillas dobles."
  }
}

variable "allocated_storage" {
  type    = number
  default = 20
  validation {
    condition     = var.allocated_storage >= 20 && var.allocated_storage <= 100 && var.allocated_storage == floor(var.allocated_storage)
    error_message = "Usar entre 20 y 100 GiB enteros."
  }
}

variable "deletion_protection" {
  type    = bool
  default = true
}

variable "skip_final_snapshot" {
  type    = bool
  default = false
}

variable "final_snapshot_identifier" {
  description = "Nombre único de la copia final. Requerido salvo aprobación explícita para omitirla."
  type        = string
  default     = null
}

variable "log_retention_days" {
  type    = number
  default = 7
  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90], var.log_retention_days)
    error_message = "Usar una retención soportada: 1, 3, 5, 7, 14, 30, 60 o 90."
  }
}
