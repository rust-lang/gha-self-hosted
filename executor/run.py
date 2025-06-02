#!/usr/bin/env -S uv run

import json
import re
import signal
import sys
from executor.utils import log
from executor.qemu import VM
from executor.github import github_api


class ConfigPreprocessor:
    # This regex matches: ${{ FUNCTION:ARGS }}
    _VARIABLE_RE = re.compile(r"^\${{ *(?P<function>[a-zA-Z0-9_-]+):(?P<args>[^}]+)}}$")

    def __init__(self, config):
        self._config = config

    def process(self):
        for key, value in self._config.items():
            matches = self._VARIABLE_RE.match(value)
            if matches is None:
                continue

            function = matches.group("function").strip()
            args = matches.group("args").strip()

            if function == "gha-install-token":
                self._config[key] = self._fetch_gha_install_token(args)
            else:
                raise ValueError(f"unknown preprocessor function: {function}")

        return self._config

    def _fetch_gha_install_token(self, repo):
        log(f"fetching the GHA installation token for {repo}")

        res = next(
            github_api(
                "POST",
                f"https://api.github.com/repos/{repo}/actions/runners/registration-token",
            )
        )
        return res["token"]


signal_vms = []


def sigusr1_received(sig, frame):
    for vm in signal_vms:
        vm.sigusr1_received()


def run(instance_name):
    signal.signal(signal.SIGUSR1, sigusr1_received)

    with open("instances.json") as f:
        instances = json.load(f)

    instance = None
    for candidate in instances:
        if candidate["name"] == instance_name:
            instance = candidate
            break
    else:
        print(f"error: instance not found: {instance_name}", file=sys.stderr)
        exit(1)

    config = ConfigPreprocessor(instance["config"])
    env = {
        "name": instance["name"],
        "config": config.process(),
    }

    vm = VM(instance, env)
    signal_vms.append(vm)

    vm.run()
    vm.cleanup()


if __name__ == "__main__":
    if len(sys.argv) == 2:
        run(sys.argv[1])
    else:
        print(f"usage: {sys.argv[0]} <instance-name>", file=sys.stderr)
        exit(1)
