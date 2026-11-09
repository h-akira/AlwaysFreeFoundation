variable "compartment_id" {
  type = string
}

variable "vcn_cidr" {
  type = string
}

variable "db_subnet_cidr" {
  type = string
}

variable "home_cidrs" {
  type = list(string)
}

resource "oci_core_vcn" "afp" {
  compartment_id = var.compartment_id
  display_name   = "afp"
  cidr_blocks    = [var.vcn_cidr]
  dns_label      = "afp"
}

# Only MySQL traffic inside the DB subnet. The Bastion's private endpoint lives
# in this subnet and shares this list, so it needs the egress rules to reach the DB.
resource "oci_core_security_list" "db" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.afp.id
  display_name   = "afp-db"

  dynamic "egress_security_rules" {
    for_each = [3306, 33060]
    content {
      protocol    = "6" # TCP
      destination = var.db_subnet_cidr
      tcp_options {
        min = egress_security_rules.value
        max = egress_security_rules.value
      }
    }
  }

  dynamic "ingress_security_rules" {
    for_each = [3306, 33060]
    content {
      protocol = "6" # TCP
      source   = var.db_subnet_cidr
      tcp_options {
        min = ingress_security_rules.value
        max = ingress_security_rules.value
      }
    }
  }
}

resource "oci_core_subnet" "db" {
  compartment_id             = var.compartment_id
  vcn_id                     = oci_core_vcn.afp.id
  display_name               = "afp-db"
  cidr_block                 = var.db_subnet_cidr
  dns_label                  = "db"
  prohibit_public_ip_on_vnic = true
  security_list_ids          = [oci_core_security_list.db.id]
}

resource "oci_bastion_bastion" "afp" {
  compartment_id               = var.compartment_id
  name                         = "afp"
  bastion_type                 = "STANDARD"
  target_subnet_id             = oci_core_subnet.db.id
  client_cidr_block_allow_list = var.home_cidrs
  max_session_ttl_in_seconds   = 10800
}

output "db_subnet_id" {
  value = oci_core_subnet.db.id
}

output "bastion_id" {
  value = oci_bastion_bastion.afp.id
}
