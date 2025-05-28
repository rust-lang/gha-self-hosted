from dataclasses import dataclass
from uuid import uuid4
from .utils import log
import jwt
import requests
import threading
import time


# How many seconds should pass between each call to the GitHub API.
GITHUB_API_POLL_INTERVAL = 15


class GitHub:
    def __init__(self, cli):
        self.org = cli.github_org

        self._http = requests.Session()
        self._http.headers["User-Agent"] = (
            "rust-lang/gha-self-hosted (infra@rust-lang.org)"
        )

        log(f"generating a JWT to authenticate as app {cli.github_client_id}")
        bearer = jwt.encode(
            {
                "iat": int(time.time() - 60),
                "exp": int(time.time() + 60 * 5),
                "iss": cli.github_client_id,
            },
            open(cli.github_private_key, "rb").read(),
            algorithm="RS256",
        )

        log(f"retrieving app installation id for {self.org}")
        resp = self._handle_error(
            self._http.get(
                f"https://api.github.com/orgs/{self.org}/installation",
                headers={"Authorization": f"Bearer {bearer}"},
            )
        )
        installation = resp.json()["id"]

        log(f"retrieving token for installation {installation}")
        resp = self._handle_error(
            self._http.post(
                f"https://api.github.com/app/installations/{installation}/access_tokens",
                headers={"Authorization": f"Bearer {bearer}"},
            )
        )

        self._http.headers["Authorization"] = f"token {resp.json()['token']}"

    def _handle_error(self, response: requests.Response) -> requests.Response:
        if response.status_code >= 400:
            print(
                f"error: github responded with status {response.status_code} to the request"
            )
            print(f"url: {response.url}")
            print(f"message: {response.json()['message']}")
            exit(1)
        return response

    def create_runner(self, cli, instance):
        resp = self._handle_error(
            self._http.post(
                f"https://api.github.com/orgs/{self.org}/actions/runners/generate-jitconfig",
                json={
                    "name": f"{instance['label']}-{uuid4()}",
                    "runner_group_id": cli.runner_group_id,
                    "labels": [instance["label"]],
                },
            )
        ).json()
        return RunnerInfo(id=resp["runner"]["id"], jitconfig=resp["encoded_jit_config"])

    def get_runner(self, id):
        r = self._http.get(
            f"https://api.github.com/orgs/{self.org}/actions/runners/{id}"
        )
        return self._handle_error(r).json()


class GitHubRunnerStatusWatcher(threading.Thread):
    def __init__(self, gh, runner_id, then):
        super().__init__(name="github-runner-status-watcher", daemon=True)

        self._gh = gh
        self._runner_id = runner_id
        self._then = then

    def run(self):
        log("started polling GitHub to detect when the runner started working")
        while True:
            runner = self._gh.get_runner(self._runner_id)
            if runner["busy"]:
                log("the runner started processing a build!")
                self._then()
                break
            time.sleep(GITHUB_API_POLL_INTERVAL)


@dataclass
class RunnerInfo:
    id: int
    jitconfig: str
