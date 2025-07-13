#!/usr/bin/env python3

import json
import os
import pathlib
import random
import re
import shutil
import signal
import subprocess
import sys
import telnetlib
import tempfile
import threading
import time
import urllib.request


# Range of ports where QMP could be bound.
QMP_PORT_RANGE = (50000, 55000)

# How many seconds to wait after a graceful shutdown signal before killing the
# virtual machine.
GRACEFUL_SHUTDOWN_TIMEOUT = 60

# How many seconds should pass between each call to the GitHub API.
GITHUB_API_POLL_INTERVAL = 15

# Architecture-specific QEMU flags and BIOS blob URL.
QEMU_ARCH = {
    "x86_64": {
        "flags": [
            # Standard x86_64 machine with hardware acceleration.
            "-machine",
            "pc,accel=kvm",
        ],
    },
    "aarch64": {
        "flags": [
            # Virtual AArch64 machine with hardware acceleration.
            "-machine",
            "virt,gic_version=3,accel=kvm",
            # Use the host's CPU variant.
            "-cpu",
            "host",
        ],
        # Installed with `sudo apt-get install qemu-efi-aarch64`
        "bios": "/usr/share/qemu-efi-aarch64/QEMU_EFI.fd",
    },
}


class VM:
    def __init__(self, instance, env):
        self._base = instance["image"]
        self._vm_timeout = instance["timeout-seconds"]
        self._ssh_port = instance["ssh-port"]
        self._cpu = instance["cpu-cores"]
        self._ram = instance["ram"]
        self._disk = instance["root-disk"]
        self._env = env

        # Once the GitHub Actions build start, the VM won't reloaad anymore
        # when a SIGUSR1 is received.
        self._prevent_reloads = False

        self._arch = instance["arch"]
        if self._arch not in QEMU_ARCH:
            raise RuntimeError(f"unsupported architecture: {self._arch}")

        self._path = pathlib.Path(tempfile.mkdtemp())
        self._path_root = self._path / "root.qcow2"
        self._path_cdrom = self._path / "env.iso"

        self._process = None
        self._qmp_shutdown_port = random.randint(*QMP_PORT_RANGE)
        self._qmp_tray_ejector_port = random.randint(*QMP_PORT_RANGE)

        self._copy_base_image()
        self._create_config_cdrom()

    def _copy_base_image(self):
        if self._path.exists():
            shutil.rmtree(self._path)

        self._path.mkdir(exist_ok=True)

        log("creating the disk image")
        subprocess.run(
            [
                "qemu-img",
                "create",
                # Path of the base image.
                "-b",
                str(pathlib.Path(self._base).resolve()),
                # Use a Copy on Write filesystem, to avoid having to copy the whole
                # base image every time we start a VM.
                "-f",
                "qcow2",
                # Explicitly set format of backing file
                "-F",
                "qcow2",
                # Path of the destination image.
                str(self._path_root.resolve()),
                # New size of the disk.
                self._disk,
            ],
            check=True,
        )

    def _create_config_cdrom(self):
        tempdir = pathlib.Path(tempfile.mkdtemp())
        envjson = tempdir / "instance.json"

        with envjson.open("w") as f:
            json.dump(self._env, f)

        log("creating the virtual CD-ROM with the instance configuration")
        subprocess.run(
            [
                "genisoimage",
                "-output",
                str(self._path_cdrom.resolve()),
                "-input-charset",
                "utf-8",
                # Call the ISO "instance-configuration"
                "-volid",
                "instance-configuration",
                # Generate a Joliet filesystem, which is preferred by Windows.
                "-joliet",
                # Generate a Rock Ridge filesystem, which is preferred by Linux.
                "-rock",
                # Include the `instance.json` file in the ISO.
                str(envjson.resolve()),
            ],
            check=True,
        )

        shutil.rmtree(str(tempdir))

    def run(self):
        if self._process is not None:
            raise RuntimeError("this VM was already started")

        def preexec_fn():
            # Don't forward signals to QEMU
            os.setpgrp()

        cmd = [
            f"qemu-system-{self._arch}",
            # Reserved RAM for the virtual machine.
            "-m",
            str(self._ram),
            # Allocated cores for the virtual machine.
            "-smp",
            str(self._cpu),
            # Prevent QEMU from showing a graphical console window.
            "-display",
            "none",
            # Mount the VM image as the root drive.
            "-drive",
            "file=" + str(self._path_root) + ",media=disk,if=virtio",
            # Enable networking inside the VM.
            "-net",
            "nic,model=virtio",
            # Forward the 22 port on the host, as the configured SSH port.
            "-net",
            "user,hostfwd=tcp::" + str(self._ssh_port) + "-:22",
            # Mount the instance configuration as a CD-ROM. The mounted ISO is
            # generated by the _create_config_cdrom method.
            "-cdrom",
            str(self._path_cdrom),
            # This QMP port is used by the shutdown() method to send the
            # shutdown signal to the QEMU VM instead of killing it.
            "-qmp",
            "telnet:127.0.0.1:" + str(self._qmp_shutdown_port) + ",server,nowait",
            # This QMP port is used by the TrayEjector thread to eject the
            # CD-ROM as soon as the guest VM opens the tray.
            "-qmp",
            "telnet:127.0.0.1:" + str(self._qmp_tray_ejector_port) + ",server,nowait",
        ]
        cmd += QEMU_ARCH[self._arch]["flags"]

        if "bios" in QEMU_ARCH[self._arch]:
            cmd += ["-bios", QEMU_ARCH[self._arch]["bios"]]

        log("starting the virtual machine")
        self._process = subprocess.Popen(cmd, preexec_fn=preexec_fn)

        TrayEjectorThread(self._qmp_tray_ejector_port).start()

        if "repo" in self._env["config"]:
            GitHubRunnerStatusWatcher(
                self._env["config"]["repo"],
                self._env["name"],
                GITHUB_API_POLL_INTERVAL,
                self._gha_build_started,
            ).start()
        else:
            log("didn't start polling the GitHub API: missing 'repo' in config")

        try:
            self._process.wait()
        except KeyboardInterrupt:
            self.shutdown()

        # Shutdown signal was successful, wait for clean shutdown
        try:
            if self._process is not None:
                self._process.wait()
        except KeyboardInterrupt:
            self.kill()

    def shutdown(self):
        if self._process is None:
            raise RuntimeError("can't shutdown a stopped VM")

        # QEMU allows interacting with the VM through the "monitoring port",
        # using Telnet as the protocol. This tries to connect to the monitoring
        # port to send the graceful shutdown signal. If it fails, we're forced
        # to hard-kill the virtual machine.
        try:
            qmp = QMPClient(self._qmp_shutdown_port)
            qmp.shutdown_vm()
        except Exception as e:
            print("failed to gracefully shutdown the VM:", e)
            self.kill()
            return

        log("sent shutdown signal to the VM")

        Timer("graceful-shutdown-timeout", self.kill, GRACEFUL_SHUTDOWN_TIMEOUT).start()

    def kill(self):
        if self._process is None:
            raise RuntimeError("can't kill a stopped VM")

        self._process.kill()
        self._process = None

        log("killed the virtual machine")

    def cleanup(self):
        shutil.rmtree(str(self._path))

    def sigusr1_received(self):
        if self._prevent_reloads:
            log("did not reload as a build is currently running")
        else:
            log("reload signal received, shutting down the VM")
            self.shutdown()

    def _gha_build_started(self):
        self._prevent_reloads = True
        Timer("vm-timeout", self.shutdown, self._vm_timeout).start()


