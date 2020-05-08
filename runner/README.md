# Ephemeral VMs runner

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
* **timeout-seconds**: number of seconds after the VM is shut down.
* **config**: arbitrary object containing instance-specific configuration. This
  data will be available inside the VM, and can be used by the base image to
  configure itself. Documentation on how to access it inside the VM is
  available below.

An example of such file is:

```json
[
    {
        "name": "vm-1",
        "image": "../images/ubuntu/build/ubuntu-amd64.qcow2",
        "timeout-seconds": 14400,
        "config": {
            "repo": "rust-lang-ci/rust",
            "token": "FOOBAR"
        }
    },
    {
        "name": "vm-1",
        "image": "../images/ubuntu/build/ubuntu-amd64.qcow2",
        "timeout-seconds": 14400,
        "config": {
            "repo": "rust-lang-ci/rust",
            "token": "FOOBAR"
        }
    }
]
```

## Starting an instance

To start an instance, run the following command inside the directory containing
the `instances.json` file:

```
./run.py IMAGE-NAME
```

The command will start an ephemeral copy of the VM and then delete it once the
VM shuts down.

## Reading the instance configuration inside the VM

The script will mount a virtual CD-ROM inside each virtual machine, containing
a file called `instance.json`. The file will contain a JSON document with a
copy of the `name` and `config` keys from the host's `instances.json`.
