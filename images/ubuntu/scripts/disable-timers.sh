#!/bin/bash

set -euo pipefail
IFS=$'\n\t'

# Disable timers updating stuff in the background while the VM is running. We
# had failures on CI due to the VM updating software in the background, and
# that should not happen. The VM is ephemeral and periodically rebuilt anyway.
sudo systemctl mask \
    apport-autoreport.timer \
    apt-daily-upgrade.timer \
    apt-daily.timer \
    dpkg-db-backup.timer \
    e2scrub_all.timer \
    fstrim.timer \
    fwupd-refresh.timer \
    logrotate.timer \
    man-db.timer \
    motd-news.timer \
    snapd.snap-repair.timer \
    sysstat-collect.timer \
    sysstat-summary.timer \
    systemd-tmpfiles-clean.timer \
    ua-timer.timer \
    update-notifier-download.timer \
    update-notifier-motd.timer
