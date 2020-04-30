#!/usr/bin/env python3

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile


DISK_SIZE = "20G"


class VM:
    def __init__(self, base, env):
        self._base = base
        self._env = env

        self._path = pathlib.Path(tempfile.mkdtemp())
        self._path_root = self._path / "root.qcow2"
        self._path_env = self._path / "env.iso"

        self._process = None

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

    def start(self):
        if self._process is not None:
            raise RuntimeError("this VM was already started")

        self._process = subprocess.Popen([
            "qemu-system-x86_64",
            "-enable-kvm",
            "-m", "2048",
            "-display", "none",
            "-drive", "file=" + str(self._path_root) + ",media=disk,if=virtio",
            "-cdrom", str(self._path_env),
            "-net", "nic,model=virtio",
            "-net", "user,hostfwd=tcp::2222-:22",
        ])
        self._process.wait()

    def kill(self):
        if self._process is None:
            raise RuntimeError("can't kill a stopped VM")

        self._process.kill()
        self._process = None

    def cleanup(self):
        shutil.rmtree(str(self._path))


def run(env_name):
    with open("environments.json") as f:
        envs = json.load(f)

    env = {
        "name": env_name,
        "config": envs[env_name]["config"],
    }

    vm = VM(envs[env_name]["image"], env)
    try:
        vm.start()
    except KeyboardInterrupt:
        vm.kill()
    vm.cleanup()


if __name__ == "__main__":
    run(sys.argv[1])
