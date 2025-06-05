#!/usr/bin/env -S uv run

from pathlib import Path
from typing import List
from executor.github import GitHub
from executor.images import ImageUpdateWatcher, ImagesRetriever
from executor.qemu import VM
import argparse
import json
import signal


running_vms: List[VM] = []


def sigterm_received(_sig, _frame):
    for vm in running_vms:
        vm.request_shutdown("SIGTERM signal")


def new_image():
    for vm in running_vms:
        vm.request_shutdown("new image available")


def run(cli):
    signal.signal(signal.SIGTERM, sigterm_received)

    with open(cli.instance_spec) as f:
        instance = json.load(f)

    images = ImagesRetriever(cli)
    image = images.get_image(instance["image"])
    ImageUpdateWatcher(images, new_image).start()

    gh = GitHub(cli)
    runner = gh.create_runner(cli, instance)

    vm = VM(cli, instance, image, runner)
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

    parser.add_argument(
        "--images-server",
        help="HTTP server to retrieve images from",
        default="https://gha-self-hosted-images.infra.rust-lang.org",
    )
    parser.add_argument(
        "--images-cache-dir",
        help="Directory to store cached images in",
        type=Path,
    )

    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
