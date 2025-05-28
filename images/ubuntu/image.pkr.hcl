packer {
  required_plugins {
    qemu = {
      source  = "github.com/hashicorp/qemu"
      version = "~> 1"
    }
  }
}

build {
  sources = ["source.qemu.ubuntu"]

  // Copy the support files the scripts rely on.
  provisioner "shell" {
    inline = [
      "mkdir /tmp/packer-files",
    ]
  }
  provisioner "file" {
    destination = "/tmp/packer-files/"
    source      = "./files/"
  }

  // Run all the scripts needed to configure the machine.
  provisioner "shell" {
    env = {
      GIT_SHA = var.git_sha
    }
    scripts = [
      "./scripts/install-packages.sh",
      "./scripts/install-gha-runner.sh",
      "./scripts/install-awscli.sh",
      "./scripts/setup-ssh.sh",
      "./scripts/setup-disk-resize.sh",
      "./scripts/setup-grub.sh",
      "./scripts/disable-timers.sh",
      "./scripts/finalize.sh",
    ]
  }
}

source "qemu" "ubuntu" {
  vm_name          = "rootfs.qcow2"
  output_directory = "build/packer-tmp"

  accelerator  = var.emulated ? "tcg" : "kvm"
  machine_type = var.arch == "aarch64" ? (var.emulated ? "virt" : "virt,gic_version=3") : "pc"

  # The values of cortex-a57 and Haswell are mostly arbitrary (recent enough CPUs).
  cpu_model = var.emulated ? (var.arch == "aarch64" ? "cortex-a57" : "Haswell") : "host"

  disk_discard   = "unmap"
  disk_image     = true
  disk_interface = "virtio-scsi"
  disk_size      = "5G"

  # Serve the cloud-init/ directory with the QEMU provisioner's HTTP server.
  # This allows us to do the initial configuration (adding the SSH user) with cloud-init.
  http_directory = "cloud-init/"

  # Download the latest cloud image for the specified Ubuntu version. Note that cloud images are
  # periodically rebuilt to include new security updates in them, so we cannot hardcode a checksum.
  iso_checksum = "file:${local.ubuntu_url}/SHA256SUMS"
  iso_url      = "${local.ubuntu_url}/ubuntu-${local.ubuntu_version}-server-cloudimg-${var.arch == "aarch64" ? "arm64" : "amd64"}.img"

  # On AArch64 the machine won't boot unless we provide the QEMU_EFI.fd file as the firmware.
  firmware = var.firmware

  # Do not show any GUI when building the machine.
  use_default_display = true

  qemu_binary = "qemu-system-${var.arch}"
  qemuargs = [
    # Show the VM output in the Packer logs.
    ["-nographic", ""],
    ["-serial", "pty"],
    # Set the kernel parameters,
    ["-smbios", "type=1,serial=ds=nocloud-net;instance-id=gha-self-hosted;seedfrom=http://{{ .HTTPIP }}:{{ .HTTPPort }}/"],
  ]

  # Username and password of the VM are configured through cloud-init.
  ssh_username = "manage"
  ssh_password = "password"

  # For emulated builds we increase the timeouts, as bringing up an emulated VM can be slow.
  ssh_handshake_attempts = var.emulated ? 100 : 10
  ssh_timeout            = var.emulated ? "1h" : "5m"
}

locals {
  ubuntu_version = "24.04"
  ubuntu_url     = "https://cloud-images.ubuntu.com/releases/${local.ubuntu_version}/release"
}

variable "arch" {
  type = string
  validation {
    condition     = var.arch == "x86_64" || var.arch == "aarch64"
    error_message = "Unsupported architecture."
  }
}

variable "emulated" {
  type = bool
}

variable "git_sha" {
  type = string
}

variable "firmware" {
  type    = string
  default = null
}
