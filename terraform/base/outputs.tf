# For checking only; the main stack looks these up by name.

output "compartment_id" {
  value = module.iam.compartment_id
}

output "vault_id" {
  value = module.vault.vault_id
}

output "key_id" {
  value = module.vault.key_id
}
