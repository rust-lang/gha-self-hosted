# Ephemeral VMs executor

This directory contains the Python script used to spawn ephemeral VMs for the
Rust CI. The script starts VMs using QEMU, and is designed to work with VM
images produced by this repository.

This README only documents how an user should use the script: technical
documentation on how the script works is present as comments inside the script
itself.

## Configuring the instances

The script reads the `instances.json` file in the current working directory at
startup, loading the definition of each supported virtual machine. The file
contains a list of instance objects, each with the following keypairs:

* **name**: name of the instance.
* **image**: path to the QCOW2 file of the base image.
* **cpu-cores**: amount of CPU cores to allocate to the VM.
* **ram**: amount of RAM to allocate to the VM.
* **root-disk**: amount of disk space to allocate to the VM.
* **timeout-seconds**: number of seconds after the VM is shut down.
* **ssh-port**: port number to assign to the VM's SSH server. Documentation on
  how to log into the VM is available below.
* **config**: arbitrary object containing instance-specific configuration. This
  data will be available inside the VM, and can be used by the base image to
  configure itself. A configuration pre-processor is available, allowing to
  fetch some configuration values at startup time. Documentation on how to
  access the configuration inside the VM is available below.

An example of such file is:

```json
[
    {
        "name": "vm-1",
        "image": "../images/ubuntu/build/ubuntu-amd64.qcow2",
        "cpu-cores": 4,
        "ram": "4G",
        "root-disk": "80G",
        "timeout-seconds": 14400,
        "ssh-port": 2201,
        "config": {
            "repo": "rust-lang-ci/rust",
            "token": "${{ gha-install-token:rust-lang-ci/rust }}",
            "whitelisted-event": "push"
        }
    },
    {
        "name": "vm-1",
        "image": "../images/ubuntu/build/ubuntu-amd64.qcow2",
        "cpu-cores": 2,
        "ram": "2G",
        "root-disk": "20G",
        "timeout-seconds": 14400,
        "ssh-port": 2202,
        "config": {
            "repo": "rust-lang-ci/rust",
            "token": "${{ gha-install-token:rust-lang-ci/rust }}",
            "whitelisted-event": "push"
        }
    }
]
```

## Configuration pre-processor

The script allows to fetch some configuration values dynamically right before
the virtual machine is started. A limited number of functions is available.

### Fetching the GHA installation token

To fetch the GitHub Actions runner installation token for a repository, you can
set the following value in the config:

```
${{ gha-install-token:ORGANIZATION/REPOSITORY }}
```

When this parameter is present, the script will call the GitHub API to fetch a
new installation token. For that to work the `GITHUB_TOKEN` environment
variable needs to be set, containing a valid GitHub API token.

## Starting an instance

To start an instance, run the following command inside the directory containing
the `instances.json` file:

```
./run.py IMAGE-NAME
```

The command will start an ephemeral copy of the VM and then delete it once the
VM shuts down.

## Logging into the instance

The script allows you to connect to the spawned VM through SSH, through the
`ssh-port` defined in the instance configuration. You can connect by running:

```
ssh -p <ssh-port> manage@localhost
```

The password for the `manage` user in our VMs is `password`. The SSH server
takes a while to start up, so you might have to wait before being able to log
in. Keep in mind that our VM images regenerate the SSH host keys every time
they boot, so you'll likely get host key mismatch errors when you try to
connect.

## Reading the instance configuration inside the VM

The script will mount a virtual CD-ROM inside each virtual machine, containing
a file called `instance.json`. The file will contain a JSON document with a
copy of the `name` and `config` keys from the host's `instances.json`.

It's possible for the VM to eject the virtual CD-ROM once it's done reading its
contents, for example to prevent future untrusted processes inside the VM from
reading it. Once the CD-ROM tray is opened, the script will automatically
remove the CD-ROM.
