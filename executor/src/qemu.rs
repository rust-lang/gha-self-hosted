use crate::credential_server::CredentialServer;
use crate::github::{CreatedRunner, GitHub};
use crate::qmp::QmpClient;
use crate::{InstanceArch, InstanceSpec, Size};
use anyhow::{Error, bail};
use std::ffi::{OsStr, OsString};
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::pin::Pin;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tempfile::NamedTempFile;
use tokio::process::Command as TokioCommand;
use tokio::signal::unix::{SignalKind, signal};
use tokio::sync::mpsc;
use tokio::time::sleep;

pub async fn start_vm(
    github: &GitHub,
    spec: &InstanceSpec,
    image: &Path,
    runner: &CreatedRunner,
    shutdown_request: ShutdownRequester,
    opts: VmOptions,
) -> Result<(), Error> {
    let root = prepare_root_filesystem(spec, image)?;

    let mut qemu = QemuInvocation {
        arch: spec.arch,
        cpu_cores: spec.cpu_cores,
        drive_path: root.path().into(),
        memory: spec.ram,
        qmp_sockets: Vec::new(),
        net_user: Vec::new(),
        smbios_11: Vec::new(),
    };

    // QMP lets us control QEMU. We need this to gracefully shutdown the VM.
    let qmp_sock = NamedTempFile::new()?;
    qemu.qmp_sockets.push(qmp_sock.path().into());

    if let Some(port) = opts.ssh_port {
        // We only bind to SSH when a port is requested.
        qemu.net_user
            .push(format!("hostfwd=tcp:127.0.0.1:{port}-:22"));
    }

    // Pass the credential asking the runner not to shutdown. This is the first credential we add
    // because it has to be passed to the VM even if the following credentials get truncated or
    // similar (as this credential is used for debugging).
    if !opts.shutdown_after_job {
        qemu.smbios_11.push(Smbios11::Value(
            "io.systemd.credential:gha-inhibit-shutdown=1".into(),
        ));
    }

    let jitconfig = CredentialServer::new("gha-jitconfig-url", &runner.jitconfig).await?;
    let _guard = jitconfig.configure_qemu(&mut qemu)?;

    eprintln!("starting the VM");
    let mut child = TokioCommand::from(qemu.into_command()).spawn()?;

    if let Some(port) = opts.ssh_port {
        eprintln!();
        eprintln!("you can now connect to the VM with SSH:");
        eprintln!();
        eprintln!(
            "    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p {} \
             manage@127.0.0.1",
            port
        );
        eprintln!();
    }

    // When a SIGTERM is received, request a graceful shutdown instead of killing the process. This
    // allows us to reboot the host machine without killing any incoming job, as shutdown requests
    // are ignored when a job is running.
    {
        let shutdown_request = shutdown_request.clone();
        let mut sigterm = signal(SignalKind::terminate())?;
        tokio::spawn(async move {
            loop {
                sigterm.recv().await;
                shutdown_request.request_shutdown(ShutdownReason::SigTerm);
            }
        });
    }

    // Inhibit shutdown requests once a job starts.
    {
        let runner_id = runner.id;
        let github = github.clone();
        let shutdown_request = shutdown_request.clone();
        tokio::spawn(async move {
            github
                .run_after_build_started(runner_id, move || {
                    shutdown_request
                        .inner
                        .allowed
                        .store(false, Ordering::Relaxed);
                })
                .await;
        });
    }

    // When a graceful shutdown is started, this future will be replaced from a future that
    // never returns to a sleep. The loop below will kill the VM when this future resolves.
    let mut graceful_shutdown_timeout: Pin<Box<dyn Future<Output = ()>>> =
        Box::pin(std::future::pending());
    let mut graceful_shutdown_started = false;

    let mut shutdown_request = shutdown_request
        .inner
        .receiver
        .lock()
        .unwrap()
        .take()
        .expect("another VM already took the receiver");

    let mut first_ctrlc = true;
    loop {
        // Lint is #[expect]ed because there might be more reasons to do multiple iterations of
        // this loop than just graceful shutdowns.
        #[expect(unused_assignments)]
        let mut do_graceful_shutdown = false;

        tokio::select! {
            _ = child.wait() => return Ok::<_, Error>(()),

            reason = shutdown_request.recv() => {
                eprintln!("graceful shutting down due to {}", reason.unwrap().description());
                do_graceful_shutdown = true;
            }

            _ = &mut graceful_shutdown_timeout => {
                eprintln!("graceful shutdown timeout reached, killing the VM");
                child.kill().await?;
                return Ok(());
            }

            _ = tokio::signal::ctrl_c() => {
                if first_ctrlc {
                    first_ctrlc = false;

                    eprintln!("pressed Ctrl+C, gracefully shutting down (press again to kill)");
                    do_graceful_shutdown = true;
                } else {
                    eprintln!("pressed Ctrl+C again, killing the VM");
                    child.kill().await?;
                    return Ok(());
                }
            }
        }

        if do_graceful_shutdown && !graceful_shutdown_started {
            match send_graceful_shutdown(&qmp_sock.path()).await {
                Ok(()) => {
                    graceful_shutdown_started = true;
                    graceful_shutdown_timeout = Box::pin(sleep(Duration::from_secs(60)));
                }
                Err(err) => {
                    eprintln!("graceful shutdown failed: {err}, killing the VM");
                    child.kill().await?;
                    return Ok(());
                }
            }
        }
    }
}

