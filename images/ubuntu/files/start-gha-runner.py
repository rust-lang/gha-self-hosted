#!/usr/bin/env python3

import json
import os
import tempfile
import subprocess
import uuid

CDROM = "/dev/disk/by-label/instance-configuration"

# Mount the virtual block device containing the environment
temp = tempfile.mkdtemp()
subprocess.run(["sudo", "mount", "-o", "ro", CDROM, temp], check=True)

# Load the environment from it
with open(temp + "/jitconfig") as f:
    jitconfig = f.read()

# Start the runner
subprocess.run(["./run.sh", "--jitconfig", jitconfig], check=True)

# Stop the machine
subprocess.run(["sudo", "poweroff"], check=True)
