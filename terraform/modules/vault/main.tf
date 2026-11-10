variable "compartment_id" {
  type = string
}

# Kept by the base stack: a deleted vault stays PENDING_DELETION inside the
# compartment for days, which blocks deleting the compartment.
resource "oci_kms_vault" "afp" {
  compartment_id = var.compartment_id
  display_name   = "afp"
  vault_type     = "DEFAULT"
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
}

output "vault_id" {
  value = oci_kms_vault.afp.id
}

output "key_id" {
  value = oci_kms_key.afp.id
}
