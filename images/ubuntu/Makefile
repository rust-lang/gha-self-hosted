ENV_BASE = PACKER_CACHE_DIR=build/cache GIT_SHA=$(shell git rev-parse HEAD)
ENV_HOST = $(ENV_BASE) QEMU_ACCELERATOR=kvm SSH_TIMEOUT=5m SSH_HANDSHAKE_ATTEMPTS=10
ENV_EMUL = $(ENV_BASE) QEMU_ACCELERATOR=tcg SSH_TIMEOUT=1h SSH_HANDSHAKE_ATTEMPTS=100

.PHONY: host clean x86_64-host aarch64-host

host:
	make $(shell uname -m)-host

clean:
	rm -rf build

x86_64-host:
	rm -rf build/x86_64
	$(ENV_HOST) packer build -only=qemu.ubuntu-x86_64 image.pkr.hcl

x86_64-emul:
	rm -rf build/x86_64
	$(ENV_EMUL) packer build -only=qemu.ubuntu-x86_64 image.pkr.hcl

aarch64-host:
	rm -rf build/aarch64
	$(ENV_HOST) AARCH64_MACHINE=virt,gic_version=3 AARCH64_CPU=host packer build -only qemu.ubuntu-aarch64 image.pkr.hcl

aarch64-emul:
	rm -rf build/aarch64
	$(ENV_EMUL) AARCH64_MACHINE=virt AARCH64_CPU=cortex-a57 packer build -only qemu.ubuntu-aarch64 image.pkr.hcl
