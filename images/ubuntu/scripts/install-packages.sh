#!/bin/bash

set -euo pipefail
IFS=$'\n\t'

export DEBIAN_FRONTEND=noninteractive

sudo apt-get update
sudo apt-get install -y \
    docker.io
