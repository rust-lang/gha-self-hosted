#!/bin/bash

set -euo pipefail
IFS=$'\n\t'

PACKAGES=(
    # Needed by QEMU to be able to send a graceful shutdown signal
    acpid

    # Needed by rustc's CI
    docker.io
)

export DEBIAN_FRONTEND=noninteractive

sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y ${PACKAGES[@]}
