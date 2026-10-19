#!/usr/bin/env bash
# Linux host build for this fork, without Docker. Builds the pinned static
# libarchive and 7-Zip into .deps/ (gitignored) when missing, then runs make
# with repo-local overrides so nothing is installed system-wide.
# Usage: tools/fork/host-build.sh [make targets...]   (default: host build/orbit-test)
# Needs: a C/C++ compiler (clang), make, curl, 7z, python3, libcurl/libmicrohttpd/openssl dev files.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"

# The Makefile and tools/build-7zip.sh name clang-19; accept a newer unversioned clang.
mkdir -p .deps/bin
for pair in clang:clang-19 clang++:clang++-19 llvm-objcopy:llvm-objcopy-19; do
  src=${pair%%:*}; dst=${pair##*:}
  command -v "$dst" >/dev/null 2>&1 || ln -sf "$(command -v "$src")" ".deps/bin/$dst"
done
export PATH="$root/.deps/bin:$PATH"

prefix="$root/.deps/host-prefix"
if [ ! -f "$prefix/lib/libarchive.a" ]; then
  mkdir -p .deps/dl && cd .deps/dl
  [ -f libarchive.tar.xz ] || curl -fsSL --retry 3 -o libarchive.tar.xz \
    https://github.com/libarchive/libarchive/releases/download/v3.8.1/libarchive-3.8.1.tar.xz
  echo '19f917d42d530f98815ac824d90c7eaf648e9d9a50e4f309c812457ffa5496b5  libarchive.tar.xz' | sha256sum -c -
  rm -rf libarchive-src && mkdir libarchive-src && tar -xf libarchive.tar.xz -C libarchive-src --strip-components=1
  (cd libarchive-src &&
    CC=clang-19 ./configure --prefix="$prefix" --disable-shared --enable-static --with-pic \
      --disable-bsdtar --disable-bsdcpio --disable-bsdcat --disable-bsdunzip --disable-acl --disable-xattr \
      --without-openssl --without-xml2 --without-expat --without-iconv --without-lz4 --without-zstd \
      --without-lzo2 --without-nettle --without-mbedtls --without-libb2 --with-zlib --with-bz2lib --with-lzma &&
    make -j"$(nproc)" && make install)
  cd "$root"
fi
[ -f .deps/7zip-host/liborbit7zip.a ] || bash tools/build-7zip.sh host
[ -f .deps/cjson/cJSON.c ] && [ -f .deps/cacert.pem ] || .venv/bin/python tools/bootstrap.py
[ -f build/generated/assets.h ] || { npm ci && npm run build; }
[ -f build/generated/network.h ] || python3 tools/embed-launcher.py

[ "$#" -gt 0 ] || set -- host build/orbit-test
exec make \
  CPPFLAGS="-D_FILE_OFFSET_BITS=64 -Ibackend -Ilauncher -I.deps/cjson -Ibuild/generated -I$prefix/include" \
  HOST_ARCHIVE_LIBS="-L$prefix/lib -l:libarchive.a -llzma -lbz2 -lz build/sevenzip-host.o -Wl,--whole-archive .deps/7zip-host/liborbit7zip.a -Wl,--no-whole-archive -lstdc++" \
  "$@"
