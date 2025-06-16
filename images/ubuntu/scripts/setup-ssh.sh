#!/bin/bash

set -euo pipefail
IFS=$'\n\t'

# Install a small service that regenerates SSH host keys on boot.
sudo cp /tmp/packer-files/regenerate-ssh-host-keys.service /etc/systemd/system/regenerate-ssh-host-keys.service
sudo systemctl daemon-reload
sudo systemctl enable regenerate-ssh-host-keys.service # Will start at the next boot.

# Remove the current host keys
sudo rm /etc/ssh/ssh_host_*