class GitHubRunnerStatusWatcher(threading.Thread):
    def __init__(self, repo, runner_name, check_interval, then):
        super().__init__(name="github-runner-status-watcher", daemon=True)

        self._check_interval = check_interval
        self._repo = repo
        self._runner_name = runner_name
        self._then = then

    def run(self):
        log("started polling GitHub to detect when the runner started working")
        while True:
            runners = self._retrieve_runners()
            if self._runner_name in runners and runners[self._runner_name]["busy"]:
                log("the runner started processing a build!")
                self._then()
                break
            time.sleep(self._check_interval)

    def _retrieve_runners(self):
        result = {}
        url = f"https://api.github.com/repos/{self._repo}/actions/runners"
        for response in github_api("GET", url):
            for runner in response["runners"]:
                result[runner["name"]] = runner
        return result


# We only want the instance configuration to be available at startup, and not
# when the build is running. To achieve that, this thread monitors QMP for
# DEVICE_TRY_MOVED events, and when the CD-ROM is ejected it detaches it from
# the virtual machine.
class TrayEjectorThread(threading.Thread):
    def __init__(self, qmp_port):
        super().__init__(name="tray-ejector", daemon=True)
        self._qmp_port = qmp_port

    def run(self):
        # Wait for the QMP port to come online.
        qmp = None
        while True:
            try:
                qmp = QMPClient(self._qmp_port)
                break
            except ConnectionRefusedError:
                time.sleep(0.01)

        try:
            while True:
                data = qmp.wait_for_event("DEVICE_TRAY_MOVED")
                if not data["tray-open"]:
                    continue
                qmp.eject(data["device"])
                log("ejected CD-ROM (device: %s)" % data["device"])
        except EOFError:
            # The connection will be closed when the VM shuts down. We don't
            # care if it happens.
            pass


