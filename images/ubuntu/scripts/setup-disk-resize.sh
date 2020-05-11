#!/bin/bash

set -euo pipefail
IFS=$'\n\t'

# Install a small service that resizes the disk on boot
sudo cp /tmp/packer-files/resize-disk.service /etc/systemd/system/resize-disk.service
sudo cp /tmp/packer-files/resize-disk.sh /usr/local/bin/resize-disk
sudo chmod +x /usr/local/bin/resize-disk
sudo systemctl daemon-reload
sudo systemctl enable resize-disk.service # Will start at the next boot.
