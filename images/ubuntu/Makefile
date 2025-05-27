ENV = PACKER_CACHE_DIR=build/cache
PACKER_ARGS = -var "git_sha=$(shell git rev-parse HEAD)"

.PHONY: host clean init x86_64-host x86_64-emul aarch64-host aarch64-emul

host:
	make $(shell uname -m)-host

clean:
	rm -rf build

init:
	$(ENV) packer init image.pkr.hcl

x86_64-host: init
	rm -rf build/x86_64
	$(ENV) packer build $(PACKER_ARGS) -var emulated=false -var arch=x86_64 image.pkr.hcl

x86_64-emul: init
	rm -rf build/x86_64
	$(ENV) packer build $(PACKER_ARGS) -var emulated=true -var arch=x86_64 image.pkr.hcl

aarch64-host: init build/qemu-efi-aarch64.fd
	rm -rf build/aarch64
	$(ENV) packer build $(PACKER_ARGS) -var emulated=false -var arch=aarch64 -var firmware=build/qemu-efi-aarch64.fd image.pkr.hcl

aarch64-emul: init build/qemu-efi-aarch64.fd
	rm -rf build/aarch64
	$(ENV) packer build $(PACKER_ARGS) -var emulated=true -var arch=aarch64 -var firmware=build/qemu-efi-aarch64.fd image.pkr.hcl

# Running QEMU for AArch64 requires the QEMU_EFI.fd file to be provided. Some distributions like
# Debian and Ubuntu package it, but the path they use is not consistent across distros. To avoid
# problems, this step downloads the (mirrored) Debian package and extracts the file from it.
#
# Debian packages are `ar` archives containing the `data.tar.xz` tarball (and other metadata). That
# tarball then contains the files that will actually be installed on the system. So, to extract a
# file out of it we first need to extract the .deb with `ar`, and then the file with `tar`.
EFI_TMP = build/qemu-efi-aarch64-tmp
build/qemu-efi-aarch64.fd:
	rm -rf $(EFI_TMP)
	mkdir $(EFI_TMP)
	curl -Lo $(EFI_TMP)/package.deb https://ci-mirrors.rust-lang.org/gha-self-hosted/qemu-efi-aarch64_2022.11-6.deb
	cd $(EFI_TMP) && ar x package.deb
	tar -C $(EFI_TMP) -xf $(EFI_TMP)/data.tar.xz
	cp $(EFI_TMP)/usr/share/qemu-efi-aarch64/QEMU_EFI.fd $@
