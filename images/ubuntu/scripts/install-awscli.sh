#!/bin/bash

set -euo pipefail
IFS=$'\n\t'

cd /tmp

ARCH="$(uname -m)"
curl "https://awscli.amazonaws.com/awscli-exe-linux-${ARCH}.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
