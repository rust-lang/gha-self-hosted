#!/usr/bin/env -S uv run

from executor.github import GitHub
from executor.qemu import VM
import argparse
import json
import re
import signal
import sys


class ConfigPreprocessor:
    # This regex matches: ${{ FUNCTION:ARGS }}
    _VARIABLE_RE = re.compile(r"^\${{ *(?P<function>[a-zA-Z0-9_-]+):(?P<args>[^}]+)}}$")

    def __init__(self, config, gh: GitHub):
        self._config = config
        self._gh = gh

    def process(self):
        for key, value in self._config.items():
            matches = self._VARIABLE_RE.match(value)
            if matches is None:
                continue

            function = matches.group("function").strip()
            args = matches.group("args").strip()

            if function == "gha-install-token":
                self._config[key] = self._gh.fetch_registration_token()
            else:
                raise ValueError(f"unknown preprocessor function: {function}")

        return self._config


signal_vms = []


def sigusr1_received(sig, frame):
    for vm in signal_vms:
        vm.sigusr1_received()


def run(cli):
    signal.signal(signal.SIGUSR1, sigusr1_received)

    gh = GitHub(cli)

    with open("instances.json") as f:
        instances = json.load(f)

    instance = None
    for candidate in instances:
        if candidate["name"] == cli.instance_name:
            instance = candidate
            break
    else:
        print(f"error: instance not found: {cli.instance_name}", file=sys.stderr)
        exit(1)

    config = ConfigPreprocessor(instance["config"], gh)
    env = {
        "name": instance["name"],
        "config": config.process(),
    }

    vm = VM(instance, env)
    signal_vms.append(vm)

    vm.run(gh)
    vm.cleanup()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("instance_name")

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

    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
