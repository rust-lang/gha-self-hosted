#!/usr/bin/env -S uv run

# Simple script to serve VM images built locally in the format the executor script expects them.
#
# Usage: ./local-image-server.py ../images/ubuntu/build [--port=8000]

from executor.utils import log
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from zstandard import ZstdCompressor
import argparse
import hashlib
import os
import random
import string
import tempfile


def find_images(dir: Path):
    for entry in dir.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix != ".qcow2":
            continue
        yield entry.stem, entry


def prepare_content(images_dir: Path):
    fake_commit = "".join(random.choice(string.hexdigits).lower() for _ in range(40))
    log(f"preparing local server for *fake* commit {fake_commit}")

    dest = Path(tempfile.mkdtemp())
    dest_latest = dest / "latest"
    dest_images = dest / "images" / fake_commit

    dest_latest.write_text(fake_commit)
    dest_images.mkdir(parents=True)

    for name, file in find_images(images_dir):
        log(f"preparing image {name} (compressing and hashing...)")

        dest_file = dest_images / f"{name}.qcow2.zst"
        with file.open("rb") as src, dest_file.open("wb") as dst:
            ZstdCompressor(level=1).copy_stream(src, dst)

        sha256_file = dest_images / f"{name}.qcow2.sha256"
        with file.open("rb") as src, sha256_file.open("w") as dst:
            hash = hashlib.file_digest(src, "sha256")
            dst.write(hash.hexdigest() + "\n")

    return dest


def serve(content_dir: Path, port: int):
    log(f"serving the local files on port {port}")
    print("You can use the local image server by adding this flag to `run.py`:")
    print()
    print(f"    --images-server http://localhost:{port}")
    print()

    # Python's SimpleHTTPRequestHandler serves the current directory by default, and it's quite
    # unwieldy to customize it. Let's just work around that by changing the current directory to
    # the path we want to serve.
    os.chdir(content_dir)

    server = HTTPServer(("localhost", port), SimpleHTTPRequestHandler)
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("images_dir", type=Path)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    content = prepare_content(args.images_dir)
    serve(content, args.port)


if __name__ == "__main__":
    main()