async fn send_graceful_shutdown(qmp_socket: &Path) -> Result<(), Error> {
    let mut qmp = QmpClient::new(qmp_socket).await?;
    qmp.shutdown_vm().await?;
    Ok(())
}

pub struct VmOptions {
    pub ssh_port: Option<u16>,
    pub shutdown_after_job: bool,
}

fn prepare_root_filesystem(spec: &InstanceSpec, image: &Path) -> Result<NamedTempFile, Error> {
    let dest = NamedTempFile::new()?;

    eprintln!("creating the root filesystem image");
    let status = Command::new("qemu-img")
        .arg("create")
        // Path of the base image.
        .args([OsStr::new("-b"), image.as_os_str()])
        // Use a Copy on Write filesystem, to avoid having to copy the whole base image every time
        // we start the VM.
        .args(["-f", "qcow2"])
        // Explicitly set the format of the backing image file.
        .args(["-F", "qcow2"])
        // Path to the destination image.
        .arg(dest.path())
        // Size of the disk we are creating.
        .arg(spec.root_disk.to_string())
        // We don't care about the output of the command (we do about errors on stderr).
        .stdout(Stdio::null())
        .status()?;
    if !status.success() {
        bail!("attempting to create the root disk exited with {status}");
    }

    Ok(dest)
}

#[derive(Clone)]
pub struct ShutdownRequester {
    inner: Arc<ShutdownRequesterInner>,
}

impl ShutdownRequester {
    pub fn new() -> Self {
        let (sender, receiver) = mpsc::unbounded_channel();
        Self {
            inner: Arc::new(ShutdownRequesterInner {
                allowed: AtomicBool::new(true),
                sender,
                receiver: Mutex::new(Some(receiver)),
            }),
        }
    }

    pub fn request_shutdown(&self, reason: ShutdownReason) {
        if !self.inner.allowed.load(Ordering::Relaxed) {
            eprintln!(
                "shutdown requested due to {}, but a job is currently running, skipping it",
                reason.description()
            );
            return;
        }
        self.inner
            .sender
            .send(reason)
            .expect("failed to send the shutdown request");
    }
}

struct ShutdownRequesterInner {
    allowed: AtomicBool,
    sender: mpsc::UnboundedSender<ShutdownReason>,
    receiver: Mutex<Option<mpsc::UnboundedReceiver<ShutdownReason>>>,
}

pub enum ShutdownReason {
    NewImages,
    SigTerm,
}

impl ShutdownReason {
    fn description(&self) -> &str {
        match self {
            ShutdownReason::NewImages => "new images being available",
            ShutdownReason::SigTerm => "SIGTERM signal",
        }
    }
}

pub(crate) struct QemuInvocation {
    pub(crate) arch: InstanceArch,
    pub(crate) cpu_cores: u32,
    pub(crate) drive_path: PathBuf,
    pub(crate) memory: Size,

    pub(crate) qmp_sockets: Vec<PathBuf>,
    pub(crate) net_user: Vec<String>,
    pub(crate) smbios_11: Vec<Smbios11>,
}

impl QemuInvocation {
    fn into_command(self) -> Command {
        let mut cmd = Command::new(match self.arch {
            InstanceArch::X86_64 => "qemu-system-x86_64",
            InstanceArch::Aarch64 => "qemu-system-aarch64",
        });
        cmd
            // Machine to emulate
            .args([
                "-machine",
                match self.arch {
                    InstanceArch::X86_64 => "pc,accel=kvm",
                    InstanceArch::Aarch64 => "virt,gic_version=3,accel=kvm",
                },
            ])
            // Allocated RAM
            .args(["-m", &self.memory.to_string()])
            // Allocated virtual cores
            .args(["-smp", &self.cpu_cores.to_string()])
            // Prevent QEMU from showing a graphical console window.
            .args(["-display", "none"])
            // Mount the VM image inside the VM
            .args([
                concat_os_string(&[&"-drive"]),
                concat_os_string(&[&"file=", &self.drive_path, &",media=disk,if=virtio"]),
            ])
            // Enable networking
            .args(["-net", "nic,model=virtio"])
            // Port forwarding configuration
            .args([
                "-net".to_string(),
                format!(
                    "user{}",
                    self.net_user
                        .iter()
                        .map(|p| format!(",{p}"))
                        .collect::<String>()
                ),
            ]);

        match self.arch {
            InstanceArch::X86_64 => {}
            InstanceArch::Aarch64 => {
                cmd.args(["-cpu", "host"])
                    .args(&["-bios", "/usr/share/qemu-efi-aarch64/QEMU_EFI.fd"]);
            }
        }

        for socket in &self.qmp_sockets {
            cmd.arg("-qmp")
                .arg(concat_os_string(&[&"unix:", socket, &",server,nowait"]));
        }
        for param in &self.smbios_11 {
            match param {
                Smbios11::Path(path) => cmd
                    .arg("-smbios")
                    .arg(concat_os_string(&[&"type=11,path=", path])),
                Smbios11::Value(value) => cmd.arg("-smbios").arg(format!("type=11,value={value}")),
            };
        }

        // Don't propagate signals into the VM.
        cmd.process_group(0);

        cmd
    }
}

pub(crate) enum Smbios11 {
    Path(PathBuf),
    Value(String),
}

fn concat_os_string(components: &[&dyn AsRef<OsStr>]) -> OsString {
    let mut result = OsString::new();
    for component in components {
        result.push(component);
    }
    result
}
