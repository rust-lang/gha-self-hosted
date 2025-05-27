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

## Building the image locally

To build the images you should have the latest version of [Packer] and QEMU
installed on your system. Running `make` will build the image for your host
architecture. If you want to build specific images, the following commands are
available:

| Architecture | Native build        | Emulated build      | Output path                  |
| ------------ | ------------------- | ------------------- | ---------------------------- |
| x86_64       | `make x86_64-host ` | `make x86_64-emul`  | `build/ubuntu-x86_64.qcow2`  |
| AArch64      | `make aarch64-host` | `make aarch64-emul` | `build/ubuntu-aarch64.qcow2` |

## Build process overview

The build process for the image is fully driven by Packer, configured in
`image.pkr.hcl`. The `Makefile` entry point is only responsible to download some
pre-requisites and pass the correct variables to Packer.

Once Packer downloads the base Ubuntu image, it boots it with QEMU (either
natively or emulated depending on the architecture) and configures it in two
stages.

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

The image is configured through a virtual CD-ROM that must be mounted in the
virtual machine with the `instance-configuration` disk label. The CD-ROM must
contain an `instance.json` file with the following schema:

* `name`: name of the runner.
* `config`:
  * `repo`: GitHub repository to register the runner into.
  * `token`: GitHub Actions registration token.
  * `whitelisted-event` *(optional)*: value that will be set in the
    `RUST_WHITELISTED_EVENT_NAME` environment variable.

## Image runtime behavior

Each time it boots, the VM will:

* Resize the disk image to use all allocated space (implemented in
  `files/regenerate-ssh-host-keys.sh`).
* Regenerate the SSH host keys, to avoid reusing the keys baked into the image
  (implemented in `files/regenerate-ssh-host-keys.sh`).
* Mount the virtual CD-ROM (see "Image runtime requirements"), load the runner
  configuration from it, eject the CD-ROM, and start the runner (implemented in
  `files/start-gha-runner.py`).

The GitHub Actions runner will then listen for jobs, and execute a single job,
once the job finishes, the runner will shut down the VM.

The VM provides passwordless sudo access via SSH through the `manage` user
(password: `password`).

[Packer]: https://developer.hashicorp.com/packer
[cloud-init]: https://cloud-init.io/
