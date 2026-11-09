variable "tenancy_ocid" {
  type = string
}

variable "compartment_id" {
  type = string
}

variable "subnet_id" {
  type = string
}

variable "availability_domain_index" {
  type = number
}

variable "admin_username" {
  type = string
}

variable "admin_password" {
  type      = string
  sensitive = true
}

data "oci_identity_availability_domains" "all" {
  compartment_id = var.tenancy_ocid
}

# Always Free MySQL HeatWave (one per tenancy). The version is left unset so
# that it starts at the latest and follows the service's upgrades.
resource "oci_mysql_mysql_db_system" "afp" {
  compartment_id          = var.compartment_id
  display_name            = "afp-db"
  availability_domain     = data.oci_identity_availability_domains.all.availability_domains[var.availability_domain_index].name
  shape_name              = "MySQL.Free"
  subnet_id               = var.subnet_id
  admin_username          = var.admin_username
  admin_password          = var.admin_password
  data_storage_size_in_gb = 50
  is_highly_available     = false
  hostname_label          = "db"

  backup_policy {
    is_enabled        = true
    retention_in_days = 1
  }

  lifecycle {
    # The service upgrades the version during maintenance.
    ignore_changes = [mysql_version]
  }
}

output "ip_address" {
  value = oci_mysql_mysql_db_system.afp.ip_address
}

output "port" {
  value = oci_mysql_mysql_db_system.afp.port
}
