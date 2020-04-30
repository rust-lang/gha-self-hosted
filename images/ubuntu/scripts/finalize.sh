#!/bin/bash

set -euo pipefail
IFS=$'\n\t'

# Commit changes to disk, to prevent losing them when Packer kills the VM at
# the end of the build.
#
#   MUST BE THE LAST COMMAND EXECUTED IN THIS SCRIPT!
#
echo "synchronizing changes to disk..."
sudo sync
