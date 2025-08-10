use anyhow::{Context, Error};
use clap::Parser;
use executor::InstanceSpec;
use executor::github::GitHub;
use executor::images::{ImagesRetriever, watch_for_image_updates};
use executor::qemu::{ShutdownRequester, VmOptions, start_vm};
use std::path::PathBuf;

#[derive(Debug, Parser)]
struct Cli {
    /// Path to the JSON instance specification.
    instance_spec: PathBuf,
    /// Client ID of the GitHub App used to authenticate.
    #[clap(long)]
    github_client_id: String,
    /// Path to the private key of the GitHub APp used to authenticate.
    #[clap(long)]
    github_private_key: PathBuf,
    /// Name of the GitHub organization to register the runner into.
    #[clap(long)]
    github_org: String,
    /// ID of the runner group to register the runner into.
    #[clap(long)]
    runner_group_id: u64,
    /// HTTP server to retrieve the images from.
    #[clap(
        long,
        default_value = "https://gha-self-hosted-images.infra.rust-lang.org"
    )]
    images_server: String,
    /// Directory to store cached images in.
    #[clap(long)]
    images_cache_dir: Option<PathBuf>,
    /// Ask the VM not to shutdown after completing a GitHub Actions job.
    #[clap(long)]
    no_shutdown_after_job: bool,
    /// Port to bind the SSH server to. The SSH server will not be bound if this is omitted.
    #[clap(long)]
    ssh_port: Option<u16>,
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    let cli = Cli::parse();
    let shutdown_requester = ShutdownRequester::new();

    let spec: InstanceSpec = serde_json::from_slice(&std::fs::read(&cli.instance_spec)?)
        .context("failed ot read the instance spec")?;

    let images = ImagesRetriever::new(&cli.images_server, cli.images_cache_dir.as_deref())
        .context("failed to create the images retriever")?;
    images
        .purge_old_caches()
        .context("failed to purge old cached images")?;
    let image = images
        .get_image(&spec.image)
        .context("failed to download the requested image")?;
    watch_for_image_updates(images, shutdown_requester.clone())?;

    let github = GitHub::new(
        &cli.github_client_id,
        &cli.github_private_key,
        &cli.github_org,
    )?;

    let runner = github
        .create_runner(
            &format!("{}-{}", spec.label, {
                let mut buf = [0; 6];
                getrandom::fill(&mut buf)?;
                buf.iter().map(|b| format!("{b:02x}")).collect::<String>()
            }),
            cli.runner_group_id,
            &[&spec.label],
        )
        .await
        .context("failed to create github runner")?;

    start_vm(
        &github,
        &spec,
        &image,
        &runner,
        shutdown_requester,
        VmOptions {
            ssh_port: cli.ssh_port,
            shutdown_after_job: !cli.no_shutdown_after_job,
        },
    )
    .await
    .context("failed to start VM")?;

    Ok(())
}
