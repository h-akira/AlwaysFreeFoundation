variable "namespace" {
  type = string
}

variable "compartment_id" {
  type = string
}

variable "bucket_name" {
  type = string
}

# Contents of afp.json, the VM's view of the platform (read by afp).
variable "afp_config" {
  type = any
}

# Holds afp.json (written here), platform.json (make platform), releases,
# each project's current version and DB dumps. The main stack's destroy
# needs it empty, except for objects Terraform itself manages.
resource "oci_objectstorage_bucket" "afp" {
  compartment_id = var.compartment_id
  namespace      = var.namespace
  name           = var.bucket_name
  access_type    = "NoPublicAccess"
  versioning     = "Disabled"
}

resource "oci_objectstorage_object" "afp_json" {
  namespace    = var.namespace
  bucket       = oci_objectstorage_bucket.afp.name
  object       = "afp.json"
  content      = jsonencode(var.afp_config)
  content_type = "application/json"
}

output "bucket_name" {
  value = oci_objectstorage_bucket.afp.name
}

output "afp_json_id" {
  value = oci_objectstorage_object.afp_json.id
}
