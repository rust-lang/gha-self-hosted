from executor.http_server import CredentialServer
from .github import GitHubRunnerStatusWatcher
from .qmp import QMPClient
from .utils import log, Timer
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
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
        "bios": None,
        "cpu_model": None,
        # Standard x86_64 machine with hardware acceleration.
        "machine": "pc,accel=kvm",
    },
    "aarch64": {
        # Installed with `sudo apt-get install qemu-efi-aarch64`
        "bios": "/usr/share/qemu-efi-aarch64/QEMU_EFI.fd",
        # Use the host's CPU variant.
        "cpu_model": "host",
        # Virtual AArch64 machine with hardware acceleration.
        "machine": "virt,gic_version=3,accel=kvm",
    },
}


class VM:
    def __init__(self, cli, instance, image, runner):
        self._cli = cli
        self._base = image
        self._vm_timeout = instance["timeout-seconds"]
        self._cpu = instance["cpu-cores"]
        self._ram = instance["ram"]
        self._disk = instance["root-disk"]
        self._runner = runner

        # Once the GitHub Actions build start, the VM won't shutdown anymore when requested by the
        # outside world (for example due to a SIGTERM, or a new image being available), as that
        # would kill the CI build running in the VM.
        self._prevent_external_shutdowns = False

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
            stdout=subprocess.DEVNULL,
            check=True,
        )

    def run(self, gh):
        if self._process is not None:
            raise RuntimeError("this VM was already started")

        qemu = QemuInvocation(
            cpu_cores=self._cpu,
            memory=self._ram,
            drive=f"file={self._path_root},media=disk,if=virtio",
            bios=QEMU_ARCH[self._arch]["bios"],
            cpu_model=QEMU_ARCH[self._arch]["cpu_model"],
            machine=QEMU_ARCH[self._arch]["machine"],
            qemu_binary=f"qemu-system-{self._arch}",
        )

        # This QMP port is used by the shutdown() method to send the
        # shutdown signal to the QEMU VM instead of killing it.
        qemu.qmp_sockets.append(self._qmp_shutdown_path)

        if self._cli.ssh_port is not None:
            # We only bind to SSH when a port is requested.
            qemu.net_user.append(f"hostfwd=tcp:127.0.0.1:{self._cli.ssh_port}-:22")

        # Pass the credential asking the runner not to shutdown. This is the first credential we add
        # because it has to be passed to the VM even if the following credentials get truncated or
        # similar (as this credential is used for debugging).
        if self._cli.no_shutdown_after_job:
            qemu.smbios_11.append("value=io.systemd.credential:gha-inhibit-shutdown=1")

        jitconfig = CredentialServer("gha-jitconfig-url", self._runner.jitconfig)
        jitconfig.configure_qemu(qemu)

        log("starting the virtual machine")
        self._process = qemu.spawn()

        if self._cli.ssh_port is not None:
            print()
            print("You can connect to the VM with SSH:")
            print()
            print(
                "    "
                "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
                f"-p {self._cli.ssh_port} manage@127.0.0.1"
            )
            print()

        GitHubRunnerStatusWatcher(gh, self._runner.id, self._gha_build_started).start()

        try:
            self._process.wait()
        except KeyboardInterrupt:
            self._shutdown()

        # Shutdown signal was successful, wait for clean shutdown
        try:
            if self._process is not None:
                self._process.wait()
        except KeyboardInterrupt:
            self._kill()

    def request_shutdown(self, reason):
        if self._prevent_external_shutdowns:
            log(f"did not shutdown due to {reason} because a build is running")
        else:
            log(f"shutting down the VM due to {reason}")
            self._shutdown()

    def _shutdown(self):
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
            self._kill()
            return

        log("sent shutdown signal to the VM")

        Timer(
            "graceful-shutdown-timeout", self._kill, GRACEFUL_SHUTDOWN_TIMEOUT
        ).start()

    def _kill(self):
        if self._process is None:
            raise RuntimeError("can't kill a stopped VM")

        self._process.kill()
        self._process = None

        log("killed the virtual machine")

    def cleanup(self):
        shutil.rmtree(str(self._path))

    def _gha_build_started(self):
        self._prevent_external_shutdowns = True
        Timer("vm-timeout", self._shutdown, self._vm_timeout).start()


@dataclass
class QemuInvocation:
    bios: Optional[str]
    cpu_cores: int
    cpu_model: Optional[str]
    drive: str
    machine: str
    memory: int
    qemu_binary: str

    qmp_sockets: List[Path] = field(default_factory=list)
    net_user: List[str] = field(default_factory=list)
    smbios_11: List[str] = field(default_factory=list)

    def spawn(self) -> subprocess.Popen:
        def preexec_fn():
            # Don't forward signals to QEMU
            os.setpgrp()

        cmd = [
            self.qemu_binary,
            # Machine to emulate.
            "-machine",
            self.machine,
            # Reserved RAM for the virtual machine.
            "-m",
            str(self.memory),
            # Allocated cores for the virtual machine.
            "-smp",
            str(self.cpu_cores),
            # Prevent QEMU from showing a graphical console window.
            "-display",
            "none",
            # Mount the VM image as the root drive.
            "-drive",
            self.drive,
            # Enable networking inside the VM.
            "-net",
            "nic,model=virtio",
            # Port forwarding configuration.
            "-net",
            "user" + "".join(f",{param}" for param in self.net_user),
        ]

        if self.cpu_model is not None:
            cmd += ["-cpu", self.cpu_model]

        if self.bios is not None:
            cmd += ["-bios", self.bios]

        for socket in self.qmp_sockets:
            cmd += ["-qmp", f"unix:{socket},server,nowait"]

        for param in self.smbios_11:
            cmd += ["-smbios", f"type=11,{param}"]

        return subprocess.Popen(cmd, preexec_fn=preexec_fn)
