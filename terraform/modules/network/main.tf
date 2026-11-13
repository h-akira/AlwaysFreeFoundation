variable "compartment_id" {
  type = string
}

variable "vcn_cidr" {
  type = string
}

variable "db_subnet_cidr" {
  type = string
}

variable "vm_subnet_cidr" {
  type = string
}

variable "home_cidrs" {
  type = list(string)
}

variable "https_public" {
  type = bool
}

resource "oci_core_vcn" "afp" {
  compartment_id = var.compartment_id
  display_name   = "afp"
  cidr_blocks    = [var.vcn_cidr]
  dns_label      = "afp"
}

# MySQL from the DB subnet and the VM subnet. The Bastion's private endpoint
# lives in this subnet and shares this list, so it needs the egress rules to
# reach the DB and the VM's ssh port.
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

  egress_security_rules {
    protocol    = "6" # TCP
    destination = var.vm_subnet_cidr
    tcp_options {
      min = 22
      max = 22
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

  ingress_security_rules {
    protocol = "6" # TCP
    source   = var.vm_subnet_cidr
    tcp_options {
      min = 3306
      max = 3306
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

resource "oci_core_internet_gateway" "afp" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.afp.id
  display_name   = "afp"
}

resource "oci_core_route_table" "vm" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.afp.id
  display_name   = "afp-vm"

  route_rules {
    destination       = "0.0.0.0/0"
    network_entity_id = oci_core_internet_gateway.afp.id
  }
}

locals {
  https_sources = var.https_public ? ["0.0.0.0/0"] : var.home_cidrs
}

# Port 80 is always open (HTTP-01 challenges and redirects); 443 is open to
# everyone or only to home_cidrs; ssh only from the Bastion in the DB subnet.
resource "oci_core_security_list" "vm" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.afp.id
  display_name   = "afp-vm"

  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }

  ingress_security_rules {
    protocol = "6" # TCP
    source   = "0.0.0.0/0"
    tcp_options {
      min = 80
      max = 80
    }
  }

  dynamic "ingress_security_rules" {
    for_each = local.https_sources
    content {
      protocol = "6" # TCP
      source   = ingress_security_rules.value
      tcp_options {
        min = 443
        max = 443
      }
    }
  }

  ingress_security_rules {
    protocol = "6" # TCP
    source   = var.db_subnet_cidr
    tcp_options {
      min = 22
      max = 22
    }
  }

  # Path MTU discovery.
  ingress_security_rules {
    protocol = "1" # ICMP
    source   = "0.0.0.0/0"
    icmp_options {
      type = 3
      code = 4
    }
  }
}

resource "oci_core_subnet" "vm" {
  compartment_id    = var.compartment_id
  vcn_id            = oci_core_vcn.afp.id
  display_name      = "afp-vm"
  cidr_block        = var.vm_subnet_cidr
  dns_label         = "vm"
  route_table_id    = oci_core_route_table.vm.id
  security_list_ids = [oci_core_security_list.vm.id]
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

output "vm_subnet_id" {
  value = oci_core_subnet.vm.id
}

output "bastion_id" {
  value = oci_bastion_bastion.afp.id
}
