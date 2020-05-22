# Ubuntu VM images

This directory contains the source code used to build the VM images used in
Rust's self-hosted CI. The images are specific to our environment and use [a
custom fork of the GitHub Actions runner][rust-lang/gha-runner]: it's not
recommended to use them outside our environment.

If you're on a x86_64 or AArch64 machine you can build the image for your host
architecture by running:

```
make
```

You can also explicitly build the image for a single architecture:

```
make x86_64-host
make aarch64-host

make x86_64-emul
make aarch64-emul
```

> **Warning**: building emulated AArch64 images is not currently working.

The resulting images will be located at:

* Ubuntu 20.04 LTS x86_64: `build/x86_64/rootfs.qcow2`
* Ubuntu 20.04 LTS AArch64: `build/aarch64/rootfs.qcow2`

## Image configuration

The image accepts the following configuration keys passed by the executor
script in this repository:

* `repo`: the GitHub repository to register the runner in.
* `token`: GitHub Actions installation token for the agent.
* `whitelisted-event` *(optional)*: value of the `RUST_WHITELISTED_EVENT_NAME`
  environment variable.

During each boot, the VM will:

* Regenerate the SSH host keys instead of using the ones baked in the VM image.
* Resize the root partition to take all available space in the disk.
* Read the configuration from the CD-ROM and start the GitHub Actions runner.

SSH access is available via the `manage` user, with the password: `password`.

## Directory structure

This directory contains the following files and directories:

* `ubuntu.json`: the Packer manifest for the image, which contains
  the list of scripts to call during the build.
* `scripts/`: bash scripts included by the manifest: Packer will run them in the
  build VM.
* `files/`: files needed by the scripts: Packer will copy them in
  `/tmp/packer-files` inside the build VM.
* `cloud-init/`: [cloud-init] configuration, used to setup authentication in the
  build VMs.

[rust-lang/gha-runner]: https://github.com/rust-lang/gha-runner
[Packer]: https://www.packer.io/
[cloud-init]: https://cloud-init.io/
