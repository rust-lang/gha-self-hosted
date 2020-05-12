#!/bin/bash
# Install and configure the GitHub Actions runner on the image.

set -euo pipefail
IFS=$'\n\t'

AGENT_VERSION="2.262.0-rust2"
AGENT_PLATFORM="linux-x64"
AGENT_REPO="rust-lang/gha-runner"

echo "adding the gha user..."
sudo adduser gha --home /gha --disabled-password
echo "gha ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/gha-nopasswd

echo "downloading and installing the runner..."
cd /gha
sudo -u gha -- curl -Lo runner.tar.gz https://github.com/${AGENT_REPO}/releases/download/v${AGENT_VERSION}/actions-runner-${AGENT_PLATFORM}-${AGENT_VERSION}.tar.gz
sudo -u gha -- tar -xzf ./runner.tar.gz
sudo -u gha -- rm ./runner.tar.gz

echo "configuring startup of the runner..."
sudo cp /tmp/packer-files/gha-runner.service /etc/systemd/system/gha-runner.service
sudo cp /tmp/packer-files/start-gha-runner.py /usr/local/bin/start-gha-runner
sudo chmod +x /usr/local/bin/start-gha-runner
sudo systemctl daemon-reload
sudo systemctl enable gha-runner.service # Will start at the next boot.
