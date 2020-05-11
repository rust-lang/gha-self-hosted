#!/bin/bash

set -euo pipefail
IFS=$'\n\t'

# Detect the current partition
full_device="$(mount | grep ' on / ' | awk '{print($1)}')"
device="$(echo "${full_device}" | sed 's/\(.\+\)[0-9]\+$/\1/g')"
partition="$(echo "${full_device}" | sed 's/.\+\([0-9]\+\)$/\1/g')"

# Resize the partition table - https://superuser.com/a/1156509
sudo sgdisk -e "${device}"
sudo sgdisk -d "${partition}" "${device}"
sudo sgdisk -N "${partition}" "${device}"
sudo partprobe "${device}"

# Resize the root file system
sudo resize2fs "${full_device}"
