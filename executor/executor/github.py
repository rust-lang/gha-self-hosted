from .utils import log
import jwt
import requests
import threading
import time


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

    def fetch_registration_token(self) -> str:
        log(f"fetching the GHA installation token for {self.org}")
        resp = self._handle_error(
            self._http.post(
                f"https://api.github.com/orgs/{self.org}/actions/runners/registration-token"
            )
        )
        return resp.json()["token"]


# How many seconds should pass between each call to the GitHub API.
GITHUB_API_POLL_INTERVAL = 15


class GitHubRunnerStatusWatcher(threading.Thread):
    def __init__(self, gh, repo, runner_name, check_interval, then):
        super().__init__(name="github-runner-status-watcher", daemon=True)

        self._check_interval = check_interval
        self._gh = gh
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
        # TODO: this is broken
        for response in self._gh._handle_error(self._gh._http.get(url)).json():
            for runner in response["runners"]:
                result[runner["name"]] = runner
        return result
