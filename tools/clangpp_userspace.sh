#!/bin/bash
# Compile a C++ file to a Subleq Linux ELF executable
# Usage: ./clangpp_userspace.sh <source.cpp> [output.elf] [extra_flags...]
#
# This script compiles C++ source files for userspace execution under Subleq Linux,
# using the uClibc-ng sysroot for headers and libraries.
#
# The driver automatically links libcxxabi for C++ exception handling support:
#   - By default: links libcxxabi.so (dynamic)
#   - With -static: links libcxxabi.a (static)
#
# Runtime symbols (__subleq_mul, __subleq_and, soft float, etc.) are left
# undefined and resolved by the kernel at load time.
#
# Examples:
#   ./clangpp_userspace.sh test.cpp                    # Default (dynamic linking)
#   ./clangpp_userspace.sh test.cpp test.elf -static   # Static linking

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <source.cpp> [output.elf] [extra_flags...]"
    echo ""
    echo "Options:"
    echo "  -static    Link statically (use libcxxabi.a instead of libcxxabi.so)"
    exit 1
fi

SOURCE="$1"
BASENAME=$(basename "$SOURCE" .cpp)
OUTNAME="${2:-${BASENAME}.elf}"

# Collect extra args (skip source and output)
shift
if [ -n "$1" ] && [[ ! "$1" == -* ]]; then
    shift  # Skip output name if it's not a flag
fi
EXTRA_ARGS="$@"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
BUILD="$PROJECT_ROOT/llvm-project/build/bin"
CLANGPP="$BUILD/clang++"

# Sysroot path (contains headers and libraries from uClibc-ng)
SYSROOT="$PROJECT_ROOT/runtime/sysroot"

# Note: kernel-headers provides asm/, asm-generic/, and linux/ headers
KERNEL_HEADERS="$PROJECT_ROOT/uclibc-ng/kernel-headers/include"

# Common flags for Subleq Linux userspace C++
CXXFLAGS="--sysroot=$SYSROOT \
    -isystem $KERNEL_HEADERS \
    -O3 -frtti -fexceptions"

LDFLAGS=""

# Compile and link using clang++ driver
# libcxxabi is automatically linked by the driver for C++ programs
# Runtime symbols are left undefined and resolved by the kernel at load time
echo "Compiling and linking $SOURCE..."
"$CLANGPP" $CXXFLAGS $LDFLAGS $EXTRA_ARGS -o "$OUTNAME" "$SOURCE" 2>&1

echo "Output: $OUTNAME"
