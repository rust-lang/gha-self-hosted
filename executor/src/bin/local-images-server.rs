use anyhow::Error;
use axum::Router;
use axum::body::Body;
use axum::http::StatusCode;
use axum::response::IntoResponse as _;
use axum::routing::get;
use clap::Parser;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs::File as StdFile;
use std::io::{Seek as _, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tempfile::NamedTempFile;
use tokio::fs::File as TokioFile;
use tokio::io::BufReader as TokioBufReader;
use tokio::net::TcpListener;
use tokio_util::io::ReaderStream;
use zstd::Encoder;

#[derive(Debug, Parser)]
struct Cli {
    /// Directory containing the images to serve.
    images_dir: PathBuf,
    /// Port to bind the server to.
    #[clap(long)]
    port: Option<u16>,
}

fn prepare_axum(images: Arc<HashMap<String, Image>>) -> Router<()> {
    use axum::extract::Path;

    // Generate a different fake commit hash every time the local images server starts. This
    // forces the executor to download fresh images even when they are cached.
    let mut fake_commit_raw = [0u8; 32];
    getrandom::fill(&mut fake_commit_raw).unwrap();
    let fake_commit = hex::encode(fake_commit_raw);

    Router::new()
        .route("/", get(async || "local-images-server is running"))
        .route("/latest", get(async move || fake_commit.clone()))
        .route(
            "/images/{commit}/{file}",
            get(async move |Path((_, file)): Path<(String, String)>| -> _ {
                let Some((image, extension)) = file.split_once('.') else {
                    return Err((StatusCode::NOT_FOUND, "missing file extension"));
                };
                match images.get(image) {
                    Some(image) => match extension {
                        "qcow2.zst" => {
                            let reader_stream = ReaderStream::new(TokioBufReader::new(
                                TokioFile::open(&image.compressed.path()).await.unwrap(),
                            ));
                            Ok(Body::from_stream(reader_stream).into_response())
                        }
                        "qcow2.sha256" => Ok(image.hash.clone().into_response()),
                        _ => Err((StatusCode::NOT_FOUND, "unknown file extension")),
                    },
                    None => Err((StatusCode::NOT_FOUND, "image not found")),
                }
            }),
        )
}

fn prepare_images(images_dir: &Path) -> Result<HashMap<String, Image>, Error> {
    let mut found = HashMap::new();
    for entry in images_dir.read_dir()? {
        let path = entry?.path();
        if !path.is_file() {
            continue;
        }
        if path.extension().and_then(|s| s.to_str()) != Some("qcow2") {
            continue;
        }
        let name = path.file_stem().unwrap().to_str().unwrap().to_string();

        eprintln!("==> preparing image {name}...");
        found.insert(name, Image::from_raw(&path)?);
    }
    Ok(found)
}

struct Image {
    compressed: NamedTempFile,
    hash: String,
}

impl Image {
    fn from_raw(path: &Path) -> Result<Self, Error> {
        let mut compressor = Encoder::new(NamedTempFile::new()?, 1)?;
        std::io::copy(&mut StdFile::open(path)?, &mut compressor)?;

        let mut compressed = compressor.finish()?;
        compressed.seek(SeekFrom::Start(0))?;

        let mut hasher = Sha256::new();
        std::io::copy(&mut StdFile::open(path)?, &mut hasher)?;

        Ok(Image {
            compressed,
            hash: hex::encode(hasher.finalize().as_slice()),
        })
    }
}

fn main() -> Result<(), Error> {
    let cli = Cli::parse();
    let images = Arc::new(prepare_images(&cli.images_dir)?);
    let router = prepare_axum(images);

    let port = cli.port.unwrap_or(8000);
    eprintln!("==> serving the local files on port {port}");
    eprintln!("You can use the local image server by adding this flag to the executor:");
    eprintln!("");
    eprintln!("    --images-server http://localhost:{port}");
    eprintln!("");

    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;

    let listener = runtime.block_on(TcpListener::bind(format!("127.0.0.1:{port}")))?;
    runtime.block_on(axum::serve(listener, router).into_future())?;

    Ok(())
}
