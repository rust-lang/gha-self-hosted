# GitHub Actions self-hosted runners infrastructure

This repository contains the infrastructure to run self-hosted GitHub Actions
runners for the Rust project. The tools and scripts here are meant to be used
only by the Rust Infrastructure Team: we do not intend to support running them
outside our infra, and there might be breaking changes in the future.

The contents of this repository are released under either the MIT or the Apache
2.0 license, at your option.

## Deployment and operations

The production servers will pull this repository every 15 minutes, and if a
change in the `images/` directory was done images will also be rebuilt. Check
out [the documentation][forge] on the forge for instructions on how to operate
the production deployment.

[forge]: https://forge.rust-lang.org/infra/docs/gha-self-hosted.html
