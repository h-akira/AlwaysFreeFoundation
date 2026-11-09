variable "compartment_id" {
  type = string
}

resource "oci_kms_vault" "afp" {
  compartment_id = var.compartment_id
  display_name   = "afp"
  vault_type     = "DEFAULT"

  lifecycle {
    prevent_destroy = true
  }
}

resource "oci_kms_key" "afp" {
  compartment_id      = var.compartment_id
  display_name        = "afp"
  management_endpoint = oci_kms_vault.afp.management_endpoint
  protection_mode     = "SOFTWARE"

  key_shape {
    algorithm = "AES"
    length    = 32
  }

  lifecycle {
    prevent_destroy = true
  }
}

# The DB system needs the password at creation, so Terraform generates it.
# It ends up in the Resource Manager state either way.
resource "random_password" "db_admin" {
  length      = 24
  min_upper   = 1
  min_lower   = 1
  min_numeric = 1
  min_special = 1
  # Avoid characters that need quoting in shells and URLs.
  override_special = "-_.!#%+="
}

resource "oci_vault_secret" "db_admin_password" {
  compartment_id = var.compartment_id
  vault_id       = oci_kms_vault.afp.id
  key_id         = oci_kms_key.afp.id
  secret_name    = "afp-db-admin-password"
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
