variable "tenancy_ocid" {
  description = "OCID of the tenancy. Set automatically by Resource Manager."
  type        = string
}

variable "region" {
  description = "Region to create resources in. Must be the home region (Always Free). Set automatically by Resource Manager."
  type        = string
}

variable "home_cidrs" {
  description = "CIDR blocks allowed to connect to the Bastion (the administrator's networks), e.g. [\"192.0.2.10/32\"]."
  type        = list(string)

  validation {
    condition     = length(var.home_cidrs) > 0 && alltrue([for c in var.home_cidrs : can(cidrhost(c, 0))])
    error_message = "home_cidrs must be a non-empty list of valid CIDR blocks."
  }
}

variable "db_admin_username" {
  description = "Administrator user name of the MySQL HeatWave DB system."
  type        = string
  default     = "afpadmin"
}

variable "availability_domain_index" {
  description = "Index of the availability domain for the DB system. Change it when creation fails with OutOfHostCapacity."
  type        = number
  default     = 0
}

variable "vcn_cidr" {
  description = "CIDR block of the VCN. Must contain db_subnet_cidr."
  type        = string
  default     = "10.0.0.0/16"
}

variable "db_subnet_cidr" {
  description = "CIDR block of the private subnet for the DB system."
  type        = string
  default     = "10.0.1.0/24"
}
