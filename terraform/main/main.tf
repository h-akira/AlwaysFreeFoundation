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
  compartment_id = data.oci_identity_compartments.afp.compartments[0].id
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
  home_cidrs     = var.home_cidrs
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
