#!/usr/bin/env bash

set -euo pipefail
IFS=$'\n\t'

CONFIG_DEVICE=/dev/disk/by-label/instance-configuration
CONFIG_DIR=/mnt/instance-configuration

if ! [[ -d "${CONFIG_DIR}" ]]; then
    sudo mkdir "${CONFIG_DIR}"
    sudo mount -o ro "${CONFIG_DEVICE}" "${CONFIG_DIR}"
fi

cd /gha
./run.sh --jitconfig "$(cat "${CONFIG_DIR}/jitconfig")"
sudo poweroff
