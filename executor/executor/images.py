from executor.utils import log
from pathlib import Path
from zstandard import ZstdDecompressor
import hashlib
import requests
import shutil
import tempfile
import threading
import time
import typing


IMAGES_SERVER_POLL_INTERVAL = 5 * 60  # 5 minutes


class ImagesRetriever:
    def __init__(self, cli):
        self._http = requests.Session()
        self._server = cli.images_server.rstrip("/")

        if cli.images_cache_dir is not None:
            self._storage_dir: Path = cli.images_cache_dir
            self._storage_dir.mkdir(parents=True, exist_ok=True)
        else:
            # If no cache dir is configured, create a temporary one just for this invocation. This
            # avoids having separate code paths for "cached" and "not cached".
            self._storage_dir = Path(tempfile.mkdtemp())

        self._latest_commit = self._get_text("latest")
        self._purge_old_caches()

    def get_image(self, name):
        local_path = self._storage_dir / self._latest_commit / f"{name}.qcow2"
        local_path.parent.mkdir(exist_ok=True, parents=True)

        image_url = f"images/{self._latest_commit}/{name}.qcow2"

        if not local_path.exists():
            log(f"downloading image {name} (commit: {self._latest_commit})")

            resp = self._http.get(f"{self._server}/{image_url}.zst", stream=True)
            resp.raise_for_status()

            decompressor = ZstdDecompressor()
            with local_path.open("wb") as dst:
                src = typing.cast(typing.BinaryIO, resp.raw)
                decompressor.copy_stream(src, dst)

        # Check that the image we are running matches the hash the images server expect. This helps
        # detect tampering in the images cache (possibly done by a compromised previous build).
        log(f"verifying hash of image {name}")
        local_hash = hashlib.file_digest(local_path.open("rb"), "sha256").hexdigest()
        remote_hash = self._get_text(f"{image_url}.sha256")
        if local_hash != remote_hash:
            print(f"error: local hash of image {name} differs from the remote one")
            print(f"local hash: {local_hash}")
            print(f"remote hash: {remote_hash}")
            exit(1)

        return local_path

    def _get_text(self, path):
        resp = self._http.get(f"{self._server}/{path}")
        resp.raise_for_status()
        return resp.text.strip()

    def _purge_old_caches(self):
        for entry in self._storage_dir.iterdir():
            if entry.is_dir() and entry.name != self._latest_commit:
                log(f"purging image cache for commit {entry.name}")
                shutil.rmtree(entry)


class ImageUpdateWatcher(threading.Thread):
    def __init__(self, retriever: ImagesRetriever, then):
        self._retriever = retriever
        self._then = then

        super().__init__(name="image-update-watcher", daemon=True)

    def run(self):
        log("started polling the image server to check for image updates")
        while True:
            time.sleep(IMAGES_SERVER_POLL_INTERVAL)
            try:
                new_commit = self._retriever._get_text("latest")
            except requests.exceptions.RequestException as e:
                print(f"warn: failed to check for image updates: {e}")
                continue
            if new_commit != self._retriever._latest_commit:
                log(f"new images with commit {new_commit} are available")
                self._then()
