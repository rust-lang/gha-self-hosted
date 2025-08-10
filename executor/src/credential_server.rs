//! Create a single-use HTTP server to inject a credential into the VM.
//!
//! Our self-hosted runners setup relies on systemd credentials to inject parameters and secrets
//! into the running VM. In August 2025 we discovered a bug though: when a credential was too long,
//! systemd would truncate it when loading it. This was a systemd problem, as with `dmidecode -t
//! 11` we could clearly see the credential was passed in the VM untruncated.
//!
//! Some credentials (like just-in-time runner configurations) are fairly long, and given that bug
//! server returning the actual credential, and inject its URL in the VM with a systemd credential.
//!
//! To ensure other processes running on the system cannot easily grab the credential, the server:
//!
//! - Listens to a random, unpredictable port.
//! - Only serves the credential when a long, random authorization token is included in the URL.
//! - Locks itself up after the credential has been retrieved, preventing further retrievals.

use crate::qemu::{QemuInvocation, Smbios11};
use anyhow::Error;
use axum::Router;
use axum::routing::get;
use reqwest::StatusCode;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use tempfile::{NamedTempFile, TempPath};
use tokio::net::TcpListener;

/// IP address of the host machine in QEMU-based VMs, at least under the default settings.
static GUEST_IP: &str = "10.0.2.2";

pub(crate) struct CredentialServer {
    name: String,
    token: String,
    port: u16,
}

impl CredentialServer {
    pub(crate) async fn new(name: &str, credential: &str) -> Result<Self, Error> {
        let mut token_raw = [0u8; 32];
        getrandom::fill(&mut token_raw).unwrap();
        let token = hex::encode(&token_raw);

        let listener = TcpListener::bind("0.0.0.0:0").await?;
        let port = listener.local_addr()?.port();

        let router = prepare_axum(name, &token, credential);
        tokio::spawn(axum::serve(listener, router).into_future());

        Ok(Self {
            name: name.into(),
            token,
            port,
        })
    }

    pub(crate) fn url(&self, host: &str) -> String {
        // QEMU before version 10 had a buffer overflow when reading SMBIOS parameters from a file,
        // as they just forgot to put a zero terminator at the end after reading it [1]. That
        // caused garbage bytes to be appended to the parameter.
        //
        // To work around that, we add a query string to the URL. Query strings are ignored by the
        // server when checking the URL path, so even if QEMU adds garbage at the end of the URL,
        // the garbage will only affect the query string.
        //
        // [1]: https://github.com/qemu/qemu/commit/a7a05f5f6a4085afbede315e749b1c67e78c966b
        //
        format!(
            "http://{host}:{}/{}?avoid-bug-before-qemu-10=1",
            self.port, self.token
        )
    }

    #[must_use]
    pub(crate) fn configure_qemu(
        &self,
        qemu: &mut QemuInvocation,
    ) -> Result<ConfigureQemuGuard, Error> {
        // The URL is saved into a file rather than passing it directly as a CLI argument to avoid
        // it leaking through the command line arguments.
        let url_file = NamedTempFile::new()?;
        std::fs::write(
            &url_file,
            format!("io.systemd.credential:{}={}", self.name, self.url(GUEST_IP)).as_bytes(),
        )?;

        qemu.smbios_11.push(Smbios11::Path(url_file.path().into()));

        Ok(ConfigureQemuGuard {
            _tempfile: url_file.into_temp_path(),
        })
    }
}

pub(crate) struct ConfigureQemuGuard {
    _tempfile: TempPath,
}

fn prepare_axum(name: &str, expected_token: &str, credential: &str) -> Router<()> {
    use axum::extract::Path;

    let name = name.to_string();
    let expected_token = expected_token.to_string();
    let credential = credential.to_string();
    let already_requested = Arc::new(AtomicBool::new(false));

    Router::new()
        .route("/", get(async || "credential server is running"))
        .route(
            "/{token}",
            get(async move |Path(token): Path<String>| -> _ {
                if token != expected_token {
                    eprintln!("warning: attempted to retrieve credential {name} with bad token");
                    (StatusCode::UNAUTHORIZED, "error: invalid token".into())
                } else if !already_requested.fetch_or(true, Ordering::Relaxed) {
                    eprintln!("credential {name} retrieved through the HTTP server");
                    (StatusCode::OK, credential.clone())
                } else {
                    eprintln!("warning: attempted to retrieve credential {name} multiple times");
                    (StatusCode::BAD_REQUEST, "error: already requested".into())
                }
            }),
        )
}
