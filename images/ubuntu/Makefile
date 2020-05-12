.PHONY: all clean ubuntu-amd64 ubuntu-aarch64

all: ubuntu-amd64 ubuntu-aarch64

clean:
	rm -rf packer_cache build

ubuntu-amd64:
	rm -rf build
	packer build -only=ubuntu-amd64 ubuntu.json

ubuntu-aarch64: QEMU_EFI.fd
	rm -rf build
	packer build -only=ubuntu-aarch64 ubuntu.json

QEMU_EFI.fd:
	curl -LO https://releases.linaro.org/components/kernel/uefi-linaro/latest/release/qemu64/QEMU_EFI.fd
