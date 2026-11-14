variable "compartment_id" {
  type = string
}

variable "vault_id" {
  type = string
}

variable "key_id" {
  type = string
}

# var.projects of the main stack.
variable "projects" {
  type = list(object({
    name = string
    secrets = list(object({
      name = string
      how  = string
    }))
  }))
}

# A deleted secret stays PENDING_DELETION in the vault, which outlives this
# stack. A suffix per stack lifetime keeps recreated names from colliding.
resource "random_id" "suffix" {
  byte_length = 4
}

# The DB system needs the password at creation, so Terraform generates it.
# It ends up in the Resource Manager state either way.
resource "random_password" "db_admin" {
  length      = 24
  min_upper   = 1
  min_lower   = 1
  min_numeric = 1
  min_special = 1
  # Only symbols usable as-is in URLs; HeatWave requires at least one symbol.
  override_special = "-_.~"
}

resource "oci_vault_secret" "db_admin_password" {
  compartment_id = var.compartment_id
  vault_id       = var.vault_id
  key_id         = var.key_id
  secret_name    = "afp-db-admin-password-${random_id.suffix.hex}"
  description    = "Administrator password of the MySQL HeatWave DB system"

  secret_content {
    content_type = "BASE64"
    content      = base64encode(random_password.db_admin.result)
  }
}

locals {
  projects = { for p in var.projects : p.name => p }
  # "<project>/<NAME>" => {project, name}
  generated = merge([for p in var.projects : {
    for s in p.secrets : "${p.name}/${s.name}" => { project = p.name, name = s.name } if s.how == "generate"
  }]...)
  manual = merge([for p in var.projects : {
    for s in p.secrets : "${p.name}/${s.name}" => { project = p.name, name = s.name } if s.how == "manual"
  }]...)
}

# Same rules as the administrator's password (ADR 011).
resource "random_password" "project_db" {
  for_each         = local.projects
  length           = 24
  min_upper        = 1
  min_lower        = 1
  min_numeric      = 1
  min_special      = 1
  override_special = "-_.~"
}

resource "random_password" "generated" {
  for_each         = local.generated
  length           = 32
  min_upper        = 1
  min_lower        = 1
  min_numeric      = 1
  min_special      = 1
  override_special = "-_.~"
}

# One suffix per secret, so that a project (or a manual secret) removed and
# added again does not collide with its own name that is still pending deletion.
resource "random_id" "project" {
  for_each    = local.projects
  byte_length = 4
}

resource "random_id" "manual" {
  for_each    = local.manual
  byte_length = 4
}

# One JSON secret per project: AFP_DB_PASSWORD and the generated secrets.
resource "oci_vault_secret" "project" {
  for_each       = local.projects
  compartment_id = var.compartment_id
  vault_id       = var.vault_id
  key_id         = var.key_id
  secret_name    = "afp-${each.key}-${random_id.project[each.key].hex}"
  description    = "AlwaysFreePlatform project ${each.key}: DB password and generated secrets"

  secret_content {
    content_type = "BASE64"
    content = base64encode(jsonencode(merge(
      { AFP_DB_PASSWORD = random_password.project_db[each.key].result },
      { for k, v in local.generated : v.name => random_password.generated[k].result if v.project == each.key },
    )))
  }
}

# Manual secrets start with a placeholder; the project puts the real value in
# as a new secret version, which Terraform leaves alone.
resource "oci_vault_secret" "manual" {
  for_each       = local.manual
  compartment_id = var.compartment_id
  vault_id       = var.vault_id
  key_id         = var.key_id
  secret_name    = "afp-${each.value.project}-${each.value.name}-${random_id.manual[each.key].hex}"
  description    = "AlwaysFreePlatform project ${each.value.project}: ${each.value.name} (set the value by hand)"

  secret_content {
    content_type = "BASE64"
    content      = base64encode("CHANGE_ME")
  }

  lifecycle {
    ignore_changes = [secret_content]
  }
}

# Per project: the JSON secret and the manual secrets by name.
output "project_secrets" {
  value = { for name, p in local.projects : name => {
    secret_id         = oci_vault_secret.project[name].id
    manual_secret_ids = { for k, v in local.manual : v.name => oci_vault_secret.manual[k].id if v.project == name }
  } }
}

output "db_admin_password" {
  value     = random_password.db_admin.result
  sensitive = true
}

output "db_admin_secret_id" {
  value = oci_vault_secret.db_admin_password.id
}
