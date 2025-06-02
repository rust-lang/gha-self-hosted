from .github import GITHUB_API_POLL_INTERVAL, GitHubRunnerStatusWatcher
from .qmp import QMPClient
from .utils import log, Timer
import json
import os
import pathlib
import random
import shutil
import subprocess
import tempfile


# Range of ports where QMP could be bound.
QMP_PORT_RANGE = (50000, 55000)

# How many seconds to wait after a graceful shutdown signal before killing the
# virtual machine.
GRACEFUL_SHUTDOWN_TIMEOUT = 60

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

    def run(self, gh):
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
                gh,
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
