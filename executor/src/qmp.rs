use anyhow::{Context, Error, bail};
use serde::de::{DeserializeOwned, IgnoredAny};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::Path;
use tokio::io::{AsyncBufReadExt as _, AsyncWriteExt as _, BufReader};
use tokio::net::UnixStream;
use tokio::net::unix::{OwnedReadHalf, OwnedWriteHalf};

pub(crate) struct QmpClient {
    reader: BufReader<OwnedReadHalf>,
    writer: OwnedWriteHalf,
}

impl QmpClient {
    pub(crate) async fn new(unix_socket: &Path) -> Result<Self, Error> {
        let (reader, writer) = UnixStream::connect(unix_socket).await?.into_split();
        let mut client = QmpClient {
            reader: BufReader::new(reader),
            writer,
        };

        client
            .read_message::<Handshake>()
            .await
            .context("failed to send qmp handshake")?;
        client.request::<()>("qmp_capabilities").await?;

        Ok(client)
    }

    pub(crate) async fn shutdown_vm(&mut self) -> Result<(), Error> {
        self.request::<()>("system_powerdown").await
    }

    async fn request<T: DeserializeOwned>(&mut self, command: &str) -> Result<T, Error> {
        #[derive(Serialize)]
        struct Execute<'a> {
            execute: &'a str,
        }

        let mut bytes = serde_json::to_vec(&Execute { execute: command })?;

        bytes.extend_from_slice(b"\r\n");
        self.writer.write_all(&bytes).await?;

        loop {
            match self.read_message::<Response<T>>().await.map(|r| r.kind) {
                Ok(ResponseKind::Return(value)) => return Ok(value),
                Ok(ResponseKind::Error(error)) => bail!("qmp returned the error {error:?}"),
                Err(err) => bail!("failed to send qmp command {command}: {err}"),
                // Ignore async events sent by QEMU.
                Ok(ResponseKind::Event(_)) => {}
            }
        }
    }

    async fn read_message<T: DeserializeOwned>(&mut self) -> Result<T, Error> {
        // Keep reading until we find a \r\n.
        let mut buf = Vec::new();
        loop {
            self.reader.read_until(b'\n', &mut buf).await?;
            if buf.len() >= 2 && &buf[buf.len() - 2..] == b"\r\n" {
                break;
            }
        }
        // Remove \r\n.
        buf.pop();
        buf.pop();

        Ok(serde_json::from_slice(&buf)?)
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
struct Response<T> {
    #[serde(flatten)]
    kind: ResponseKind<T>,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum ResponseKind<T> {
    Return(T),
    Event(IgnoredAny),
    Error(Value),
}

#[derive(Deserialize)]
struct Handshake {
    #[serde(rename = "QMP")]
    #[expect(dead_code)]
    qmp: Value,
}
