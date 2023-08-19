#!/usr/bin/env python3

import json
import os
import tempfile
import subprocess
import uuid

CDROM = "/dev/disk/by-label/instance-configuration"

# Mount the virtual CD containing the environment
temp = tempfile.mkdtemp()
subprocess.run(["sudo", "mount", "-o", "ro", CDROM, temp], check=True)

# Load the environment from it
with open(temp + "/instance.json") as f:
    instance = json.load(f)

# Eject the CD containing the environment
subprocess.run(["sudo", "umount", temp], check=True)
try:
    subprocess.run(["sudo", "eject", CDROM], check=True)
except subprocess.CalledProcessError:
    print("warning: failed to eject the CD-ROM")
os.rmdir(temp)

# Configure the GitHub Actions runner
subprocess.run([
    "./config.sh", "--unattended", "--replace",
    "--url", "https://github.com/" + instance["config"]["repo"],
    "--token", instance["config"]["token"],
    "--name", instance["name"] + uuid.uuid4().hex,
    "--ephemeral",
], check=True)

# Start the runner
env = dict(os.environ)
if "whitelisted-event" in instance["config"]:
    env["RUST_WHITELISTED_EVENT_NAME"] = instance["config"]["whitelisted-event"]
subprocess.run(["./run.sh"], env=env, check=True)

# Stop the machine
subprocess.run(["sudo", "poweroff"], check=True)
