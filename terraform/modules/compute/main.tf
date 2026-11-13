variable "tenancy_ocid" {
  type = string
}

variable "compartment_id" {
  type = string
}

# The VM's name in the project list ("main").
variable "name" {
  type = string
}

variable "subnet_id" {
  type = string
}

variable "availability_domain_index" {
  type = number
}

variable "shape" {
  type = string
}

# Used only for flexible shapes.
variable "ocpus" {
  type = number
}

variable "memory_in_gbs" {
  type = number
}

variable "ssh_public_key" {
  type = string
}

# Bumping it replaces the VM.
variable "generation" {
  type = number
}

# IDs of what the VM needs at its first boot (dynamic group, policy,
# afp.json). The VM is created only after them: an instance that joins a
# dynamic group later waits up to 30 minutes before Run Command works.
variable "ready_after" {
  type = list(string)
}

data "oci_identity_availability_domains" "all" {
  compartment_id = var.tenancy_ocid
}

# Latest Oracle Linux 9 platform image for the shape (no GPU or minimal images).
data "oci_core_images" "ol9" {
  compartment_id           = var.compartment_id
  operating_system         = "Oracle Linux"
  operating_system_version = "9"
  shape                    = var.shape
  state                    = "AVAILABLE"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"

  filter {
    name   = "display_name"
    values = ["^Oracle-Linux-9\\.[0-9]+-[0-9]{4}\\.[0-9]{2}\\.[0-9]{2}-[0-9]+$"]
    regex  = true
  }
}

resource "terraform_data" "generation" {
  input = var.generation
}

resource "terraform_data" "ready" {
  input = var.ready_after
}

locals {
  # Only the fixed bootstrap goes into user_data; the project list and the
  # platform code version are read from the bucket at run time.
  user_data = join("\n", ["#cloud-config", yamlencode({
    write_files = [
      {
        path        = "/usr/local/sbin/afp-bootstrap"
        permissions = "0755"
        content     = file("${path.module}/afp-bootstrap.sh")
      },
      {
        path        = "/etc/systemd/system/afp-bootstrap.service"
        permissions = "0644"
        content     = file("${path.module}/afp-bootstrap.service")
      },
    ]
    runcmd = [
      ["systemctl", "daemon-reload"],
      ["systemctl", "enable", "--now", "--no-block", "afp-bootstrap.service"],
    ]
  })])
}

resource "oci_core_instance" "vm" {
  compartment_id      = var.compartment_id
  display_name        = "afp-${var.name}"
  availability_domain = data.oci_identity_availability_domains.all.availability_domains[var.availability_domain_index].name
  shape               = var.shape

  dynamic "shape_config" {
    for_each = endswith(var.shape, ".Flex") ? [1] : []
    content {
      ocpus         = var.ocpus
      memory_in_gbs = var.memory_in_gbs
    }
  }

  create_vnic_details {
    subnet_id        = var.subnet_id
    display_name     = "afp-${var.name}"
    hostname_label   = var.name
    assign_public_ip = false # the reserved IP below is attached instead
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ol9.images[0].id
    boot_volume_size_in_gbs = 50
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data           = base64encode(local.user_data)
  }

  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }

  agent_config {
    plugins_config {
      name          = "Compute Instance Run Command"
      desired_state = "ENABLED"
    }
    # Enabled by default on the image; the platform does not use Cloud Guard
    # Instance Security, and the VM has little memory to spare.
    plugins_config {
      name          = "Cloud Guard Workload Protection"
      desired_state = "DISABLED"
    }
  }

  lifecycle {
    # A newer image, a new bootstrap or a new ssh key reach the VM only when
    # it is recreated (bump vm_generation).
    ignore_changes       = [source_details[0].source_id, metadata]
    replace_triggered_by = [terraform_data.generation]
  }

  depends_on = [terraform_data.ready]
}

data "oci_core_vnic_attachments" "vm" {
  compartment_id = var.compartment_id
  instance_id    = oci_core_instance.vm.id
}

data "oci_core_private_ips" "vm" {
  vnic_id = data.oci_core_vnic_attachments.vm.vnic_attachments[0].vnic_id
}

# Kept across VM replacements, so DNS records need no change.
resource "oci_core_public_ip" "vm" {
  compartment_id = var.compartment_id
  display_name   = "afp-${var.name}"
  lifetime       = "RESERVED"
  private_ip_id  = data.oci_core_private_ips.vm.private_ips[0].id
}

output "instance_id" {
  value = oci_core_instance.vm.id
}

output "private_ip" {
  value = oci_core_instance.vm.private_ip
}

output "public_ip" {
  value = oci_core_public_ip.vm.ip_address
}
