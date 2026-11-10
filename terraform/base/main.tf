# Stack "afp-base": only what Terraform destroy cannot remove.
# A deleted vault stays PENDING_DELETION inside its compartment, so neither can
# be destroyed and recreated repeatedly. Everything else is in terraform/main.

module "iam" {
  source       = "../modules/iam"
  tenancy_ocid = var.tenancy_ocid
}

module "vault" {
  source         = "../modules/vault"
  compartment_id = module.iam.compartment_id
}
