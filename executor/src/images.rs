use crate::qemu::{ShutdownReason, ShutdownRequester};
use anyhow::{Error, anyhow};
use reqwest::blocking::Client;
use sha2::{Digest as _, Sha256};
use std::fs::{File, remove_dir_all};
use std::io::{BufReader, Read};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::Duration;
use tempfile::TempDir;
use zstd::stream::read::Decoder;

pub struct ImagesRetriever {
    http: Client,
    server_url: String,
    storage_dir: PathBuf,
    latest_commit: OnceLock<String>,

    _tempdir_drop_guard: Option<TempDir>,
}

impl ImagesRetriever {
    pub fn new(server_url: &str, cache_dir: Option<&Path>) -> Result<Self, Error> {
        // If no cache dir is configured, create a temporary one just for this invocation. This
        // avoids having separate code paths for "cached" and "not cached".
        let mut tempdir_drop_guard = None;
        let storage_dir = if let Some(path) = cache_dir {
            std::fs::create_dir_all(path)?;
            path.to_path_buf()
        } else {
            let tempdir = TempDir::new()?;
            let tempdir_path = tempdir.path().to_path_buf();
            tempdir_drop_guard = Some(tempdir);
            tempdir_path
        };

        Ok(Self {
            http: Client::new(),
            server_url: server_url.trim_end_matches('/').to_string(),
            storage_dir,
            latest_commit: OnceLock::new(),
            _tempdir_drop_guard: tempdir_drop_guard,
        })
    }

    pub fn get_image(&self, name: &str) -> Result<PathBuf, Error> {
        let commit = self.latest_commit()?;

        let path = self.storage_dir.join(&commit).join(format!("{name}.qcow2"));
        std::fs::create_dir_all(path.parent().unwrap())?;

        let url = self.url(&format!("images/{commit}/{name}.qcow2.zst"));
        if !path.exists() {
            eprintln!("downloading image {name} (commit: {commit})");

            let resp = self.http.get(&url).send()?.error_for_status()?;
            std::io::copy(&mut Decoder::new(resp)?, &mut File::create(&path)?)?;
        }

        // Check that the image we are running matches the hash the images server expect. This helps
        // detect tampering in the images cache (possibly done by a compromised previous build).
        eprintln!("verifying hash of image {name}");
        let local_hash = sha256_file(&path)?;
        let remote_hash = self.retrieve_text(&format!("images/{commit}/{name}.qcow2.sha256"))?;
        if local_hash != remote_hash {
            return Err(anyhow!("local hash: {local_hash}")
                .context(format!("remote hash: {remote_hash}"))
                .context(format!(
                    "local hash of image {name} differs from the remote one"
                )));
        }

        Ok(path)
    }

    pub fn purge_old_caches(&self) -> Result<(), Error> {
        let latest_commit = self.latest_commit()?;
        for entry in self.storage_dir.read_dir()? {
            let path = entry?.path();
            if path.is_dir() && path.file_name().and_then(|s| s.to_str()) != Some(&latest_commit) {
                eprintln!(
                    "purging outdated image cache for commit {}",
                    path.file_name().unwrap().to_string_lossy()
                );
                remove_dir_all(path)?;
            }
        }
        Ok(())
    }

    fn latest_commit(&self) -> Result<&str, Error> {
        if let Some(value) = self.latest_commit.get() {
            return Ok(value);
        }
        let commit = self.retrieve_text("latest")?;
        Ok(self.latest_commit.get_or_init(move || commit))
    }

    fn retrieve_text(&self, url: &str) -> Result<String, Error> {
        Ok(self
            .http
            .get(self.url(url))
            .send()?
            .error_for_status()?
            .text()?
            .trim()
            .to_string())
    }

    fn url(&self, path: &str) -> String {
        format!("{}/{path}", self.server_url)
    }
}

pub fn watch_for_image_updates(
    retriever: ImagesRetriever,
    shutdown_requester: ShutdownRequester,
) -> Result<(), Error> {
    let latest_commit = retriever.latest_commit()?.to_string();

    eprintln!("started polling the image server to check for image updates");
    std::thread::spawn(move || {
        loop {
            std::thread::sleep(Duration::from_secs(60));
            match retriever.retrieve_text("latest") {
                Ok(new_commit) if new_commit == latest_commit => {}
                Ok(new_commit) => {
                    eprintln!("new images with commit {new_commit} are available");
                    shutdown_requester.request_shutdown(ShutdownReason::NewImages);
                }
                Err(err) => {
                    eprintln!("warning: failed to fetch the latest image commit: {err}");
                }
            }
        }
    });
    Ok(())
}

fn sha256_file(file: &Path) -> Result<String, Error> {
    let mut file = BufReader::new(File::open(file)?);
    let mut hasher = Sha256::new();

    let mut buf = vec![0; 1024 * 1024 * 4];
    loop {
        match file.read(&mut buf)? {
            0 => break,
            len => hasher.update(&buf[..len]),
        }
    }

    Ok(hex::encode(hasher.finalize().as_slice()))
}
