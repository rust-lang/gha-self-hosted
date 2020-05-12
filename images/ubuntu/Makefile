.PHONY: all clean build

all: build

clean:
	rm -rf packer_cache build

build:
	rm -rf build
	packer build ubuntu.json
