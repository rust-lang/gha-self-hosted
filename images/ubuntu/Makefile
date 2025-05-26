ENV = PACKER_CACHE_DIR=build/cache
PACKER_ARGS = -var "git_sha=$(shell git rev-parse HEAD)"

.PHONY: host clean x86_64-host aarch64-host

host:
	make $(shell uname -m)-host

clean:
	rm -rf build

x86_64-host:
	rm -rf build/x86_64
	$(ENV) packer build $(PACKER_ARGS) -var emulated=false -var arch=x86_64 image.pkr.hcl

x86_64-emul:
	rm -rf build/x86_64
	$(ENV) packer build $(PACKER_ARGS) -var emulated=true -var arch=x86_64 image.pkr.hcl

aarch64-host: build/qemu-efi-aarch64.fd
	rm -rf build/aarch64
	$(ENV) packer build $(PACKER_ARGS) -var emulated=false -var arch=aarch64 -var firmware=build/qemu-efi-aarch64.fd image.pkr.hcl

aarch64-emul: build/qemu-efi-aarch64.fd
	rm -rf build/aarch64
	$(ENV) packer build $(PACKER_ARGS) -var emulated=true -var arch=aarch64 -var firmware=build/qemu-efi-aarch64.fd image.pkr.hcl

build/qemu-efi-aarch64.fd: utils/download-qemu-efi-aarch64.sh
	utils/download-qemu-efi-aarch64.sh "$@"
