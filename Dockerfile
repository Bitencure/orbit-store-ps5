FROM orbit-sdk:0.43
USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl python3 cmake pkg-config autoconf automake libtool perl libcurl4-openssl-dev libmicrohttpd-dev libssl-dev zstd && rm -rf /var/lib/apt/lists/*
COPY tools/build-deps.sh /tmp/build-deps.sh
RUN apt-get update && apt-get install -y --no-install-recommends xz-utils && rm -rf /var/lib/apt/lists/*
# Fork: OpenSSL embeds its build date, which shifts every merged string in the final link. Pinning it to the
# date of upstream's own library build (2026-10-02T23:17:49Z, read from the official ELF) makes an unmodified
# rebuild byte-identical to the published orbit_store.elf. A new cache id keeps older, differently dated objects out.
RUN --mount=type=cache,id=orbit-deps-epoch,target=/tmp/orbit-deps SOURCE_DATE_EPOCH=1790983069 bash /tmp/build-deps.sh
# Host tests: the payload's pinned libarchive, and 7-Zip to generate fixtures.
RUN apt-get update && apt-get install -y --no-install-recommends zlib1g-dev libbz2-dev liblzma-dev 7zip && rm -rf /var/lib/apt/lists/*
COPY tools/build-host-archive.sh /tmp/build-host-archive.sh
RUN --mount=type=cache,target=/tmp/orbit-deps bash /tmp/build-host-archive.sh
RUN apt-get update && apt-get install -y --no-install-recommends clang-format-19 && rm -rf /var/lib/apt/lists/*
WORKDIR /work
ENTRYPOINT ["make"]
CMD ["host"]
