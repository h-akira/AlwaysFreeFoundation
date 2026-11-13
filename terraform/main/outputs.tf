# Read by scripts/ (e.g. db-tunnel.sh) from the stack's state.

output "compartment_id" {
  value = local.compartment_id
}

output "bastion_id" {
  value = module.network.bastion_id
}

output "db_ip" {
  value = module.database.ip_address
}

output "db_port" {
  value = module.database.port
}

output "db_admin_username" {
  value = var.db_admin_username
}

output "db_admin_secret_id" {
  value = module.secrets.db_admin_secret_id
}

output "bucket" {
  value = module.storage.bucket_name
}

output "namespace" {
  value = data.oci_objectstorage_namespace.this.namespace
}

output "vm_id" {
  value = module.vm.instance_id
}

output "vm_private_ip" {
  value = module.vm.private_ip
}

output "vm_public_ip" {
  value = module.vm.public_ip
}
