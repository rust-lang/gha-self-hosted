# Ubuntu VM images

> [!CAUTION]
>
> These images are strictly meant to be used in Rust's self-hosted CI. The Rust
> infrastructure team provides no support for third parties attempting to use
> the images, nor any stability guarantee. If you want to use these images, we
> recommend forking this repository.

This directory contains the source code used to build the Ubuntu images for
Rust's self-hosted CI. The images are built with [Packer].

The images are based on Ubuntu 20.04, and are prepared for x86_64 and AArch64.

## Accessing the images built by CI

Our production infrastructure relies on VM images built by CI. These images are
uploaded to [gha-self-hosted-images.infra.rust-lang.org] when a PR is being
merged to `main` with the merge queue.

In order to download any image, you must first retrieve the latest commit hash,
which is available at the [`/latest`][cdn-latest] URL. Then, access the relevant
URL depending on the image you want, replacing `${commit}` with the commit hash
you previously retrieved:

| Image name       | Architecture | Compression | URL template                                 |
| ---------------- | ------------ | ----------- | -------------------------------------------- |
| `ubuntu-x86_64`  | x86_64       | zstandard   | `/images/${commit}/ubuntu-x86_64.qcow2.zst`  |
| `ubuntu-aarch64` | AArch64      | zstandard   | `/images/${commit}/ubuntu-aarch64.qcow2.zst` |

### Rolling back to a previously built image

Merging changes that break our self-hosted runners might happen, and in those
cases the easiest way to roll back is to create a new PR reverting the
problematic changes.

If that is not quick enough, you can ask a member of infra-admins to manually
override the `latest` object inside of the `rust-gha-self-hosted-images` S3
bucket to point to the known good commit. No CDN invalidation is needed, as that
file intentionally has a short TTL.

## Building the image locally

To build the images you should have the latest version of [Packer] and QEMU
installed on your system. Running `make` will build the image for your host
architecture. If you want to build specific images, the following commands are
available:

| Architecture | Native build        | Emulated build      | Output path                  |
| ------------ | ------------------- | ------------------- | ---------------------------- |
| x86_64       | `make x86_64-host`  | `make x86_64-emul`  | `build/ubuntu-x86_64.qcow2`  |
| AArch64      | `make aarch64-host` | `make aarch64-emul` | `build/ubuntu-aarch64.qcow2` |

## Build process overview

The build process for the image is fully driven by Packer, configured in
`image.pkr.hcl`. The `Makefile` entry point is only responsible to download some
pre-requisites, pass the correct variables to Packer, and move files to their
correct location. Once Packer downloads the base Ubuntu image, it boots it with
QEMU (either natively or emulated depending on the architecture) and configures
it in two stages.

The first stage is performed by [cloud-init]: Packer spins up a local HTTP
server with the content of the `cloud-init/` directory, and points cloud-init to
it. cloud-init is responsible to create the user Packer will SSH into, allowing
the second stage to begin.

The second stage is performed by Packer SSH'ing into the VM. It copies the
`files/` directory (containing support files needed by our scripts) into the VM
(at `/tmp/packer-files`), and then calls each of the scripts defined in the
`scripts/` directory. These scripts are actually responsible for most of the VM
configuration.

> [!NOTE]
>
> Adding a script to the `scripts/` directory is **not** enough for it to be
> executed. You will also need to explicitly list it in `image.pkr.hcl`.

## Image runtime requirements

The image requires the `gha-jitconfig` [systemd credential] to be set by the
hypervisor, containing the encoded just-in-time runner configuration retrieved
from the GitHub API ([repositories][jit-repo], [organizations][jit-org], or
[enterprises][jit-enterprise]). On QEMU, you can set it with this flag:

```
-smbios type=11,value=io.systemd.credential:gha-jitconfig=CONFIG_GOES_HERE
```

## Image runtime behavior

Each time it boots, the VM will:

* Resize the disk image to use all allocated space (implemented in
  `files/regenerate-ssh-host-keys.sh`).
* Regenerate the SSH host keys, to avoid reusing the keys baked into the image
  (implemented in `files/regenerate-ssh-host-keys.sh`).
* Mount the virtual block device (see "Image runtime requirements"), load the
  runner configuration from it, and start the runner (implemented in
  `files/start-gha-runner.py`).

The GitHub Actions runner will then listen for jobs, and execute a single job,
once the job finishes, the runner will shut down the VM.

The VM provides passwordless sudo access via SSH through the `manage` user
(password: `password`).

[Packer]: https://developer.hashicorp.com/packer
[cloud-init]: https://cloud-init.io/
[gha-self-hosted-images.infra.rust-lang.org]: https://gha-self-hosted-images.infra.rust-lang.org
[cdn-latest]: https://gha-self-hosted-images.infra.rust-lang.org/latest
[systemd credential]: https://systemd.io/CREDENTIALS/
[jit-repo]: https://docs.github.com/en/enterprise-cloud@latest/rest/actions/self-hosted-runners?versionId=enterprise-cloud%40latest&apiVersion=2022-11-28#create-configuration-for-a-just-in-time-runner-for-a-repository
[jit-org]: https://docs.github.com/en/enterprise-cloud@latest/rest/actions/self-hosted-runners?versionId=enterprise-cloud%40latest&apiVersion=2022-11-28#create-configuration-for-a-just-in-time-runner-for-an-organization
[jit-enterprise]: https://docs.github.com/en/enterprise-cloud@latest/rest/actions/self-hosted-runners?versionId=enterprise-cloud%40latest&apiVersion=2022-11-28#create-configuration-for-a-just-in-time-runner-for-an-enterprise
