# Runs on OCI Resource Manager, which supports Terraform 1.5.x.
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 6.0.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.5.0"
    }
  }
}

# Resource Manager authenticates the provider itself; only the region is set.
provider "oci" {
  region = var.region
}
