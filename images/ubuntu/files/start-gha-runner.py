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
    env = json.load(f)

# Eject the CD containing the environment
subprocess.run(["sudo", "umount", temp], check=True)
os.rmdir(temp)

# Configure the GitHub Actions runner
subprocess.run([
    "./config.sh", "--unattended", "--replace",
    "--url", "https://github.com/" + env["config"]["repo"],
    "--token", env["config"]["token"],
    "--name", env["name"],
], check=True)

# Start the runner
subprocess.run(["./run.sh", "--once"], check=True)

# Stop the machine
subprocess.run(["sudo", "poweroff"], check=True)
