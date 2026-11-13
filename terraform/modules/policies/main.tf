variable "tenancy_ocid" {
  type = string
}

variable "compartment_id" {
  type = string
}

# Name of the compartment, as written in policy statements.
variable "compartment_name" {
  type = string
}

variable "bucket_name" {
  type = string
}

# Every instance in the compartment acts as the platform's VM.
resource "oci_identity_dynamic_group" "vm" {
  compartment_id = var.tenancy_ocid
  name           = "afp-vm"
  description    = "AlwaysFreePlatform VMs"
  matching_rule  = "ALL {instance.compartment.id = '${var.compartment_id}'}"
}

locals {
  dg = oci_identity_dynamic_group.vm.name
  c  = var.compartment_name
}

resource "oci_identity_policy" "vm" {
  compartment_id = var.compartment_id
  name           = "afp-vm"
  description    = "What the AlwaysFreePlatform VMs may do"
  statements = [
    "Allow dynamic-group ${local.dg} to read secret-bundles in compartment ${local.c}",
    "Allow dynamic-group ${local.dg} to read buckets in compartment ${local.c} where target.bucket.name = '${var.bucket_name}'",
    "Allow dynamic-group ${local.dg} to manage objects in compartment ${local.c} where target.bucket.name = '${var.bucket_name}'",
    "Allow dynamic-group ${local.dg} to read repos in compartment ${local.c}",
    # Run Command: each instance receives only the commands sent to itself.
    "Allow dynamic-group ${local.dg} to use instance-agent-command-execution-family in compartment ${local.c} where request.instance.id = target.instance.id",
  ]
}

output "dynamic_group_id" {
  value = oci_identity_dynamic_group.vm.id
}

output "policy_id" {
  value = oci_identity_policy.vm.id
}