# Simple thread that executes a function after a timeout
class Timer(threading.Thread):
    def __init__(self, name, callback, timeout):
        super().__init__(name=name, daemon=True)

        self._name = name
        self._callback = callback
        self._timeout = timeout

    def run(self):
        log(f"started timer {self._name}, fires in {self._timeout} seconds")

        # The sleep is done in a loop to handle spurious wakeups
        started_at = time.time()
        while time.time() < started_at + self._timeout:
            time.sleep(self._timeout - (time.time() - started_at))

        log(f"timer {self._name} fired")
        self._callback()


# QMP (QEMU Machine Protocol) is a way to control VMs spawned with QEMU, and
# to receive events from them. An introduction to the protocol is available at:
#
#    https://wiki.qemu.org/Documentation/QMP
#
# A full list of commands and events is available at:
#
#    https://www.qemu.org/docs/master/qemu-qmp-ref.html#Commands-and-Events-Index
#
class QMPClient:
    def __init__(self, port):
        self._conn = telnetlib.Telnet("127.0.0.1", port)

        # When starting the connection, QEMU sends a greeting message
        # containing the `QMP` key. To finish the handshake, the command
        # `qmp_capabilities` then needs to be sent.
        greeting = self._read_message()
        if "QMP" not in greeting:
            raise RuntimeError("didn't receive a greeting from the QMP server")
        self._write_message({"execute": "qmp_capabilities"})
        self._read_success()

    def shutdown_vm(self):
        self._write_message({"execute": "system_powerdown"})
        self._read_success()

    def eject(self, device, *, force=False):
        self._write_message(
            {
                "execute": "eject",
                "arguments": {
                    "device": device,
                    "force": force,
                },
            }
        )
        self._read_success()

    def wait_for_event(self, event):
        while True:
            message = self._read_message()
            if "event" in message and message["event"] == event:
                return message["data"]

    def _read_success(self):
        result = self._read_message()
        if "return" not in result:
            raise RuntimeError("QMP returned an error: " + repr(result))

    def _write_message(self, message):
        self._conn.write(json.dumps(message).encode("utf-8") + b"\r\n")

    def _read_message(self):
        return json.loads(self._conn.read_until(b"\n").decode("utf-8").strip())


class ConfigPreprocessor:
    # This regex matches: ${{ FUNCTION:ARGS }}
    _VARIABLE_RE = re.compile(r"^\${{ *(?P<function>[a-zA-Z0-9_-]+):(?P<args>[^}]+)}}$")

    def __init__(self, config):
        self._config = config

    def process(self):
        for key, value in self._config.items():
            matches = self._VARIABLE_RE.match(value)
            if matches is None:
                continue

            function = matches.group("function").strip()
            args = matches.group("args").strip()

            if function == "gha-install-token":
                self._config[key] = self._fetch_gha_install_token(args)
            else:
                raise ValueError(f"unknown preprocessor function: {function}")

        return self._config

    def _fetch_gha_install_token(self, repo):
        log(f"fetching the GHA installation token for {repo}")

        res = next(
            github_api(
                "POST",
                f"https://api.github.com/repos/{repo}/actions/runners/registration-token",
            )
        )
        return res["token"]


NEXT_LINK_RE = re.compile(r"<([^>]+)>; rel=\"next\"")


def github_api(method, url):
    try:
        github_token = os.environ["GITHUB_TOKEN"]
    except KeyError:
        raise RuntimeError("missing environment variable GITHUB_TOKEN") from None

    while url is not None:
        request = urllib.request.Request(url)
        request.add_header(
            "User-Agent",
            "https://github.com/rust-lang/gha-self-hosted (infra@rust-lang.org)",
        )
        request.add_header("Authorization", f"token {github_token}")
        request.method = method

        response = urllib.request.urlopen(request)

        # Handle pagination of the GitHub API
        url = None
        if "Link" in response.headers:
            captures = NEXT_LINK_RE.search(response.headers["Link"])
            if captures is not None:
                url = captures.group(1)

        yield json.load(response)


signal_vms = []


def sigusr1_received(sig, frame):
    for vm in signal_vms:
        vm.sigusr1_received()


def run(instance_name):
    signal.signal(signal.SIGUSR1, sigusr1_received)

    with open("instances.json") as f:
        instances = json.load(f)

    instance = None
    for candidate in instances:
        if candidate["name"] == instance_name:
            instance = candidate
            break
    else:
        print(f"error: instance not found: {instance_name}", file=sys.stderr)
        exit(1)

    config = ConfigPreprocessor(instance["config"])
    env = {
        "name": instance["name"],
        "config": config.process(),
    }

    vm = VM(instance, env)
    signal_vms.append(vm)

    vm.run()
    vm.cleanup()


def log(*args, **kwargs):
    print("==>", *args, **kwargs)
    sys.stdout.flush()


if __name__ == "__main__":
    if len(sys.argv) == 2:
        run(sys.argv[1])
    else:
        print(f"usage: {sys.argv[0]} <instance-name>", file=sys.stderr)
        exit(1)
