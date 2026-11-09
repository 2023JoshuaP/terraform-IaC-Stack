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

variable "force_delete" {
  type    = bool
  default = false
}
