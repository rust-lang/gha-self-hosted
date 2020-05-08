#!/bin/bash

set -euo pipefail
IFS=$'\n\t'

export DEBIAN_FRONTEND=noninteractive

# Regenerate the SSH host keys, which were deleted during VM creation.
dpkg-reconfigure openssh-server
