packer {
  required_plugins {
    qemu = {
      source  = "github.com/hashicorp/qemu"
      version = "~> 1"
    }
  }
}

build {
  sources = ["source.qemu.ubuntu-aarch64", "source.qemu.ubuntu-x86_64"]

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

source "qemu" "ubuntu-x86_64" {
  vm_name          = "rootfs.qcow2"
  output_directory = "build/x86_64"

  accelerator = local.qemu_accelerator
  cpus        = local.build_cpus

  disk_discard   = "unmap"
  disk_image     = true
  disk_interface = "virtio-scsi"
  disk_size      = local.build_disk_size

  # Serve the cloud-init/ directory with the QEMU provisioner's HTTP server.
  # This allows us to do the initial configuration (adding the SSH user).
  http_directory = "cloud-init"

  iso_checksum = "file:https://cloud-images.ubuntu.com/releases/${local.ubuntu_version}/release/SHA256SUMS"
  iso_url      = "https://cloud-images.ubuntu.com/releases/${local.ubuntu_version}/release/ubuntu-${local.ubuntu_version}-server-cloudimg-amd64.img"

  qemu_binary = "qemu-system-x86_64"
  qemuargs = [
    ["-smbios", "type=1,serial=ds=nocloud-net;instance-id=${local.build_hostname};seedfrom=http://{{ .HTTPIP }}:{{ .HTTPPort }}/"],
  ]

  ssh_handshake_attempts = local.ssh_handshake_attempts
  ssh_password           = local.ssh_password
  ssh_timeout            = local.ssh_timeout
  ssh_username           = local.ssh_username

  use_default_display = true
}

source "qemu" "ubuntu-aarch64" {
  vm_name          = "rootfs.qcow2"
  output_directory = "build/aarch64"

  accelerator  = local.qemu_accelerator
  machine_type = var.emulated ? "virt" : "virt,gic_version=3"
  cpus         = local.build_cpus

  disk_discard   = "unmap"
  disk_image     = true
  disk_interface = "virtio-scsi"
  disk_size      = local.build_disk_size

  # Serve the cloud-init/ directory with the QEMU provisioner's HTTP server.
  # This allows us to do the initial configuration (adding the SSH user).
  http_directory = "cloud-init"

  iso_checksum = "file:https://cloud-images.ubuntu.com/releases/${local.ubuntu_version}/release/SHA256SUMS"
  iso_url      = "https://cloud-images.ubuntu.com/releases/${local.ubuntu_version}/release/ubuntu-${local.ubuntu_version}-server-cloudimg-arm64.img"

  # On AArch64 the machine won't boot unless we provide the QEMU_EFI.fd file as the firmware.
  firmware = var.firmware

  qemu_binary = "qemu-system-aarch64"
  qemuargs = [
    ["-nographic", ""],
    ["-serial", "pty"],
    ["-cpu", var.emulated ? "cortex-a57" : "host"],
    ["-smbios", "type=1,serial=ds=nocloud-net;instance-id=${local.build_hostname};seedfrom=http://{{ .HTTPIP }}:{{ .HTTPPort }}/"],
  ]

  ssh_handshake_attempts = local.ssh_handshake_attempts
  ssh_password           = local.ssh_password
  ssh_timeout            = local.ssh_timeout
  ssh_username           = local.ssh_username

  use_default_display = true
}

locals {
  build_cpus      = 8
  build_disk_size = "5G"
  build_hostname  = "gha-self-hosted-vm"

  qemu_accelerator = var.emulated ? "tcg" : "kvm"

  ssh_handshake_attempts = var.emulated ? 100 : 10
  ssh_timeout            = var.emulated ? "1h" : "5m"
  ssh_password           = "password"
  ssh_username           = "manage"

  ubuntu_version = "20.04"
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
