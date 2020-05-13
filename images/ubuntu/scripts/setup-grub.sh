#!/bin/bash

set -euo pipefail
IFS=$'\n\t'

# Reduce the GRUB timeout to 1, otherwise some VMs might wait 30 seconds before
# booting into the OS.
sudo sed -i 's/^GRUB_TIMEOUT=[0-9]*$/GRUB_TIMEOUT=1/g' /etc/default/grub
sudo bash -c "echo 'GRUB_RECORDFAIL_TIMEOUT=0' >> /etc/default/grub"
sudo update-grub
