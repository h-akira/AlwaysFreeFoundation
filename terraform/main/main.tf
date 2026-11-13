# Stack "afp": everything that is created and destroyed repeatedly.
# The compartment, vault and key come from the base stack (terraform/base)
# and are looked up by name, so no values are passed between the stacks.
# The names ("afp") must match terraform/modules/iam and terraform/modules/vault.

data "oci_identity_compartments" "afp" {
  compartment_id = var.tenancy_ocid
  name           = "afp"
  state          = "ACTIVE"

  lifecycle {
    postcondition {
      condition     = length(self.compartments) == 1
      error_message = "Compartment \"afp\" not found; apply the base stack first (make base-plan, make base-apply)."
    }
  }
}

locals {
  compartment_id   = data.oci_identity_compartments.afp.compartments[0].id
  compartment_name = "afp"
  # Also written in terraform/modules/compute/afp-bootstrap.sh.
  bucket_name = "afp"
}

data "oci_kms_vaults" "afp" {
  compartment_id = local.compartment_id

  # Older vaults of the same name may be PENDING_DELETION.
  filter {
    name   = "display_name"
    values = ["afp"]
  }
  filter {
    name   = "state"
    values = ["ACTIVE"]
  }

  lifecycle {
    postcondition {
      condition     = length(self.vaults) == 1
      error_message = "Exactly one ACTIVE vault \"afp\" must exist; apply the base stack first."
    }
  }
}

data "oci_kms_keys" "afp" {
  compartment_id      = local.compartment_id
  management_endpoint = data.oci_kms_vaults.afp.vaults[0].management_endpoint

  filter {
    name   = "display_name"
    values = ["afp"]
  }
  filter {
    name   = "state"
    values = ["ENABLED"]
  }

  lifecycle {
    postcondition {
      condition     = length(self.keys) == 1
      error_message = "Exactly one ENABLED key \"afp\" must exist in vault \"afp\"; apply the base stack first."
    }
  }
}

module "secrets" {
  source         = "../modules/secrets"
  compartment_id = local.compartment_id
  vault_id       = data.oci_kms_vaults.afp.vaults[0].id
  key_id         = data.oci_kms_keys.afp.keys[0].id
}

module "network" {
  source         = "../modules/network"
  compartment_id = local.compartment_id
  vcn_cidr       = var.vcn_cidr
  db_subnet_cidr = var.db_subnet_cidr
  vm_subnet_cidr = var.vm_subnet_cidr
  home_cidrs     = var.home_cidrs
  https_public   = var.https_public
}

module "database" {
  source                    = "../modules/database"
  tenancy_ocid              = var.tenancy_ocid
  compartment_id            = local.compartment_id
  subnet_id                 = module.network.db_subnet_id
  availability_domain_index = var.availability_domain_index
  admin_username            = var.db_admin_username
  admin_password            = module.secrets.db_admin_password
}

data "oci_identity_regions" "this" {
  filter {
    name   = "name"
    values = [var.region]
  }
}

data "oci_objectstorage_namespace" "this" {
  compartment_id = var.tenancy_ocid
}

module "storage" {
  source         = "../modules/storage"
  namespace      = data.oci_objectstorage_namespace.this.namespace
  compartment_id = local.compartment_id
  bucket_name    = local.bucket_name
  afp_config = {
    region              = var.region
    namespace           = data.oci_objectstorage_namespace.this.namespace
    bucket              = local.bucket_name
    platform_repository = var.platform_repository
    db = {
      host            = module.database.ip_address
      port            = module.database.port
      admin_user      = var.db_admin_username
      admin_secret_id = module.secrets.db_admin_secret_id
    }
    image_prefix_base = "${lower(data.oci_identity_regions.this.regions[0].key)}.ocir.io/${data.oci_objectstorage_namespace.this.namespace}/afp"
  }
}

module "policies" {
  source           = "../modules/policies"
  tenancy_ocid     = var.tenancy_ocid
  compartment_id   = local.compartment_id
  compartment_name = local.compartment_name
  bucket_name      = local.bucket_name
}

module "vm" {
  source                    = "../modules/compute"
  tenancy_ocid              = var.tenancy_ocid
  compartment_id            = local.compartment_id
  name                      = "main"
  subnet_id                 = module.network.vm_subnet_id
  availability_domain_index = var.vm_availability_domain_index
  shape                     = var.vm_shape
  ocpus                     = var.vm_ocpus
  memory_in_gbs             = var.vm_memory_in_gbs
  ssh_public_key            = var.ssh_public_key
  generation                = var.vm_generation
  ready_after = [
    module.policies.dynamic_group_id,
    module.policies.policy_id,
    module.storage.afp_json_id,
  ]
}
