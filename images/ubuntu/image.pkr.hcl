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

  accelerator = var.env_qemu_accelerator
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

  ssh_handshake_attempts = var.env_ssh_handshake_attempts
  ssh_password           = local.ssh_password
  ssh_timeout            = var.env_ssh_timeout
  ssh_username           = local.ssh_username

  use_default_display = true
}

source "qemu" "ubuntu-aarch64" {
  vm_name          = "rootfs.qcow2"
  output_directory = "build/aarch64"

  accelerator  = var.env_qemu_accelerator
  machine_type = var.env_aarch64_machine
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

  qemu_binary = "qemu-system-aarch64"
  qemuargs = [
    ["-nographic", ""],
    ["-serial", "pty"],
    ["-cpu", "${var.env_aarch64_cpu}"],
    ["-bios", "/usr/share/qemu-efi-aarch64/QEMU_EFI.fd"],
    ["-smbios", "type=1,serial=ds=nocloud-net;instance-id=${local.build_hostname};seedfrom=http://{{ .HTTPIP }}:{{ .HTTPPort }}/"],
  ]

  ssh_handshake_attempts = var.env_ssh_handshake_attempts
  ssh_password           = local.ssh_password
  ssh_timeout            = var.env_ssh_timeout
  ssh_username           = local.ssh_username

  use_default_display = true
}

locals {
  build_cpus      = 8
  build_disk_size = "5G"
  build_hostname  = "gha-self-hosted-vm"

  ssh_username = "manage"
  ssh_password = "password"

  ubuntu_version = "20.04"
}

variable "env_aarch64_cpu" {
  type    = string
  default = "${env("AARCH64_CPU")}"
}

variable "env_aarch64_machine" {
  type    = string
  default = "${env("AARCH64_MACHINE")}"
}

variable "git_sha" {
  type    = string
  default = env("GIT_SHA")
}

variable "env_qemu_accelerator" {
  type    = string
  default = "${env("QEMU_ACCELERATOR")}"
}

variable "env_ssh_handshake_attempts" {
  type    = string
  default = "${env("SSH_HANDSHAKE_ATTEMPTS")}"
}

variable "env_ssh_timeout" {
  type    = string
  default = "${env("SSH_TIMEOUT")}"
}
