from .utils import log
import json
import os
import re
import threading
import time
import urllib.request


# How many seconds should pass between each call to the GitHub API.
GITHUB_API_POLL_INTERVAL = 15


class GitHubRunnerStatusWatcher(threading.Thread):
    def __init__(self, repo, runner_name, check_interval, then):
        super().__init__(name="github-runner-status-watcher", daemon=True)

        self._check_interval = check_interval
        self._repo = repo
        self._runner_name = runner_name
        self._then = then

    def run(self):
        log("started polling GitHub to detect when the runner started working")
        while True:
            runners = self._retrieve_runners()
            if self._runner_name in runners and runners[self._runner_name]["busy"]:
                log("the runner started processing a build!")
                self._then()
                break
            time.sleep(self._check_interval)

    def _retrieve_runners(self):
        result = {}
        url = f"https://api.github.com/repos/{self._repo}/actions/runners"
        for response in github_api("GET", url):
            for runner in response["runners"]:
                result[runner["name"]] = runner
        return result


NEXT_LINK_RE = re.compile(r"<([^>]+)>; rel=\"next\"")


def github_api(method, url):
    try:
        github_token = os.environ["GITHUB_TOKEN"]
    except KeyError:
        raise RuntimeError("missing environment variable GITHUB_TOKEN") from None

    while url is not None:
        request = urllib.request.Request(url)
        request.add_header(
            "User-Agent",
            "https://github.com/rust-lang/gha-self-hosted (infra@rust-lang.org)",
        )
        request.add_header("Authorization", f"token {github_token}")
        request.method = method

        response = urllib.request.urlopen(request)

        # Handle pagination of the GitHub API
        url = None
        if "Link" in response.headers:
            captures = NEXT_LINK_RE.search(response.headers["Link"])
            if captures is not None:
                url = captures.group(1)

        yield json.load(response)
