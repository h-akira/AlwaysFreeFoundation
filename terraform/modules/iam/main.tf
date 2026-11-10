variable "tenancy_ocid" {
  type = string
}

# All platform resources live in this compartment.
resource "oci_identity_compartment" "afp" {
  compartment_id = var.tenancy_ocid
  name           = "afp"
  description    = "AlwaysFreePlatform"
  # Deletable while the platform is being tested.
  enable_delete = true
}

output "compartment_id" {
  value = oci_identity_compartment.afp.id
}
