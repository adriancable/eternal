#!/bin/bash
# Cross-compile LLVM's libcxx for Subleq
#
# Prerequisites:
#   1. Toolchain built via build.sh (clang, lld, llvm-ar, etc.)
#   2. libc++abi built and installed to sysroot via build_and_install_runtime.sh
#   3. uclibc-ng sysroot populated
#
# This uses CMAKE_C_COMPILER_FORCED / CMAKE_CXX_COMPILER_FORCED to skip
# CMake's compiler identification step, which would otherwise fail because
# the built clang can only emit Subleq code (not host-native binaries).

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
BUILD_DIR="$SCRIPT_DIR/libcxx"
TOOLCHAIN="$PROJECT_ROOT/llvm-project/build/bin"
SYSROOT="$PROJECT_ROOT/runtime/sysroot"

# Verify prerequisites
if [ ! -x "$TOOLCHAIN/clang" ]; then
    echo "Error: Toolchain not found at $TOOLCHAIN/clang"
    echo "Run build.sh first to build the LLVM toolchain."
    exit 1
fi

if [ ! -f "$SYSROOT/lib/libc++abi.a" ]; then
    echo "Error: libc++abi.a not found in $SYSROOT/lib/"
    echo "Run build_and_install_runtime.sh first to build and install libc++abi."
    exit 1
fi

echo "=== Cross-compiling libcxx for Subleq ==="
echo ""
echo "Toolchain: $TOOLCHAIN"
echo "Sysroot:   $SYSROOT"
echo "Build dir: $BUILD_DIR"
echo ""

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

cmake -G Ninja \
    -S "$PROJECT_ROOT/llvm-project/runtimes" \
    -B "$BUILD_DIR" \
    \
    -DCMAKE_C_COMPILER="$TOOLCHAIN/clang" \
    -DCMAKE_CXX_COMPILER="$TOOLCHAIN/clang++" \
    -DCMAKE_AR="$TOOLCHAIN/llvm-ar" \
    -DCMAKE_RANLIB="$TOOLCHAIN/llvm-ranlib" \
    -DCMAKE_NM="$TOOLCHAIN/llvm-nm" \
    -DCMAKE_OBJDUMP="$TOOLCHAIN/llvm-objdump" \
    \
    -DCMAKE_C_COMPILER_TARGET=subleq-unknown-linux \
    -DCMAKE_CXX_COMPILER_TARGET=subleq-unknown-linux \
    -DCMAKE_SYSTEM_NAME=Linux \
    -DCMAKE_SYSROOT="$SYSROOT" \
    -DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY \
    \
    -DLLVM_DIR="$PROJECT_ROOT/llvm-project/build/lib/cmake/llvm" \
    -DClang_DIR="$PROJECT_ROOT/llvm-project/build/lib/cmake/clang" \
    -DLLVM_DEFAULT_TARGET_TRIPLE=subleq-unknown-linux \
    -DLLVM_USE_LINKER=lld \
    \
    -DCMAKE_C_FLAGS="-Oz -isystem $SYSROOT/kernel-headers/include" \
    -DCMAKE_CXX_FLAGS="-Oz -isystem $SYSROOT/kernel-headers/include -D_LIBCPP_PROVIDES_DEFAULT_RUNE_TABLE" \
    -DCMAKE_BUILD_TYPE=MinSizeRel \
    -DCMAKE_INSTALL_PREFIX="$SYSROOT" \
    -DCMAKE_INSTALL_LIBDIR=lib \
    \
    -DLLVM_ENABLE_RUNTIMES="libcxx" \
    \
    -DLIBCXX_CXX_ABI=system-libcxxabi \
    -DLIBCXX_CXX_ABI_INCLUDE_PATHS="$SCRIPT_DIR/cxxabi/include" \
    -DLIBCXX_CXX_ABI_LIBRARY_PATH="$SYSROOT/lib" \
    \
    -DLIBCXX_ENABLE_SHARED=ON \
    -DLIBCXX_ENABLE_STATIC=ON \
    \
    -DLIBCXX_ENABLE_THREADS=ON \
    -DLIBCXX_HAS_PTHREAD_API=ON \
    -DLIBCXX_ENABLE_MONOTONIC_CLOCK=ON \
    -DLIBCXX_ENABLE_LOCALIZATION=ON \
    -DLIBCXX_ENABLE_WIDE_CHARACTERS=ON \
    -DLIBCXX_ENABLE_FILESYSTEM=ON \
    -DLIBCXX_ENABLE_RANDOM_DEVICE=ON \
    -DLIBCXX_ENABLE_TIME_ZONE_DATABASE=OFF \
    -DLIBCXX_ENABLE_EXCEPTIONS=ON \
    -DLIBCXX_ENABLE_RTTI=ON \
    -DLIBCXX_ENABLE_NEW_DELETE_DEFINITIONS=ON \
    -DLIBCXX_USE_COMPILER_RT=OFF \
    -DLIBCXX_HAS_MUSL_LIBC=OFF \
    -DLIBCXX_HAS_ATOMIC_LIB=OFF \
    -DLIBCXXABI_USE_LLVM_UNWINDER=OFF \
    -DLIBCXX_INCLUDE_BENCHMARKS=OFF \
    -DLIBCXX_INCLUDE_TESTS=OFF \
    -DLIBCXX_INCLUDE_DOCS=OFF \
    \
    -DCMAKE_SHARED_LINKER_FLAGS="-lc++abi" \
    -DCMAKE_EXE_LINKER_FLAGS=""

echo ""
echo "=== CMake configuration complete ==="
echo ""
echo "To build:   ninja -C $BUILD_DIR"
echo "To install: ninja -C $BUILD_DIR install"
echo ""
echo "This will install to: $SYSROOT"
echo "  Headers: $SYSROOT/include/c++/v1/"
echo "  Libs:    $SYSROOT/lib/libc++.{a,so}"
