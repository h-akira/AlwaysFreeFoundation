module "iam" {
  source       = "./modules/iam"
  tenancy_ocid = var.tenancy_ocid
}

module "vault" {
  source         = "./modules/vault"
  compartment_id = module.iam.compartment_id
}

module "network" {
  source         = "./modules/network"
  compartment_id = module.iam.compartment_id
  vcn_cidr       = var.vcn_cidr
  db_subnet_cidr = var.db_subnet_cidr
  home_cidrs     = var.home_cidrs
}

module "database" {
  source                    = "./modules/database"
  tenancy_ocid              = var.tenancy_ocid
  compartment_id            = module.iam.compartment_id
  subnet_id                 = module.network.db_subnet_id
  availability_domain_index = var.availability_domain_index
  admin_username            = var.db_admin_username
  admin_password            = module.vault.db_admin_password
}
