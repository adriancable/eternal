#!/bin/bash
# Compile a C file to a Subleq Linux ELF executable
# Usage: ./clang_userspace.sh <source.c> [output.elf] [extra_flags...]
#
# This script compiles C source files for userspace execution under Subleq Linux,
# using the uClibc-ng sysroot for headers and libraries.
#
# Runtime symbols (__subleq_mul, __subleq_and, soft float, etc.) are left
# undefined and resolved by the kernel at load time.
#
# Examples:
#   ./clang_userspace.sh test.c                    # Default (dynamic linking)
#   ./clang_userspace.sh test.c test.elf -static   # Static linking

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <source.c> [output.elf] [extra_flags...]"
    echo ""
    echo "Options:"
    echo "  -static    Link statically (use libc.a instead of libc.so)"
    exit 1
fi

SOURCE="$1"
BASENAME=$(basename "$SOURCE" .c)
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
CLANG="$BUILD/clang"

# Sysroot path (contains headers and libraries from uClibc-ng)
SYSROOT="$PROJECT_ROOT/runtime/sysroot"

# Note: kernel-headers provides asm/, asm-generic/, and linux/ headers
KERNEL_HEADERS="$PROJECT_ROOT/uclibc-ng/kernel-headers/include"

# Common flags for Subleq Linux userspace C++
CXXFLAGS="--sysroot=$SYSROOT \
    -isystem $KERNEL_HEADERS \
    -ffunction-sections -fdata-sections \
    -O3"

LDFLAGS="-Wl,--gc-sections"

# Compile and link using clang driver
# libc is automatically linked by the driver for C programs
# Runtime symbols are left undefined and resolved by the kernel at load time
echo "Compiling and linking $SOURCE..."
"$CLANG" $CXXFLAGS $LDFLAGS $EXTRA_ARGS -o "$OUTNAME" "$SOURCE" 2>&1

echo "Output: $OUTNAME"
