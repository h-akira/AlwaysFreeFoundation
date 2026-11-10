# Stack "afp-base": what is never destroyed with the main stack (terraform/main).
# A deleted vault stays PENDING_DELETION inside its compartment, so neither can
# be destroyed and recreated repeatedly.

module "iam" {
  source       = "../modules/iam"
  tenancy_ocid = var.tenancy_ocid
}

module "vault" {
  source         = "../modules/vault"
  compartment_id = module.iam.compartment_id
}
