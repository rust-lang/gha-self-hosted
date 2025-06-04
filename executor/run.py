#!/usr/bin/env -S uv run

from typing import List
from executor.github import GitHub
from executor.qemu import VM
import argparse
import json
import signal


running_vms: List[VM] = []


def sigterm_received(sig, _frame):
    for vm in running_vms:
        vm.request_shutdown("SIGTERM signal")


def run(cli):
    signal.signal(signal.SIGTERM, sigterm_received)

    with open(cli.instance_spec) as f:
        instance = json.load(f)

    gh = GitHub(cli)
    runner = gh.create_runner(cli, instance)

    vm = VM(cli, instance, runner)
    running_vms.append(vm)

    vm.run(gh)
    vm.cleanup()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("instance_spec")

    parser.add_argument(
        "--github-client-id",
        help="Client ID of the GitHub App used to authenticate",
        required=True,
    )
    parser.add_argument(
        "--github-private-key",
        help="Path to the private key of the GitHub App used to authenticate",
        required=True,
    )
    parser.add_argument(
        "--github-org",
        help="GitHub org to register the runner into",
        required=True,
    )

    parser.add_argument(
        "--runner-group-id",
        help="ID of the runner group to register the runner into",
        type=int,
        required=True,
    )

    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
