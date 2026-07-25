# Finta toolchain OpenWrt per i test (scenario Molecule "default").
#
# Non compila niente: al posto del firmware produce un file che CONTIENE il
# .config assemblato dal ruolo. Cosi' i test possono verificare quali pacchetti
# sarebbero finiti davvero nell'immagine (e quali no) senza le 2-3 ore e le
# decine di GB di una build vera, impossibili su un runner GitHub.
#
# I target replicano quelli che il ruolo invoca: defconfig, download, clean e
# la build di default.

BIN := bin/targets/ramips/mt76x8
IMG := $(BIN)/openwrt-ramips-mt76x8-glinet_gl-mt300n-v2-squashfs-sysupgrade.bin

.PHONY: all defconfig download clean

all:
	@mkdir -p $(BIN)
	@cp .config $(BIN)/config.buildinfo
	@{ echo "STUB FIRMWARE"; cat .config; } > $(IMG)
	@echo "stub-toolchain" > $(BIN)/version.buildinfo
	@cp feeds.conf $(BIN)/feeds.buildinfo
	@sha256sum $(IMG) > $(BIN)/sha256sums

# Il defconfig vero normalizza il .config: qui basta verificare che esista,
# cosi' il test fallisce se dotconfig.yml non lo ha assemblato.
defconfig:
	@test -f .config

download:
	@true

clean:
	@rm -rf bin
