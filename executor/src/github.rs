use anyhow::{Context, Error, bail};
use jsonwebtoken::{Algorithm, EncodingKey};
use reqwest::Method;
use reqwest::{Client, RequestBuilder, Response};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tokio::time::sleep;

const REFRESH_TOKEN_AFTER: Duration = Duration::from_secs(60 * 15);
const POLL_INTERVAL: Duration = Duration::from_secs(5);

#[derive(Clone)]
pub struct GitHub {
    inner: Arc<GitHubInner>,
}

impl GitHub {
    pub fn new(client_id: &str, private_key: &Path, org: &str) -> Result<Self, Error> {
        let http = Client::builder()
            .user_agent("rust-lang/gha-self-hosted (infra@rust-lang.org)")
            .build()?;

        Ok(Self {
            inner: Arc::new(GitHubInner {
                http,
                org: org.into(),
                client_id: client_id.into(),
                private_key: private_key.into(),
                token: Mutex::new(None),
            }),
        })
    }

    pub async fn run_after_build_started(&self, id: u64, then: impl FnOnce()) {
        let mut last_status = None;
        let mut not_yet_executed = Some(then);

        loop {
            match self.get_runner(id).await {
                Ok(runner) => {
                    if last_status.as_ref() != Some(&runner.status) {
                        last_status = Some(runner.status.clone());
                        eprintln!("runner status changed to {}", runner.status);
                    }
                    if runner.busy
                        && let Some(callback) = not_yet_executed.take()
                    {
                        eprintln!("the runner started processing a build");
                        callback();
                        break;
                    }
                }
                Err(err) => {
                    eprintln!("warning: failed to poll GitHub for the runner status: {err}");
                }
            };
            sleep(POLL_INTERVAL).await;
        }
    }

    pub async fn create_runner(
        &self,
        name: &str,
        runner_group_id: u64,
        labels: &[&str],
    ) -> Result<CreatedRunner, Error> {
        #[derive(serde::Serialize)]
        struct RunnerBody<'a> {
            name: &'a str,
            labels: &'a [&'a str],
            runner_group_id: u64,
        }
        #[derive(serde::Deserialize)]
        struct RunnerResponse {
            runner: RunnerRunner,
            encoded_jit_config: String,
        }
        #[derive(serde::Deserialize)]
        struct RunnerRunner {
            id: u64,
        }

        let response: RunnerResponse = self
            .request(
                Method::POST,
                AuthMode::Token,
                &format!(
                    "https://api.github.com/orgs/{}/actions/runners/generate-jitconfig",
                    self.inner.org
                ),
            )
            .await?
            .json(&RunnerBody {
                name,
                runner_group_id,
                labels,
            })
            .send()
            .await?
            .handle_github_error()
            .await?
            .json()
            .await?;

        Ok(CreatedRunner {
            id: response.runner.id,
            jitconfig: response.encoded_jit_config,
        })
    }

    pub async fn get_runner(&self, id: u64) -> Result<RunnerInfo, Error> {
        let response = self
            .request(
                Method::GET,
                AuthMode::Token,
                &format!(
                    "https://api.github.com/orgs/{}/actions/runners/{id}",
                    self.inner.org
                ),
            )
            .await?
            .send()
            .await?
            .handle_github_error()
            .await?
            .json()
            .await?;
        Ok(response)
    }

    async fn refresh_token(&self) -> Result<String, Error> {
        #[derive(serde::Deserialize)]
        struct Installation {
            id: u64,
        }
        #[derive(serde::Deserialize)]
        struct Token {
            token: String,
        }

        eprintln!("refreshing the token for organization {}", self.inner.org);

        let jwt = self.generate_jwt()?;
        let installation = self
            .request(
                Method::GET,
                AuthMode::Jwt(&jwt),
                &format!(
                    "https://api.github.com/orgs/{}/installation",
                    self.inner.org
                ),
            )
            .await?
            .send()
            .await?
            .handle_github_error()
            .await?
            .json::<Installation>()
            .await?
            .id;
        let token = self
            .request(
                Method::POST,
                AuthMode::Jwt(&jwt),
                &format!("https://api.github.com/app/installations/{installation}/access_tokens"),
            )
            .await?
            .send()
            .await?
            .handle_github_error()
            .await?
            .json::<Token>()
            .await?
            .token;

        *self.inner.token.lock().unwrap() = Some(GitHubToken {
            token: token.clone(),
            issued_at: Instant::now(),
        });

        Ok(token)
    }

    fn generate_jwt(&self) -> Result<String, Error> {
        #[derive(serde::Serialize)]
        struct Claims<'a> {
            iat: u64,
            exp: u64,
            iss: &'a str,
        }

        let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();

        Ok(jsonwebtoken::encode(
            &jsonwebtoken::Header {
                alg: Algorithm::RS256,
                ..Default::default()
            },
            &Claims {
                iat: now - 60,
                exp: now + 60 * 5,
                iss: &self.inner.client_id,
            },
            &EncodingKey::from_rsa_pem(&std::fs::read(&self.inner.private_key)?)?,
        )?)
    }

    async fn request(
        &self,
        method: Method,
        auth: AuthMode<'_>,
        url: &str,
    ) -> Result<RequestBuilder, Error> {
        let mut request = self.inner.http.request(method, url);
        match auth {
            AuthMode::Jwt(jwt) => {
                request = request.header("authorization", format!("Bearer {jwt}"));
            }
            AuthMode::Token => {
                let cache = self.inner.token.lock().unwrap().clone();
                let token = match cache {
                    Some(t) if t.issued_at.elapsed() > REFRESH_TOKEN_AFTER => {
                        Box::pin(self.refresh_token())
                            .await
                            .context("failed to refresh token")?
                    }
                    Some(t) => t.token.clone(),
                    None => Box::pin(self.refresh_token())
                        .await
                        .context("failed to refresh token")?,
                };
                request = request.header("authorization", format!("token {token}"));
            }
        }
        Ok(request)
    }
}

struct GitHubInner {
    http: Client,
    org: String,
    client_id: String,
    private_key: PathBuf,
    token: Mutex<Option<GitHubToken>>,
}

#[derive(Clone)]
struct GitHubToken {
    token: String,
    issued_at: Instant,
}

pub struct CreatedRunner {
    pub id: u64,
    pub jitconfig: String,
}

#[derive(serde::Deserialize)]
pub struct RunnerInfo {
    pub busy: bool,
    pub status: String,
}

enum AuthMode<'a> {
    Jwt(&'a str),
    Token,
}

trait ResponseExt: Sized {
    async fn handle_github_error(self) -> Result<Self, Error>;
}

impl ResponseExt for Response {
    async fn handle_github_error(self) -> Result<Self, Error> {
        #[derive(serde::Deserialize)]
        struct ErrorResponse {
            message: String,
        }

        let status = self.status();
        if status.is_client_error() || status.is_server_error() {
            let url = self.url().to_string();
            let body = self.text().await?;
            let message = if let Ok(parsed) = serde_json::from_str::<ErrorResponse>(&body) {
                parsed.message
            } else {
                body
            };

            bail!("request failed with status {status}: {message} (url: {url})")
        } else {
            Ok(self)
        }
    }
}
