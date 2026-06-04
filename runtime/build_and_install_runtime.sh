#!/bin/bash
# Build and install Subleq runtime libraries
#
# This script:
# 1. Regenerates the core runtime from Python generators
# 2. Copies core runtime to Linux kernel sources
# 3. Builds soft-float runtime
# 4. Copies soft-float runtime to Linux kernel sources
# 5. Builds CXXABI runtime to libc++abi.a
# 6. Installs libc++abi.a to the sysroot

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
BUILD="$PROJECT_ROOT/llvm-project/build/bin"
CLANG="$BUILD/clang"
CLANGPP="$BUILD/clang++"
MC="$BUILD/llvm-mc"
AR="$BUILD/llvm-ar"

# Sysroot path
SYSROOT="$PROJECT_ROOT/runtime/sysroot"

# Linux kernel path
LINUX_LIB="$PROJECT_ROOT/linux/arch/subleq/lib"

echo "=== Subleq Runtime Build and Install ==="
echo ""

# Step 1: Regenerate core runtime from Python
echo "Step 1: Regenerating core runtime..."
cd "$SCRIPT_DIR/core"
python3 gen_runtime.py > subleq_runtime.s
echo "  Generated: core/subleq_runtime.s"

# Step 2: Copy core runtime to Linux kernel
echo "Step 2: Copying core runtime to Linux kernel..."
cp "$SCRIPT_DIR/core/subleq_runtime.s" "$LINUX_LIB/subleq_runtime.S"
echo "  Copied to: linux/arch/subleq/lib/subleq_runtime.S"

# Step 2B: Build core runtime
"$MC" -triple=subleq -filetype=obj -o "$SCRIPT_DIR/core/subleq_runtime.o" "$SCRIPT_DIR/core/subleq_runtime.s"
echo "  Built: core/subleq_runtime.o"

# Step 3: Build soft-float runtime
echo "Step 3: Building soft-float runtime..."
"$CLANG" -target subleq -c -O3 -ffunction-sections -fdata-sections -fno-builtin -ffreestanding \
    -o "$SCRIPT_DIR/fpu/subleq_runtime_softfloat.o" \
    "$SCRIPT_DIR/fpu/subleq_runtime_softfloat.c"
echo "  Built: fpu/subleq_runtime_softfloat.o"

# Step 4: Copy soft-float runtime to Linux kernel
echo "Step 4: Copying soft-float runtime to Linux kernel..."
cp "$SCRIPT_DIR/fpu/subleq_runtime_softfloat.c" "$LINUX_LIB/"
echo "  Copied to: linux/arch/subleq/lib/subleq_runtime_softfloat.c"

# Step 5: Build CXXABI runtime (static library)
echo "Step 5: Building CXXABI runtime..."
cd "$SCRIPT_DIR/cxxabi"

# Build each object file for static library
"$CLANG" -target subleq-unknown-linux \
    --sysroot="$SYSROOT" \
    -O3 -fno-builtin \
    -c cxxabi_minimal.c -o cxxabi_minimal.o
echo "  Built: cxxabi/cxxabi_minimal.o"

"$CLANGPP" -target subleq-unknown-linux \
    --sysroot="$SYSROOT" \
    -isystem "$SCRIPT_DIR/cxxabi/include" \
    -O3 -fno-builtin -frtti -fno-exceptions \
    -c cxxabi_typeinfo.cpp -o cxxabi_typeinfo.o
echo "  Built: cxxabi/cxxabi_typeinfo.o"

"$CLANG" -target subleq-unknown-linux \
    --sysroot="$SYSROOT" \
    -c sjlj_longjmp.S -o sjlj_longjmp.o
echo "  Built: cxxabi/sjlj_longjmp.o"

"$CLANG" -target subleq-unknown-linux \
    --sysroot="$SYSROOT" \
    -O3 -fno-builtin \
    -c sjlj_unwind.c -o sjlj_unwind.o
echo "  Built: cxxabi/sjlj_unwind.o"

# Create static library
"$AR" rcs libc++abi.a cxxabi_minimal.o cxxabi_typeinfo.o sjlj_longjmp.o sjlj_unwind.o
echo "  Created: cxxabi/libc++abi.a"

# Step 6: Install libraries and headers to sysroot
echo "Step 6: Installing libc++abi to sysroot..."
mkdir -p "$SYSROOT/lib"
cp "$SCRIPT_DIR/cxxabi/libc++abi.a" "$SYSROOT/lib/"
echo "  Installed: runtime/sysroot/lib/libc++abi.a"

# Install cxxabi.h to sysroot so clang++ driver finds it automatically
mkdir -p "$SYSROOT/include/c++/v1"
cp "$SCRIPT_DIR/cxxabi/include/cxxabi.h" "$SYSROOT/include/c++/v1/"
echo "  Installed: runtime/sysroot/include/c++/v1/cxxabi.h"

# Create empty libunwind.a stub (libc++.so linker script references -lunwind,
# but Subleq's SJLJ unwinding is built into libc++abi)
"$AR" rcs "$SYSROOT/lib/libunwind.a"
echo "  Installed: runtime/sysroot/lib/libunwind.a (empty stub)"

echo ""
echo "=== Build complete! ==="
echo ""
echo "Runtime components:"
echo "  Core runtime:      runtime/core/subleq_runtime.s"
echo "  Soft-float:        runtime/fpu/subleq_runtime_softfloat.o"
echo "  CXXABI static:     runtime/cxxabi/libc++abi.a"
echo ""
echo "Installed to:"
echo "  Linux kernel:      linux/arch/subleq/lib/"
echo "  Sysroot:           runtime/sysroot/lib/libc++abi.a"
