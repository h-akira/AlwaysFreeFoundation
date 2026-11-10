variable "compartment_id" {
  type = string
}

variable "vault_id" {
  type = string
}

variable "key_id" {
  type = string
}

# A deleted secret stays PENDING_DELETION in the vault, which outlives this
# stack. A suffix per stack lifetime keeps recreated names from colliding.
resource "random_id" "suffix" {
  byte_length = 4
}

# The DB system needs the password at creation, so Terraform generates it.
# It ends up in the Resource Manager state either way.
resource "random_password" "db_admin" {
  length      = 24
  min_upper   = 1
  min_lower   = 1
  min_numeric = 1
  min_special = 1
  # Only symbols usable as-is in URLs; HeatWave requires at least one symbol.
  override_special = "-_.~"
}

resource "oci_vault_secret" "db_admin_password" {
  compartment_id = var.compartment_id
  vault_id       = var.vault_id
  key_id         = var.key_id
  secret_name    = "afp-db-admin-password-${random_id.suffix.hex}"
  description    = "Administrator password of the MySQL HeatWave DB system"

  secret_content {
    content_type = "BASE64"
    content      = base64encode(random_password.db_admin.result)
  }
}

output "db_admin_password" {
  value     = random_password.db_admin.result
  sensitive = true
}

output "db_admin_secret_id" {
  value = oci_vault_secret.db_admin_password.id
}
