#!/usr/bin/env python3

import json
import os
import pathlib
import random
import shutil
import subprocess
import sys
import telnetlib
import tempfile


DISK_SIZE = "20G"

MONITORING_PORT_RANGE = (50000, 55000)


class VM:
    def __init__(self, base, env):
        self._base = base
        self._env = env

        self._path = pathlib.Path(tempfile.mkdtemp())
        self._path_root = self._path / "root.qcow2"
        self._path_env = self._path / "env.iso"

        self._process = None
        self._monitoring_port = random.randint(*MONITORING_PORT_RANGE)

        self._copy_base_image()
        self._create_environment_cd()

    def _copy_base_image(self):
        if self._path.exists():
            shutil.rmtree(self._path)

        self._path.mkdir(exist_ok=True)
        subprocess.run([
            "qemu-img", "create",
            "-b", str(pathlib.Path(self._base).resolve()),
            "-f", "qcow2",
            str(self._path_root.resolve()),
            DISK_SIZE
        ], check=True)

    def _create_environment_cd(self):
        tempdir = pathlib.Path(tempfile.mkdtemp())
        envjson = tempdir / "environment.json"

        with envjson.open("w") as f:
            json.dump(self._env, f)

        subprocess.run([
            "genisoimage",
            "-output", str(self._path_env.resolve()),
            "-volid", "environment",
            "-joliet", "-rock",
            str(envjson.resolve()),
        ], check=True)

        shutil.rmtree(str(tempdir))

    def run(self):
        if self._process is not None:
            raise RuntimeError("this VM was already started")

        def preexec_fn():
            # Don't forward signals to QEMU
            os.setpgrp()

        self._process = subprocess.Popen([
            "qemu-system-x86_64",
            "-enable-kvm",
            "-m", "2048",
            "-display", "none",
            "-drive", "file=" + str(self._path_root) + ",media=disk,if=virtio",
            "-cdrom", str(self._path_env),
            "-net", "nic,model=virtio",
            "-net", "user,hostfwd=tcp::2222-:22",

            # The monitoring port is used by the shutdown() method to send the
            # shutdown signal to the QEMU VM, instead of killing it.
            "-monitor", "telnet:127.0.0.1:" + str(self._monitoring_port) + ",server,nowait",
        ], preexec_fn=preexec_fn)

        try:
            self._process.wait()
        except KeyboardInterrupt:
            self.shutdown()

        # Shutdown signal was successful, wait for clean shutdown
        if self._process is not None:
            self._process.wait()

    def shutdown(self):
        if self._process is None:
            raise RuntimeError("can't shutdown a stopped VM")

        try:
            telnet = telnetlib.Telnet("127.0.0.1", self._monitoring_port)
            telnet.write("system_powerdown\n".encode("ascii"))
        except:
            self.kill()
            return

        print("==> sent shutdown signal to the VM")

    def kill(self):
        if self._process is None:
            raise RuntimeError("can't kill a stopped VM")

        self._process.kill()
        self._process = None

    def cleanup(self):
        shutil.rmtree(str(self._path))


def run(instance_name):
    with open("instances.json") as f:
        instances = json.load(f)

    instance = None
    for candidate in instances:
        if candidate["name"] == instance_name:
            instance = candidate
            break
    else:
        print(f"error: instance not found: {instance_name}", f=sys.stderr)
        return

    env = {
        "name": instance["name"],
        "config": instance["config"],
    }

    vm = VM(instance["image"], env)
    vm.run()
    vm.cleanup()


if __name__ == "__main__":
    run(sys.argv[1])
