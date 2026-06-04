# Introduction

This is the root repository for the [Eternal Software Initiative](https://www.eternal-software.org).

The ESI defines a minimal machine architecture (based on a modification of the Subleq OISC) that is so simple that its complete specification can be written down on a napkin. We then provide an LLVM compiler backend for this architecture, a port of Linux, ports of the C/C++ runtime libraries, and other tools (including a [reference virtual machine implementation](https://github.com/adriancable/eternal/vm/vm.c) in ~50 lines of C) required to build and run a self-contained 'capsule' from existing software.

What's the point of all this? Running today's software requires a complex stack of dependencies (compilers, libraries frameworks, OS) on top of proprietary and incompletely documented hardware, making it very difficult to ensure that today's software will continue to operate in the future. This problem of 'bit rot' is well known to anyone maintaining legacy software over a timespan of years or decades, but now imagine a historian 1,000 years from now trying to understand 21st century life, much of which is experienced through software. Even if today's software binaries are preserved, it is far fetched to imagine those binaries will still be runnable. Emulators like QEMU move this problem around but do not solve it: they too have a similarly complex stack of software and hardware dependencies, and so also won't be runnable in the far future.

The ESI solves this problem by (1) defining an architecture that is simple enough to write down on a napkin but powerful enough to efficiently represent any software, but does not require knowledge of any proprietary hardware, software, frameworks and so forth, and (2) implementing a toolchain to compile any existing software for this architecture into a self-contained 'capsule'. This ensures that, providing the capsule binary and the napkin instructions are preserved, the software can be revived and experienced in the far future without assuming any knowledge of present day computing systems.

This repository includes everything needed to build and run your own ESI machine, and build ESI 'capsules' from existing software.

For more information on the ESI's mission, see: [https://www.eternal-software.org](https://www.eternal-software.org)

# Check Out

This repository includes, as submodules, ESI forks of the LLVM toolchain, the Linux kernel, uClibc-ng, and Busybox. These must all be checked out together.

```
git clone --recurse-submodules https://github.com/adriancable/eternal
```

# Build VM and Try It

You will need SDL3 to build the ESI virtual machine. Install with e.g. `apt install libsdl3-dev`. There are no other dependencies. SDL3 can easily be replaced with any other means for writing pixels and capturing keyboard events, now or in the future.

```
cd eternal/vm
make

xz -d ../capsules/vmlinux.bootimage.xz
./vm ../capsules/vmlinux.bootimage
```

When Linux has booted, try for example:

```
cd doom
./doom
```

# Building the Toolchain

The ESI toolchain should build on any Linux system with minimal effort. We have also successfully built on macOS, with [some modifications](https://seiya.me/blog/building-linux-on-macos-natively). Make sure you have `gcc`, `python3`, `CMake`, `ninja`, `flex`, `bison` installed and operational.

Start in the checked-out `eternal` folder.

## Step 1: Build ESI LLVM

```
rm -rf llvm-project/build && mkdir -p llvm-project/build
cmake -G Ninja -S llvm-project/llvm -B llvm-project/build -DLLVM_ENABLE_PROJECTS="clang;lld" -DLLVM_BUILD_TOOLS=ON -DLLVM_ENABLE_ASSERTIONS=OFF -DCMAKE_BUILD_TYPE=Release -DLLVM_TARGETS_TO_BUILD="" -DLLVM_EXPERIMENTAL_TARGETS_TO_BUILD="Subleq" -DLLVM_DEFAULT_TARGET_TRIPLE="subleq-unknown-linux" -DLLVM_FORCE_VC_REPOSITORY="ESI" -DLLVM_FORCE_VC_REVISION=""

cd llvm-project/build
ninja llc clang llvm-mc lld llvm-objcopy llvm-ar llvm-ranlib llvm-nm llvm-readelf llvm-strip llvm-objdump
```

## Step 2: Install Linux Kernel Headers

```
cd ../../linux
make ARCH=subleq \
  CC=../llvm-project/build/bin/clang \
  LD=../llvm-project/build/bin/ld.lld \
  AR=../llvm-project/build/bin/llvm-ar \
  NM=../llvm-project/build/bin/llvm-nm \
  OBJCOPY=../llvm-project/build/bin/llvm-objcopy \
  INSTALL_HDR_PATH=../runtime/sysroot/kernel-headers \
  headers_install
```

## Step 3: Build and Install ESI C Runtime (uClibc-ng)

```
cd ../uclibc-ng
make ARCH=subleq defconfig

make ARCH=subleq \
  CC=../llvm-project/build/bin/clang \
  LD=../llvm-project/build/bin/ld.lld \
  AR=../llvm-project/build/bin/llvm-ar \
  NM=../llvm-project/build/bin/llvm-nm \
  PREFIX=../runtime/sysroot \
  STRIPTOOL=../llvm-project/build/bin/llvm-strip \
  DEVEL_PREFIX=/ \
  install_dev
```

## Step 4: Build ESI Core Runtimes (CPU, FPU, C++)

```
cd ../runtime
./build_and_install_runtime.sh
./build_libcxx.sh
ninja -C ./libcxx install
```

## Step 5: Build Busybox

```
cd ../busybox
make subleq_defconfig

make CC=../llvm-project/build/bin/clang \
     AR=../llvm-project/build/bin/llvm-ar \
     STRIP=../llvm-project/build/bin/llvm-strip

mkdir ../initramfs_root/bin
cp busybox ../initramfs_root/bin/busybox
```

## Step 6: Build ESI Linux

```
cd ../linux
export KBUILD_BUILD_USER="root"
export KBUILD_BUILD_HOST="eternal"

make ARCH=subleq \
  CC=../llvm-project/build/bin/clang \
  LD=../llvm-project/build/bin/ld.lld \
  AR=../llvm-project/build/bin/llvm-ar \
  NM=../llvm-project/build/bin/llvm-nm \
  OBJCOPY=../llvm-project/build/bin/llvm-objcopy \
  defconfig

make ARCH=subleq \
  CC=../llvm-project/build/bin/clang \
  LD=../llvm-project/build/bin/ld.lld \
  AR=../llvm-project/build/bin/llvm-ar \
  NM=../llvm-project/build/bin/llvm-nm \
  OBJCOPY=../llvm-project/build/bin/llvm-objcopy
```

## Step 7: Build Capsule and Run VM

```
cd ..
python3 tools/make_boot_image.py --stack-size 536870912 linux/vmlinux
./vm/vm linux/vmlinux.bootimage
```

Type `exit` when done to terminate the VM.

# Compiling and Running Your Own Software

Standard cross-compilation workflow. To get started quickly, we provide a convenience script (`clang_userspace.sh`) that sets up the environment and calls `clang`.

```
cat << 'EOF' > hello.c
#include <stdio.h>

int main() {
    printf("Hello, ESI world!\n");
    return 0;
}
EOF

tools/clang_userspace.sh hello.c
cp hello.elf initramfs_root/root
```

Then rebuild the `initramfs` and capsule:

```
cd linux
make ARCH=subleq \
  CC=../llvm-project/build/bin/clang \
  LD=../llvm-project/build/bin/ld.lld \
  AR=../llvm-project/build/bin/llvm-ar \
  NM=../llvm-project/build/bin/llvm-nm \
  OBJCOPY=../llvm-project/build/bin/llvm-objcopy

cd ..
python3 tools/make_boot_image.py --stack-size 536870912 linux/vmlinux
```

Boot the VM:

```
./vm/vm linux/vmlinux.bootimage
```

Once Linux is booted:

```
./hello.elf
```

# Technical Documentation

Provided for developers of today to understand the architecture and toolchain. None of this is needed for someone 1,000 years from now to revive a capsule and
run the software within.

- [ESI machine architecture reference](docs/machine_architecture.md)
- [LLVM backend port reference](docs/llvm_backend.md)
- [Linux kernel port reference](docs/esi_linux_port.md)

