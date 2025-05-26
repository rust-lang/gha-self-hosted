#!/usr/bin/env bash
# Running QEMU for AArch64 requires the QEMU_EFI.fd file to be provided. Some distributions like
# Debian and Ubuntu package it, but the path they use is not consistent across distros. To avoid
# problems, this script downloads the Debian version into our build directory.

set -euo pipefail
IFS=$'\n\t'

# If this ever becomes unavailable, pick a new URL and the corresponding SHA256 from:
#
#    https://packages.debian.org/stable/all/qemu-efi-aarch64/download
#
PACKAGE_URL="http://ftp.debian.org/debian/pool/main/e/edk2/qemu-efi-aarch64_2022.11-6+deb12u2_all.deb"
PACKAGE_SHA256="9a55c7b94fdf13a28928359a77d42e5364aa3ae2e558bd1fd5361955bf479d81"

if [[ $# -ne 1 ]]; then
    echo "usage: $0 <dest>"
    exit 1
fi
dest="$(realpath "$1")"

# Avoid cluttering the working directory.
cd "$(mktemp -d)"

# Download and verify the package
curl -o package.deb -L "${PACKAGE_URL}"
echo "${PACKAGE_SHA256}  package.deb" | sha256sum -c

# Extract the Debian package and move the resulting file into the destination.
ar x package.deb
tar xf data.tar.xz
cp usr/share/qemu-efi-aarch64/QEMU_EFI.fd "${dest}"
