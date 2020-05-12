#!/usr/bin/env python3

import json
import os
import tempfile
import subprocess

# Mount the virtual CD containing the environment
temp = tempfile.mkdtemp()
subprocess.run(["sudo", "mount", "-o", "ro", "/dev/cdrom", temp], check=True)

# Load the environment from it
with open(temp + "/instance.json") as f:
    instance = json.load(f)

# Eject the CD containing the environment
subprocess.run(["sudo", "umount", temp], check=True)
subprocess.run(["sudo", "eject", "/dev/cdrom"], check=True)
os.rmdir(temp)

# Configure the GitHub Actions runner
subprocess.run([
    "./config.sh", "--unattended", "--replace",
    "--url", "https://github.com/" + instance["config"]["repo"],
    "--token", instance["config"]["token"],
    "--name", instance["name"],
], check=True)

# Start the runner
env = dict(os.environ)
if "whitelisted-event" in instance["config"]:
    env["RUST_WHITELISTED_EVENT_NAME"] = instance["config"]["whitelisted-event"]
subprocess.run(["./run.sh", "--once"], env=env, check=True)

# Stop the machine
subprocess.run(["sudo", "poweroff"], check=True)
