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
with open(temp + "/jitconfig") as f:
    jitconfig = f.read()

# Eject the CD containing the environment
subprocess.run(["sudo", "umount", temp], check=True)
try:
    subprocess.run(["sudo", "eject", CDROM], check=True)
except subprocess.CalledProcessError:
    print("warning: failed to eject the CD-ROM")
os.rmdir(temp)

# Start the runner
subprocess.run(["./run.sh", "--jitconfig", jitconfig], check=True)

# Stop the machine
subprocess.run(["sudo", "poweroff"], check=True)
