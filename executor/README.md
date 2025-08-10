# Ephemeral VMs executor

This directory contains the Python script used to spawn ephemeral VMs for the
Rust CI. The script starts VMs using QEMU, and is designed to work with VM
images produced by this repository. This README only documents how an user
should use the script: technical documentation on how the script works is
present as comments inside the script itself.

## Command-line interface

The `./run.py` script accepts the following command-line arguments:

* **`INSTANCE_SPEC`** _(required)_: the JSON file describing the instance. See
  ["Instance specifications"](#instance-specifications) for more information.
* **`--github-client-id <id>`** _(required)_: the Client ID of the GitHub App.
* **`--github-private-key <path>`** _(required)_: the private key of the GitHub App.
* **`--github-org`** _(required)_: the GitHub org to register the runner into.
* **`--runner-group-id`** _(required)_: the ID of the [runner
  group][runner-group] to register the runner into.
* **`--images-server`**: the URL of the HTTP server hosting the VM images. By
  default this points to [our production server][images-prod]. The flag allows
  you to override it when testing things locally: see ["Testing local
  images"](#testing-local-images) for more information.
* **`--images-cache-dir`**: the directory to cache downloaded VM images in. If
  it's not provided, no images will be cached. Note that a cache must not be
  accessed by multiple instances of the executor concurrently.
* **`--no-shutdown-after-job`**: ask the VM to not shut down after executing a
  job. See ["Troubleshooting the VM immediately
  exiting"](#troubleshooting-the-vm-immediately-exiting).
* **`--ssh-port`**: host port to bind the VM's SSH port into. If it's not
  provided, the VM's SSH server will not be accessible from the host.

## Instance specifications

An image specification is a JSON file describing what the VM should look like.
It must contain a JSON object with the following keys:

* **label**: the GitHub Actions label assigned to the runner. You will need to
  use the label in the `runs-on` GitHub Actions YAML key to assign a job to a
  runner. For example, a label of "foo" will require you to do `runs-on: foo` in
  the YAML.
* **image**: the name of the image to use for the VM. It must correspond with
  [one of the images available on the image server][ubuntu-readme].
* **arch**: the architecture of the VM. It currently supports either `x86_64` or
  `aarch64`.
* **cpu-cores**: the number of CPU cores to allocate to the VM.
* **ram**: the amount of RAM to allocate to the VM. Use the `G` suffix to
  specify the gigabytes unit.
* **root-disk**: the amount of disk space to allocate to the VM's root disk. Use
  the `G` suffix to specify the gigabytes unit.
* **timeout-seconds**: maximum amount of time (in seconds) a job is allowed to
  run before the VM is killed. 

## Starting a sample VM

To start a sample VM, write this image specification to a file (let's assume
`instance.json`):

```json
{
    "label": "sample",
    "image": "ubuntu-x86_64",
    "arch": "x86_64",
    "cpu-cores": 4,
    "ram": "4G",
    "root-disk": "80G",
    "timeout-seconds": 3600
}
```

Then create a GitHub App with the permission to manage self-hosted runners for
an organization, create a private key pair for it, and install it in an
organization you control. Finally, in the same organization create a runner
group and write down its ID (you can find it in the URL).

Once all of this is done, you can start a VM:

```bash
./run.py instance.json \
  --github-client-id 12345 \
  --github-private-key key.pem \
  --github-org emilyorg \
  --runner-group-id 12345
```

## Testing local images

By default, the executor downloads images from our production infrastructure,
but it's possible to override that and use locally built images. To do so, you
can execute the `local-images-server` binary, which serves all images present in
a directory in the format the executor expects:

```bash
cargo run --bin local-images-server ../images/ubuntu/build
```

The binary will print the command line flags to pass to the executor. Note that
you will need to restart the `local-images-server` if you change any image, as
it does not implement auto-reloading.

## Runtime behavior of the executor

The executor script will use the GitHub credentials to generate a [just-in-time
registration token][jit] and pass it to the VM in the `gha-jitconfig` [systemd
credential]. It will then start the VM with QEMU, and assume the image will
start a GitHub Actions runner with the token passed into it.

The executor will periodically poll the GitHub API to determine when the runner
starts executing a job. When that happens, it will start a timer (as defined in
the `timeout-seconds` key of the [instance
specification](#instance-specifications)) and forcibly shut down the machine
when the timer expires. This prevents a compromised VM from running forever.

When the executor receives a SIGTERM, it will check whether the VM is currently
executing a job. The executor will gracefully shut down the VM only if it's not
running any job, to avoid terminating it.

When the executor receives a SIGINT (Ctrl+C), it will gracefully shutdown the
VM, regardless of whether it's executing a job. Sending a second SIGINT will
forcefully kill the VM and exit immediately.

The executor will also periodically check whether a new version of the image is
available on the images server. If a new one is available, and there is no job
currently running on the VM, the executor will gracefully shut down the VM and
exit. It's then the responsibility of the init system to restart the executor,
which will pick the new image.

## Troubleshooting the VM immediately exiting

The [Ubuntu images][ubuntu-readme] are configured to shut down as soon as the
GitHub Actions runner exits. This can result in the VM shutting down as soon as
it boots when the runner fails to start, preventing you from logging into the VM
and debugging the failure.

When that happens, you should pass the `--no-shutdown-after-job` CLI flag to
`run.py`. Doing so will set the `gha-inhibit-shutdown` [systemd credential],
which tells the image to not shutdown after the GitHub Actions runner exits.

[runner-group]: https://docs.github.com/en/enterprise-cloud@latest/actions/how-tos/hosting-your-own-runners/managing-self-hosted-runners/managing-access-to-self-hosted-runners-using-groups
[images-prod]: https://gha-self-hosted-images.infra.rust-lang.org
[ubuntu-readme]: ../images/ubuntu/README.md
[jit]: https://docs.github.com/en/enterprise-cloud@latest/actions/how-tos/security-for-github-actions/security-guides/security-hardening-for-github-actions#using-just-in-time-runners\
[systemd credential]: https://systemd.io/CREDENTIALS/
