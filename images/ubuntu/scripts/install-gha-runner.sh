#!/bin/bash
# Install and configure the GitHub Actions runner on the image.

set -euo pipefail
IFS=$'\n\t'

AGENT_REPO="actions/runner"

case "$(uname -m)" in
    x86_64)
        AGENT_PLATFORM="linux-x64"
        ;;
    aarch64)
        AGENT_PLATFORM="linux-arm64"
        ;;
    *)
        echo "error: unsupported platform: $(uname -m)"
        exit 1
        ;;
esac

# We need to know the exact version number to be able to download the runner, but the API GitHub
# provides to retrieve it (GitHub's REST releases API) is heavily rate limited for non-authenticated
# requests. We cannot easily pass a token inside of the build (and we wouldn't want to risk baking
# it into the image anyway), so we need to retrieve the latest version in another way.
#
# The `$repo/releases/latest` browser URL redirects to `$repo/releases/tag/$version`. We thus
# extract the `location` header and parse the version from the redirected URL.
echo "determining the latest version of the runner..."
version="$(curl --head "https://github.com/${AGENT_REPO}/releases/latest" | grep "^location:" | sed 's#.*releases/tag/v##' | tr -d '\r')"
if [[ "${version}" == https* ]]; then
    # Version begins with "https", so `sed` failed to strip the URL. This likely means GitHub
    # started redirecting to a different page :(
    echo "error: the hack to determine the latets version of the runner failed"
    exit 1
fi
echo "found version ${version}"

echo "adding the gha user..."
sudo adduser gha --home /gha --disabled-password
sudo adduser gha docker
echo "gha ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/gha-nopasswd

echo "downloading and installing the runner..."
curl -Lo /tmp/runner.tar.gz "https://github.com/${AGENT_REPO}/releases/download/v${version}/actions-runner-${AGENT_PLATFORM}-${version}.tar.gz"
sudo -u gha -- tar -C /gha -xzf /tmp/runner.tar.gz
rm /tmp/runner.tar.gz

echo "configuring startup of the runner..."
sudo cp /tmp/packer-files/gha-runner.service /etc/systemd/system/gha-runner.service
sudo systemctl daemon-reload
sudo systemctl enable gha-runner.service # Will start at the next boot.

echo "adding runner information..."
cat > /tmp/setup_info << EOF
[
    {
        "group": "Image details",
        "detail": "rust-lang/gha-self-hosted commit: ${GIT_SHA}\nImage build time: $(date --iso-8601=seconds --utc)"
    }
]
EOF
sudo -u gha cp /tmp/setup_info /gha/.setup_info
