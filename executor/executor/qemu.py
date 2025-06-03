from .github import GitHubRunnerStatusWatcher
from .qmp import QMPClient
from .utils import log, Timer
import os
import pathlib
import shutil
import subprocess
import tempfile


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
    def __init__(self, cli, instance, runner):
        self._cli = cli
        self._base = instance["image"]
        self._vm_timeout = instance["timeout-seconds"]
        self._ssh_port = instance["ssh-port"]
        self._cpu = instance["cpu-cores"]
        self._ram = instance["ram"]
        self._disk = instance["root-disk"]
        self._runner = runner

        # Once the GitHub Actions build start, the VM won't reloaad anymore
        # when a SIGUSR1 is received.
        self._prevent_reloads = False

        self._arch = instance["arch"]
        if self._arch not in QEMU_ARCH:
            raise RuntimeError(f"unsupported architecture: {self._arch}")

        self._path = pathlib.Path(tempfile.mkdtemp())
        self._path_root = self._path / "root.qcow2"

        self._process = None
        self._qmp_shutdown_path = self._path / "shutdown.sock"

        self._copy_base_image()

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
            # Pass the jitconfig to the runner using systemd credentials.
            "-smbios",
            f"type=11,value=io.systemd.credential:gha-jitconfig={self._runner.jitconfig}",
            # This QMP port is used by the shutdown() method to send the
            # shutdown signal to the QEMU VM instead of killing it.
            "-qmp",
            "unix:" + str(self._qmp_shutdown_path) + ",server,nowait",
        ]
        cmd += QEMU_ARCH[self._arch]["flags"]

        if "bios" in QEMU_ARCH[self._arch]:
            cmd += ["-bios", QEMU_ARCH[self._arch]["bios"]]

        log("starting the virtual machine")
        self._process = subprocess.Popen(cmd, preexec_fn=preexec_fn)

        GitHubRunnerStatusWatcher(gh, self._runner.id, self._gha_build_started).start()

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
            qmp = QMPClient(self._qmp_shutdown_path)
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
