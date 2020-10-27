#!/bin/bash

set -euo pipefail
IFS=$'\n\t'

# Disable timers updating stuff in the background while the VM is running. We
# had failures on CI due to the VM updating software in the background, and
# that should not happen. The VM is ephemeral and periodically rebuilt anyway.
sudo systemctl disable \
    motd-news.timer \
    apt-daily.timer \
    fwupd-refresh.timer \
    apt-daily-upgrade.timer
