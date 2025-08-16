#!/bin/bash

set -euo pipefail
IFS=$'\n\t'

# CI expects a Rust toolchain to be installed.
DEBIAN_FRONTEND=noninteractive sudo apt install rustup -y
sudo -u gha rustup toolchain install stable --profile minimal
