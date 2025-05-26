ENV = PACKER_CACHE_DIR=build/cache
PACKER_ARGS = -var "git_sha=$(shell git rev-parse HEAD)"

.PHONY: host clean x86_64-host aarch64-host

host:
	make $(shell uname -m)-host

clean:
	rm -rf build

x86_64-host:
	rm -rf build/x86_64
	$(ENV) packer build $(PACKER_ARGS) -var emulated=false -only=qemu.ubuntu-x86_64 image.pkr.hcl

x86_64-emul:
	rm -rf build/x86_64
	$(ENV) packer build $(PACKER_ARGS) -var emulated=true -only=qemu.ubuntu-x86_64 image.pkr.hcl

aarch64-host:
	rm -rf build/aarch64
	$(ENV) packer build $(PACKER_ARGS) -var emulated=false -only qemu.ubuntu-aarch64 image.pkr.hcl

aarch64-emul:
	rm -rf build/aarch64
	$(ENV) packer build $(PACKER_ARGS) -var emulated=true -only qemu.ubuntu-aarch64 image.pkr.hcl
