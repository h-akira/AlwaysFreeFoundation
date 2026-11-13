variable "tenancy_ocid" {
  description = "OCID of the tenancy."
  type        = string
}

variable "region" {
  description = "Region to create resources in. Must be the home region (Always Free)."
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
  description = "CIDR block of the VCN. Must contain db_subnet_cidr and vm_subnet_cidr."
  type        = string
  default     = "10.0.0.0/16"
}

variable "db_subnet_cidr" {
  description = "CIDR block of the private subnet for the DB system."
  type        = string
  default     = "10.0.1.0/24"
}

variable "vm_subnet_cidr" {
  description = "CIDR block of the public subnet for the VM. Must be inside vcn_cidr."
  type        = string
  default     = "10.0.0.0/24"
}

variable "https_public" {
  description = "Open port 443 to everyone (true) or only to home_cidrs (false). Port 80 is always open."
  type        = bool
  default     = false
}

variable "ssh_public_key" {
  description = "OpenSSH public key for user opc on the VM, used for maintenance through the Bastion (make ssh)."
  type        = string

  validation {
    condition     = can(regex("^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp[0-9]+) ", var.ssh_public_key))
    error_message = "ssh_public_key must be one OpenSSH public key line."
  }
}

variable "platform_repository" {
  description = "URL of the public platform repository on GitHub (https://github.com/<owner>/<repo>). The VM fetches its code from here."
  type        = string

  validation {
    condition     = can(regex("^https://github\\.com/[^/]+/[^/]+$", var.platform_repository))
    error_message = "platform_repository must look like https://github.com/<owner>/<repo> (no .git, no trailing slash)."
  }
}

variable "vm_shape" {
  description = "Shape of the VM: VM.Standard.A1.Flex (arm64) when it can be created, else VM.Standard.E2.1.Micro (amd64). Flexible shapes (*.Flex) also use vm_ocpus and vm_memory_in_gbs. Changing the CPU type means rebuilding every project's images."
  type        = string
  default     = "VM.Standard.A1.Flex"
}

variable "vm_ocpus" {
  description = "OCPUs of the VM, for flexible shapes only."
  type        = number
  default     = 1
}

variable "vm_memory_in_gbs" {
  description = "Memory of the VM in GB, for flexible shapes only."
  type        = number
  default     = 6
}

variable "vm_availability_domain_index" {
  description = "Index of the availability domain for the VM. Change it when creation fails with OutOfHostCapacity."
  type        = number
  default     = 0
}

variable "vm_generation" {
  description = "Increase by one to replace only the VM (e.g. to pick up a newer image or bootstrap)."
  type        = number
  default     = 1
}
