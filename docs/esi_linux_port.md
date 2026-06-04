# Eternal Software Initiative Linux Kernel Port

This document provides a complete, self-contained reference for the Linux kernel port to the ESI One Instruction Set Computer (OISC). It covers every architecture-specific subsystem: boot flow, register map, interrupt handling, syscall dispatch, context switching, signal delivery, timekeeping, console I/O, framebuffer graphics, memory management, ELF loading, and the runtime library.

---

## Table of Contents

1.  [Architecture Overview](#1-architecture-overview)
2.  [Register Map and Memory Layout](#2-register-map-and-memory-layout)
3.  [Boot Sequence](#3-boot-sequence)
4.  [Interrupt Handling](#4-interrupt-handling)
5.  [Syscall Entry and Dispatch](#5-syscall-entry-and-dispatch)
6.  [Context Switching](#6-context-switching)
7.  [Process Management and Fork](#7-process-management-and-fork)
8.  [Signal Delivery and Return](#8-signal-delivery-and-return)
9.  [Timekeeping](#9-timekeeping)
10. [IRQ Flag Management](#10-irq-flag-management)
11. [Console and TTY](#11-console-and-tty)
12. [Keyboard Input](#12-keyboard-input)
13. [Framebuffer Console](#13-framebuffer-console)
14. [Memory Management (NOMMU)](#14-memory-management-nommu)
15. [ELF Loader and Relocations](#15-elf-loader-and-relocations)
16. [Runtime Library](#16-runtime-library)
17. [Kernel Configuration](#17-kernel-configuration)
18. [Linker Script](#18-linker-script)
19. [Traps and Debugging](#19-traps-and-debugging)
20. [File Inventory](#20-file-inventory)

---

## 1. Architecture Overview

Subleq is a One Instruction Set Computer where the sole operation is:

```
subleq(A, B, C):  m[B] -= m[A]; if m[B] <= 0 then PC = C else PC += 12
```

Each instruction is 12 bytes (three 32-bit words). Every high-level operation-addition, multiplication, bitwise logic, memory copies-must be decomposed into sequences of `subleq` instructions. The Linux kernel port runs on this architecture with the following characteristics:

| Property | Value |
|---|---|
| **Word size** | 32-bit |
| **Address space** | 1.5 GB (configurable) |
| **Addressing** | Byte-addressed, 4-byte aligned |
| **MMU** | None (NOMMU) |
| **Hardware registers** | None (all registers are memory-mapped) |
| **Interrupt model** | Single timer interrupt via VM |
| **SMP** | No (single CPU) |
| **Indirect addressing** | Subleq+ extension (bit 0 flag) |

The Subleq+ extension repurposes bit 0 of operand addresses as an indirection flag. When set, the VM dereferences the address to obtain the actual operand address. This eliminates self-modifying code, enabling fully re-entrant interrupt handlers and context switch code-a hard requirement for running Linux.

### Source Tree

All architecture-specific code lives under `linux/arch/subleq/`:

```
arch/subleq/
├── Kconfig                  # Architecture feature selection
├── Makefile                 # Build rules
├── configs/defconfig        # Default kernel configuration
├── include/asm/             # Architecture headers (41 files)
├── kernel/                  # Core kernel implementation
│   ├── head.S               # Boot entry point
│   ├── entry.S              # IRQ, syscall, context switch (3041 lines)
│   ├── setup.c              # Machine setup and early console
│   ├── irq.c                # C-level interrupt handler
│   ├── time.c               # Clocksource and timekeeping
│   ├── process.c            # Process/thread management
│   ├── signal.c             # Signal delivery and sigreturn
│   ├── syscall_entry.c      # Syscall dispatcher
│   ├── tty.c                # TTY driver
│   ├── keyboard.c           # Keyboard input driver
│   ├── fbcon.c              # Framebuffer console driver
│   ├── bitblit.c            # Framebuffer blit operations
│   ├── direct_putcs_asm.S   # Optimized character rendering
│   ├── binfmt_elf_subleq.c  # Custom ELF loader
│   ├── elf_process_relr_section.S  # RELR relocation engine
│   ├── traps.c              # Trap/exception stubs
│   ├── syscalls.c           # Syscall table
│   ├── vmlinux.lds.S        # Linker script
│   └── ...
├── mm/                      # Memory management
│   ├── init.c               # Zone initialization
│   └── nommu.c              # NOMMU memory allocator
└── lib/                     # Architecture-specific libraries
    ├── subleq_runtime.S     # Runtime (shifts, mul, div, etc.)
    └── subleq_runtime_softfloat.c  # Soft-float support
```

---

## 2. Register Map and Memory Layout

Since Subleq has no hardware registers, all "registers" are fixed memory-mapped locations in the first 272 bytes (68 words) of the address space. The kernel reserves this region via `memblock_reserve(0, 0x1000)`.

### 2.1 Complete Register Map

| Word | Byte Addr | Name | Category | Purpose |
|------|-----------|------|----------|---------|
| 0 | `0x00` | `INT_HANDLER` | Interrupt | Handler address (0 = disabled) |
| 1 | `0x04` | `INT_SAVED_PC` | Interrupt | VM saves PC here on interrupt |
| 2 | `0x08` | `INT_SAVED_HANDLER` | Interrupt | Saved handler when IRQs disabled |
| 3 | `0x0C` | `Z` | Core | Scratch zero register |
| 4 | `0x10` | `SP` | Core | Stack pointer |
| 5 | `0x14` | `RA` | Core | Return address scratch |
| 6 | `0x18` | - | - | Reserved |
| 7–23 | `0x1C`–`0x5C` | `R3`–`R19` | GPR | Callee-saved |
| 24 | `0x60` | `R20` | GPR | Return value (caller-saved) |
| 25–28 | `0x64`–`0x70` | `R21`–`R24` | GPR | Arguments 1–4 (caller-saved) |
| 29–35 | `0x74`–`0x8C` | `R25`–`R31` | GPR | Callee-saved |
| 36 | `0x90` | `ZERO` | Constant | Always 0 |
| 37 | `0x94` | `FP` | Core | Frame pointer (callee-saved) |
| 38 | `0x98` | `MINUS_ONE` | Constant | Always −1 |
| 39 | `0x9C` | `ONE` | Constant | Always +1 |
| 40–55 | `0xA0`–`0xDC` | `T0`–`T15` | Compiler | Temporaries (codegen-reserved) |
| 56 | `0xE0` | `INT_Z` | IRQ | Interrupt scratch (only register safe to use at IRQ entry) |
| 57 | `0xE4` | `INT_Z2` | IRQ | Running pointer for pt_regs population |
| 58 | `0xE8` | `SAVE_SP` | IRQ | Saved interrupted SP |
| 59 | `0xEC` | `SYSCALL_JMPTGT` | Syscall | Return jump target (saved/restored by IRQ) |
| 60 | `0xF0` | `SAVE_JMPTGT` | IRQ | Interrupt return PC |
| 61 | `0xF4` | `SW_Z` | Context | Context switch scratch |
| 62 | `0xF8` | `SW_Z2` | Context | Context switch second scratch |
| 63 | `0xFC` | `SYSCALL_SCRATCH` | Syscall | Syscall return pointer (saved/restored by IRQ) |
| 64 | `0x100` | `CLOCK_S_LO` | Clock | Low 32 bits of seconds (Unix epoch) |
| 65 | `0x104` | `CLOCK_S_HI` | Clock | High 32 bits of seconds |
| 66 | `0x108` | `CLOCK_NS` | Clock | Nanoseconds (0–999999999) |
| 67 | `0x10C` | - | Clock | Padding for `struct timespec` |

### 2.2 Register Isolation Strategy

Since all registers are global memory locations, the kernel must carefully partition their usage:

- **User/compiler registers** (`Z`, `SP`, `RA`, `R3`–`R31`, `FP`, `T0`–`T15`): Used by compiled code. The interrupt handler must save ALL of these into `pt_regs` before calling any C code.
- **Interrupt-only registers** (`INT_Z`, `INT_Z2`, `SAVE_SP`, `SAVE_JMPTGT`): Used exclusively during the IRQ entry/exit assembly in `entry.S`. Safe to clobber without saving because no compiler-generated code uses them.
- **Context switch registers** (`SW_Z`, `SW_Z2`): Used exclusively by `__switch_to` and `ret_from_fork`. Separate from `INT_Z`/`INT_Z2` so context switches work safely when interrupts are enabled.
- **Syscall registers** (`SYSCALL_JMPTGT`, `SYSCALL_SCRATCH`): Used by the syscall entry/exit trampoline. Saved and restored by the IRQ handler on the kernel stack to prevent corruption if an interrupt fires during a syscall return.

### 2.3 Memory Map

```
0x00000000 ┌─────────────────────────┐
           │  Boot Area / Registers  │  (0x1000 bytes reserved)
           │  Interrupt vectors      │
           │  Memory-mapped regs     │
           │  Clock registers        │
0x00001000 ├─────────────────────────┤  TEXT_START
           │  Kernel .text           │
           │  .rodata                │
           │  .data                  │
           │  .bss                   │
           │  .init (freed after boot)│
           ├─────────────────────────┤
           │  User/kernel heap       │
           │       ...               │
           │  (grows up via memblock)│
           ├─────────────────────────┤
           │                         │
           │  Available memory       │
           │                         │
0x5E700000 ├─────────────────────────┤  SUBLEQ_FB_ADDR
           │  Framebuffer            │  800×512×4 = 1,638,400 bytes
0x60000000 └─────────────────────────┘  subleq_memory_end (1.5 GB)
```

---

## 3. Boot Sequence

### 3.1 VM Boot

The VM starts with `PC = 0`. The boot image prepended by `tools/add_boot.py` occupies the first 4096 bytes and performs:

1. `subleq(0, 0, 12)` - Always branches to byte 12 (word 3)
2. Initializes `SP` by pre-storing the stack size value at word 4
3. Jumps to the kernel entry point at `_start` (byte `0x1000`)

### 3.2 Kernel Entry - `head.S`

`_start` in [head.S](linux/arch/subleq/kernel/head.S) performs:

1. **Switch to init_task's kernel stack**: Loads the address of `init_thread_union + THREAD_SIZE` into `SP`. The boot stack from the VM must not be used after this point-it may overlap with kernel memory.
2. **Jump to `subleq_start`**: An unconditional branch to the C entry point.

```asm
; SP = init_thread_union + THREAD_SIZE
.word   REG_Z, REG_Z, .+4
.word   .Linit_stack_top, REG_Z, .+4
.word   REG_SP, REG_SP, .+4
.word   REG_Z, REG_SP, .Ljump_start
```

The `init_thread_union` and `init_stack` symbols are defined in `head.S` (not the linker script) to avoid LLD issues with `. = symbol` syntax.

### 3.3 C Entry - `setup.c`

[subleq_start](linux/arch/subleq/kernel/setup.c#L115-L127) in `setup.c`:

1. **Clears BSS** using the optimized `__subleq_memset` (word-aligned fast-zero path)
2. **Clears per-CPU data** (important for `timer_bases` and other zero-initialized structures)
3. **Initializes kernel stack pointer** via `subleq_init_kernel_sp(&init_task)`
4. **Calls `start_kernel()`** - the generic Linux kernel entry point

### 3.4 Architecture Setup - `setup_arch()`

[setup_arch](linux/arch/subleq/kernel/setup.c#L134-L183):

1. **Registers early console** - Uses `__subleq_putchar` for immediate boot output
2. **Prints boot banner** - "Eternal Software Initiative Linux" with CPU identification
3. **Configures command line** from `CONFIG_CMDLINE`
4. **Sets up memblock** - Adds 0 to `0x60000000` (1.5 GB), reserves kernel text/data, low memory (`0x0`–`0x1000`), and framebuffer region
5. **Calls `paging_init()`** to set up memory zones

---

## 4. Interrupt Handling

The Subleq VM fires a timer interrupt periodically (every ~500K instruction cycles). The VM's interrupt mechanism:

1. Checks if `m[0]` (INT_HANDLER) is non-zero
2. Saves current PC to `m[1]` (INT_SAVED_PC)
3. Jumps to `m[0]`

### 4.1 Interrupt Entry - `entry.S`

[subleq_irq_entry](linux/arch/subleq/kernel/entry.S) is a 1024-line assembly routine organized into distinct phases:

#### Phase −1: Self-Interrupt Detection

Checks if `INT_SAVED_PC` falls within `[subleq_irq_entry, subleq_irq_entry_end)`. This handles the hazard window in Phase 4 where interrupts are re-enabled before the final jump completes. If detected, the handler returns immediately via indirect jump. This is safe because:
- `INT_Z` is IRQ-only scratch
- The timer counter just reset (~300K instructions of headroom)
- The lost tick is harmless

#### Phase 0a: Disable Interrupts

Saves `m[0]` to `m[8]` (INT_SAVED_HANDLER), then clears `m[0]` to prevent nested interrupts. Uses only `INT_Z` as scratch.

#### Phase 0b: SP Validity Check

**Critical for OISC**: SP updates in Subleq are non-atomic - SP is cleared to 0 before being set to a new value. If the interrupt fires between these two operations, SP is 0 or garbage. The handler checks `SP >= 1` and returns immediately if invalid.

#### Phase 0c–1: Kernel vs User Mode Detection

Saves interrupted SP to `SAVE_SP`, then determines whether the interrupt hit kernel or user code by checking if SP falls within the current task's kernel stack range:

- **Check 1**: `SP < subleq_kernel_sp` (below stack top)
- **Check 2**: `SP >= subleq_kernel_sp - THREAD_SIZE` (above stack base)

If both pass → kernel mode, keep current SP. Otherwise → user mode, switch to `subleq_kernel_sp + 1268` (calculated so that after pushing `SYSCALL_JMPTGT`, `SYSCALL_SCRATCH`, and allocating `pt_regs`, the `pt_regs` base lands exactly at `task_pt_regs(current)`).

#### Phase 2: Build `pt_regs`

Saves all registers into a 236-byte `pt_regs` structure on the kernel stack using **negated storage**: `[dest] = -value`. This is fundamentally efficient for Subleq because `subleq(A, B, C)` naturally stores `-m[A]` at `B`. The C code accesses values via `PT_REG_GET()` which negates back to get the logical positive value. This eliminates ~100 instructions per interrupt compared to double-negation.

The saved registers include:
- `R3`–`R31`, `FP`, `SP`, `RA`, `PC` (full GPR set)
- `T0`–`T15`, `Z` (compiler temporaries, needed for signal handling)
- `syscall_nr` set to −1 (marks this as an interrupt, not a syscall)

A running pointer (`INT_Z2`) starts at `SP` and increments by 4 for each field, using the pattern:
```asm
.word   .Lconst_neg4, INT_Z2, .+4           ; advance pointer
.word   INT_Z2 | INDIRECT, INT_Z2 | INDIRECT, .+4  ; [ptr] = 0
.word   REG_Rx, INT_Z2 | INDIRECT, .+4      ; [ptr] = -Rx
```

#### C-Level Handler Call

Sets `R21 = SP` (pt_regs pointer) and calls `subleq_do_IRQ(regs)` via stack-based call convention.

#### Phase 2b: Work Loop (ColdFire Pattern)

After `subleq_do_IRQ` returns, the assembly calls `subleq_do_work(regs)` in a loop. This C function ([irq.c](linux/arch/subleq/kernel/irq.c#L173-L263)) handles:

1. **Kernel preemption**: If `CONFIG_PREEMPTION`, calls `preempt_schedule_irq()` when preempt_count is 0 and `need_resched()` is set
2. **User-mode scheduling**: Calls `schedule()` with IRQs enabled
3. **Signal delivery**: Calls `do_notify_resume(regs)` which may modify `pt_regs` to redirect execution to a signal handler

Returns non-zero if work was done (loop again) or 0 (safe to return).

#### Phase 3: Restore Registers

Reads `SP` and `PC` from `pt_regs` (they may have been modified by signal delivery), then restores all GPRs, T-registers, and Z from pt_regs. Deallocates pt_regs, restores `SYSCALL_SCRATCH` and `SYSCALL_JMPTGT` from the kernel stack, and restores the interrupted SP from `SAVE_SP`.

#### Phase 4: Re-enable and Return

Re-enables interrupts by copying `INT_SAVED_HANDLER` back to `INT_HANDLER`, then performs an indirect jump to `SAVE_JMPTGT`. The Phase −1 self-interrupt detection handles the hazard window between re-enabling and the final jump.

### 4.2 C-Level IRQ Handler - `irq.c`

[subleq_do_IRQ](linux/arch/subleq/kernel/irq.c#L63-L142) wraps interrupt processing:

1. **`irq_enter()`** - Enters hardirq context
2. **Timer tick advancement** - Computes elapsed wall-clock ticks using a fast 32-bit incremental loop that avoids expensive 64-bit multiplication:
   ```c
   for (;;) {
       u32 next_ns = last_ns + tick_ns;
       if (next_ns >= NSEC_PER_SEC) { next_ns -= NSEC_PER_SEC; next_s++; }
       if (lo > next_s || (lo == next_s && ns >= next_ns)) {
           ticks++; last_s = next_s; last_ns = next_ns;
       } else break;
   }
   if (ticks > 0) legacy_timer_tick(ticks);
   ```
   Typically iterates 0–1 times. This is critical because timer interrupts fire by instruction count, not real time.
3. **`irq_exit()`** - May trigger softirqs
4. **Restores `irq_regs`**

### 4.3 IRQ Initialization - `init_IRQ()`

[init_IRQ](linux/arch/subleq/kernel/irq.c#L147-L158) stores the `subleq_irq_entry` address into `m[2]` (INT_SAVED_HANDLER). Interrupts remain disabled (`m[0] = 0`) until `local_irq_enable()` is first called by the kernel.

---

## 5. Syscall Entry and Dispatch

### 5.1 Assembly Trampoline - `entry.S`

Since Subleq has no hardware `syscall` instruction, syscalls are implemented as C function calls to `__subleq_syscall` which is linked by the C library. The assembly trampoline in [entry.S](linux/arch/subleq/kernel/entry.S#L2016) (the `__subleq_syscall` symbol):

1. **Disables interrupts** - Saves `m[0]` to a local, clears `m[0]`. Prevents context switch during state saving.
2. **Saves userspace SP, FP, RA** to global variables and to pt_regs
3. **Switches to kernel stack** - Loads `subleq_kernel_sp`
4. **Saves all GPRs** (`R3`–`R31`) to pt_regs with negated storage
5. **Loads stack arguments** (args 5–6) from the userspace stack
6. **Re-enables interrupts**
7. **Calls `__subleq_syscall_c`** with `(nr, a1, a2, a3, a4, a5, a6)`
8. **Disables interrupts** for return
9. **Restores userspace SP, FP** from saved globals
10. **Returns** via saved RA (NOT from stack, since vfork children share the parent's stack)

### 5.2 C Dispatcher - `syscall_entry.c`

[__subleq_syscall_c](linux/arch/subleq/kernel/syscall_entry.c#L65-L292):

1. **Saves syscall metadata** to `task_pt_regs(current)`: syscall number, all 6 original arguments (for restart)
2. **Validates syscall number** - Returns `-ENOSYS` for out-of-range or unimplemented
3. **Executes syscall** with a restart loop for `-ERESTARTNOINTR` (used by `wait_for_vfork_done()`), including `cond_resched()` to let the child run
4. **Calls `do_signal(regs)`** after execution for signal delivery
5. **Handles `-ERESTART_RESTARTBLOCK`** by calling `restart_block->fn()`
6. **Pre-return work** - Checks `need_resched()`, signals, and `TIF_NOTIFY_RESUME` (critical for fput/file close via task_work)

### 5.3 Kernel Stack Pointer - `subleq_kernel_sp`

Each task has its own kernel stack pointer, computed by [subleq_init_kernel_sp](linux/arch/subleq/kernel/syscall_entry.c#L303-L316):

```c
subleq_kernel_sp = task_stack_page(tsk) + THREAD_SIZE - sizeof(struct pt_regs) - 1024;
```

The 1024-byte margin accommodates deep kernel call chains (particularly `do_signal()` → `get_signal()` path). This global is updated during every context switch by `__switch_to`.

---

## 6. Context Switching

### 6.1 `__switch_to` - `entry.S`

[__switch_to](linux/arch/subleq/kernel/entry.S#L1066-L1523) switches between two tasks using Subleq+ indirect addressing for full re-entrancy. Arguments: `R21 = prev`, `R22 = next`. Returns: `R20 = prev`.

**Steps:**

1. **Allocate switch_stack** (100 bytes = 25 registers × 4): `SP -= 100`
2. **Save callee-saved registers** (`R3`–`R19`, `R20`, `R25`–`R31`) to switch_stack using a running pointer in `SW_Z2`
3. **Save SP and FP** to `prev->thread.sp` and `prev->thread.fp` using indirect addressing into task_struct
4. **Update `__current_task`** = next (global volatile pointer, since `CONFIG_THREAD_INFO_IN_TASK`)
5. **Update `subleq_kernel_sp`** for the next task: `next->stack + THREAD_SIZE - sizeof(pt_regs) - 1024`
6. **Load SP and FP** from `next->thread.sp` and `next->thread.fp`
7. **Restore callee-saved registers** from next's switch_stack
8. **Deallocate switch_stack**: `SP += 100`
9. **Pop return address** and jump

### 6.2 `switch_stack` Structure

Defined in [switch_context.h](linux/arch/subleq/include/asm/switch_context.h):

```c
struct switch_stack {
    unsigned long r3, r4, ..., r19;  // 17 callee-saved
    unsigned long r20;                // Must be saved for vfork (CLONE_VM)
    unsigned long r25, ..., r31;      // 7 callee-saved
};  // Total: 25 words = 100 bytes
```

`R20` is technically caller-saved, but must be preserved across context switches because vfork children share the parent's memory (including the `R20` memory location). Without saving it in switch_stack, the child's writes to `R20` would clobber the parent's syscall return value.

### 6.3 Stack Layout per Task

```
[high address]   pt_regs (236 bytes)
                 ret_from_fork return address (4 bytes)
                 switch_stack (100 bytes)   <-- thread.sp points here
[low address]    Remaining kernel stack space
```

---

## 7. Process Management and Fork

### 7.1 `copy_thread` - `process.c`

[copy_thread](linux/arch/subleq/kernel/process.c#L220-L289) sets up the stack for a new thread:

1. Pushes `ret_from_fork` as the return address below pt_regs
2. Allocates a zeroed switch_stack below the return address
3. Sets `thread.sp` pointing to switch_stack

For **kernel threads**: pt_regs is zeroed; `r3 = fn`, `r21 = fn_arg`, `pc = 0` (kernel thread marker).

For **user threads** (fork): copies parent's pt_regs; sets `R20 = 0` (child fork return); sets user stack if provided.

Both paths call `syscall_wont_restart(childregs)` to prevent Hazard 1342 (false syscall restart).

### 7.2 `ret_from_fork` - `entry.S`

[ret_from_fork](linux/arch/subleq/kernel/entry.S#L1539-L1924) is the first code a new thread executes after being scheduled:

1. **Copy R20 to R21** (prev task for `schedule_tail`)
2. **Read pt_regs.pc** to distinguish thread type:
   - `pc == 0` → kernel thread → call `kernel_thread_helper(prev)`
   - `pc != 0` → user thread → call `ret_to_user_prep(prev)`, then restore all GPRs from pt_regs and jump to user PC

### 7.3 `start_thread` - `process.c`

Called after `execve()` to configure the new program's registers:

```c
void start_thread(struct pt_regs *regs, unsigned long pc, unsigned long sp) {
    memset(regs, 0, sizeof(*regs));    // -0 = 0, safe for negated storage
    PT_REG_SET(regs, pc, pc);
    PT_REG_SET(regs, sp, sp);
    syscall_wont_restart(regs);         // Prevent false restart
}
```

### 7.4 `user_mode()` Detection

[user_mode](linux/arch/subleq/include/asm/ptrace.h#L160-L218) determines if the interrupted context was user or kernel mode. **It cannot use PC** because runtime library functions (`__subleq_mul`, `__subleq_and`, etc.) reside in kernel text but execute on behalf of userspace. Instead, it checks whether SP falls within the current task's kernel stack range:

```c
unsigned long kstack_base = *(unsigned long *)((char *)__current_task + SUBLEQ_TASK_STACK_OFFSET);
unsigned long kstack_top = kstack_base + SUBLEQ_THREAD_SIZE;
return (sp < kstack_base || sp >= kstack_top);
```

Special cases: If PC is within `__subleq_syscall`, `subleq_irq_entry`, or `ret_from_fork`→`__subleq_syscall` range, it's always kernel mode (handles the race where SP was restored to user value but the final jump hasn't executed).

---

## 8. Signal Delivery and Return

### 8.1 Signal Frame

When delivering a signal, [setup_rt_frame](linux/arch/subleq/kernel/signal.c#L252-L338) pushes an `rt_sigframe` onto the user stack:

```c
struct rt_sigframe {
    void *pretcode;               // Return trampoline address
    int sig;                      // Signal number
    struct siginfo __user *pinfo;
    void __user *puc;
    struct siginfo info;
    struct ucontext uc;           // Saved regs, signal mask
};
```

Register setup for the handler:
- `PC` = signal handler address
- `SP` = frame address − 4 (return address slot)
- `R21` = signal number (first argument)
- `R22` = `&frame->info` (for `SA_SIGINFO`)
- `R23` = `&frame->uc` (for `SA_SIGINFO`)
- `RA` = `ret_from_user_rt_signal` trampoline

### 8.2 Signal Context Save/Restore

`save_sigcontext` copies all registers from pt_regs to the sigcontext using `PT_REG_GET` (negation). The full set includes R3–R31, FP, SP, RA, PC, T0–T15, Z, and all 6 original syscall arguments (for restart after handler returns).

### 8.3 `sys_rt_sigreturn`

[sys_rt_sigreturn](linux/arch/subleq/kernel/signal.c#L512-L648) restores context after the signal handler returns:

1. Locates the signal frame at `SP - 4`
2. Restores signal mask and all registers from the sigcontext
3. **Handles syscall restart**: If the restored context contains `-ERESTARTNOINTR`, `-ERESTARTSYS`, or `-ERESTARTNOHAND` with `syscall_nr >= 0`, it re-executes the original syscall using the preserved `orig_a1`–`orig_a6` arguments
4. Invalidates `restart_block` to prevent stale restart
5. Marks `syscall_wont_restart` to prevent double-restart

### 8.4 Syscall Restart

[handle_restart](linux/arch/subleq/kernel/signal.c#L349-L405) converts restart error codes based on signal state:

| Error Code | With Handler | Without Handler |
|---|---|---|
| `ERESTARTNOHAND` | → `EINTR` | → restart |
| `ERESTARTSYS` | → `EINTR` (unless `SA_RESTART`) | → restart |
| `ERESTARTNOINTR` | → restart | → restart |
| `ERESTART_RESTARTBLOCK` | preserved for sigreturn | calls `restart_block->fn()` |

---

## 9. Timekeeping

### 9.1 Clock Registers

The VM provides wall-clock time through memory-mapped registers at words 64–66:

| Register | Byte Addr | Contents |
|---|---|---|
| `CLOCK_S_LO` | 256 | Low 32 bits of seconds since epoch |
| `CLOCK_S_HI` | 260 | High 32 bits of seconds since epoch |
| `CLOCK_NS` | 264 | Nanoseconds (0–999999999) |

These are updated continuously by the VM, not just at interrupts.

### 9.2 Clocksource - `time.c`

The [subleq_clocksource](linux/arch/subleq/kernel/time.c#L88-L94) reads nanoseconds since boot:

```c
static u64 subleq_read_clock(struct clocksource *cs) {
    u64 seconds = ((u64)hi << 32) | lo;
    return subleq_seconds_to_ns(seconds) + ns;
}
```

**Performance optimization**: A seconds-to-nanoseconds *cache* avoids the extremely expensive 64-bit multiplication (16K+ Subleq instructions per multiply). The seconds value changes at most once per second, so within a given second every read reduces to a comparison and addition:

```c
static inline u64 subleq_seconds_to_ns(u64 seconds) {
    if (likely(seconds == cached_seconds_val))
        return cached_seconds_ns;
    cached_seconds_val = seconds;
    cached_seconds_ns = seconds * NSEC_PER_SEC;
    return cached_seconds_ns;
}
```

Registered at 1 GHz (nanosecond resolution), rating 400.

### 9.3 `sched_clock()`

Returns monotonic nanoseconds since boot by subtracting `boot_ns` (captured on first call during `time_init()`).

### 9.4 Entropy Seeding

[time_init](linux/arch/subleq/kernel/time.c#L129-L164) seeds the kernel RNG with 256 bits from 4 consecutive clock reads (varying nanosecond precision provides jitter). With `random.trust_bootloader=on`, this fully initializes the CRNG and eliminates "uninitialized urandom read" warnings.

### 9.5 `read_persistent_clock64()`

Reads wall-clock time from the VM's clock registers for the kernel's timekeeping initialization.

---

## 10. IRQ Flag Management

[irqflags.h](linux/arch/subleq/include/asm/irqflags.h) implements `local_irq_enable/disable`:

### Key Design: Nested Interrupt Prevention

`arch_local_irq_enable()` checks **both** hardirq AND softirq context before actually enabling hardware interrupts:

```c
static inline void arch_local_irq_enable(void) {
    if (*SUBLEQ_INT_HANDLER == 0 && !__subleq_in_interrupt()) {
        *SUBLEQ_INT_HANDLER = *SUBLEQ_INT_SAVED_HANDLER;
    }
}
```

This is critical because:
- `irq_exit()` decrements the hardirq count **before** calling `invoke_softirq()`
- `handle_softirqs()` calls `local_irq_enable()` internally
- Without the softirq check, interrupts would be re-enabled during softirq processing, causing nested entry into the handler

### Atomic Disable

`arch_local_irq_disable()` clears `INT_HANDLER` **first**, then saves to `INT_SAVED_HANDLER`. The reverse order would create a window where an interrupt fires between save and clear, corrupting the saved state.

### `__subleq_in_interrupt()` - Lightweight Context Check

Reads `preempt_count` directly from `__current_task` at hardcoded offset 4 (thread_info is at offset 0 of task_struct). Checks bits 8–19 (softirq + hardirq masks). This avoids `#include <linux/preempt.h>` which creates circular dependencies, and avoids the ~200-instruction cost of `__subleq_and`.

---

## 11. Console and TTY

### 11.1 Early Console - `setup.c`

The earliest console output uses `__subleq_putchar` (a compiler intrinsic that emits a single `subleq(addr, -4, next)` instruction). Registered with `CON_PRINTBUFFER | CON_BOOT` flags so boot messages are buffered and replayed.

Disabled when the proper TTY console takes over (flag `subleq_early_disabled`).

### 11.2 TTY Driver - `tty.c`

[tty.c](linux/arch/subleq/kernel/tty.c) provides `/dev/ttyS0`:

- **Output**: `subleq_tty_write()` sends each byte via `__subleq_putchar`. No `\r\n` expansion (handled by n_tty line discipline).
- **Input**: Characters are injected by the keyboard driver via `subleq_tty_inject_char()` + `subleq_tty_push()`.
- **Console**: A console driver wraps the TTY for `printk` output, with `\n` → `\r\n` expansion.
- Registered as `device_initcall`, major 4 / minor 64 (standard serial port).

---

## 12. Keyboard Input

### 12.1 Driver Architecture - `keyboard.c`

[keyboard.c](linux/arch/subleq/kernel/keyboard.c) uses timer-based polling at 100 Hz (`HZ/100 = 10ms`):

```c
static void subleq_kbd_poll(struct timer_list *t) {
    while ((c = __subleq_getchar()) != 0) { /* process key events */ }
    mod_timer(&subleq_kbd_timer, jiffies + SUBLEQ_KBD_POLL_INTERVAL);
}
```

### 12.2 Dual-Mode Operation

**Framebuffer mode** (detected by absence of `console=ttyS` in command line):
- VM sends SDL scancodes: positive = keydown, negative = keyup
- SDL scancodes are USB HID usage codes, mapped to Linux `KEY_*` via a 256-entry table copied from `drivers/hid/hid-input.c`
- Fed into the Linux input subsystem (`input_report_key` / `input_sync`)
- The VT keyboard layer handles keymaps, shift states, Ctrl combos, F-keys

**Serial mode** (fallback for text-only VM):
- Raw ASCII bytes injected into the foreground VT via `tty_insert_flip_char`
- Also injected into `ttyS0` for console input

### 12.3 Auto-Repeat

`EV_REP` is enabled on the input device with `REP_DELAY = 500ms` (overriding the kernel default of 250ms).

---

## 13. Framebuffer Console

### 13.1 Framebuffer Layout

Defined in [subleq_fb.h](linux/arch/subleq/include/asm/subleq_fb.h):

| Parameter | Value |
|---|---|
| Resolution | 800 × 512 |
| Color depth | 32 bpp (XRGB8888) |
| Size | 1,638,400 bytes |
| Address | `0x60000000 - size` = `0x5E700000` |

The framebuffer is memory-mapped directly in the VM's address space. Writing to these addresses immediately updates the display.

### 13.2 Console Driver - `fbcon.c`

The [fbcon.c](linux/arch/subleq/kernel/fbcon.c) is a modified copy of the upstream `drivers/video/fbdev/core/fbcon.c` (3445 lines), with Subleq-specific optimizations. Conditionally compiled with `CONFIG_FRAMEBUFFER_CONSOLE`.

### 13.3 Optimized Character Rendering - `direct_putcs_asm.S`

[direct_putcs_asm.S](linux/arch/subleq/kernel/direct_putcs_asm.S) (102KB) provides hand-optimized assembly for rendering characters directly to the framebuffer, bypassing the generic fbcon blit path. This is critical because every operation expands to many subleq instructions.

### 13.4 Bitblit - `bitblit.c`

[bitblit.c](linux/arch/subleq/kernel/bitblit.c) implements framebuffer blit operations (copy, fill, cursor rendering) optimized for the Subleq architecture.

### 13.5 Early Boot Log Replay

A known issue with `dummy_con`: early boot messages printed before `fbcon` initializes are lost because `dummy_con` discards all print requests. The workaround is `dmesg > /dev/tty0` early in the init script.

---

## 14. Memory Management (NOMMU)

### 14.1 NOMMU Configuration

The kernel is configured with `CONFIG_MMU=n` (NOMMU). There are no page tables, no virtual addresses-all addresses are physical. Key implications:

- All processes share the same address space
- No memory protection between user and kernel
- ELF binaries must be fully relocated at load time (position-independent)
- `mmap` allocates contiguous physical memory

### 14.2 Memory Initialization - `mm/init.c`

[paging_init](linux/arch/subleq/mm/init.c#L35-L64):

1. Sets `high_memory` to `subleq_memory_end` (1.5 GB)
2. Allocates `empty_zero_page` via memblock
3. All memory goes into `ZONE_NORMAL` (no DMA/highmem zones)
4. `ARCH_FORCE_MAX_ORDER = 13` allows contiguous allocations up to 128 MB (2^13 × 16KB pages)

### 14.3 Page Size

`PAGE_SHIFT = 14` → `PAGE_SIZE = 16384` (16 KB pages). This larger page size reduces page table overhead and provides larger contiguous allocations for NOMMU ELF loading.

### 14.4 `nommu.c`

[nommu.c](linux/arch/subleq/mm/nommu.c) (49KB) provides the NOMMU memory allocator, handling `mmap`, `munmap`, and memory region management without hardware MMU support.

---

## 15. ELF Loader and Relocations

### 15.1 Why a Custom Loader?

The standard Linux `binfmt_elf.c` assumes MMU-based virtual memory for segment loading, and cannot handle the unique requirements of Subleq OISC binaries:

1. **NOMMU**: There are no page tables. All PT_LOAD segments must be loaded into contiguous physical memory and relocated to their actual load addresses.
2. **Extreme relocation density**: Every 12-byte `subleq(A, B, C)` instruction contains up to 3 absolute addresses. A typical binary has more relocations than instructions-`libc.so` alone has 600K+ relocations.
3. **Kernel runtime sharing**: Subleq runtime functions (`__subleq_mul`, `__subleq_and`, `__subleq_shl`, etc.) are linked into the kernel image. User binaries reference them as external symbols, but there is no traditional dynamic linker (`ld.so`). The kernel loader must resolve these directly.
4. **Custom relocation type**: `R_SUBLEQ_NEG32` (type 200) is a Subleq-specific relocation for negated absolute addresses (`-(S + A)`), used by the compiler for efficient subleq codegen patterns.

### 15.2 Binary Format Requirements

[binfmt_elf_subleq.c](linux/arch/subleq/kernel/binfmt_elf_subleq.c) (2244 lines) accepts only:
- **ELF32** (`ELFCLASS32`)
- **ET_DYN** (PIE / shared library) - `ET_EXEC` is rejected. The toolchain produces only PIE executables.
- **EM_SUBLEQ** machine type
- **Non-zero entry point** (shared libraries with `e_entry == 0` are rejected as non-executable)

### 15.3 Two-Pass Library Loading Algorithm

The loader uses a **two-pass** approach to handle circular dependencies between shared libraries:

```
Phase 1: Load all libraries (segments only, collect symbols)
  For each DT_NEEDED library:
    1. Load PT_LOAD segments into contiguous memory via vm_mmap()
    2. Build symbol table (export all global FUNC/OBJECT symbols)
    3. Skip relocations (symbols from later libraries not yet available)
    4. Recursively load transitive DT_NEEDED dependencies

Phase 2: Apply deferred relocations
  For each loaded library (in load order):
    1. Pre-scan all undefined symbols → resolve against kernel + hash table
    2. Process SHT_REL sections (R_386_32, R_386_RELATIVE, R_SUBLEQ_NEG32)
    3. Process SHT_RELR sections (packed relative relocations)

Phase 3: Load and relocate the main executable
  1. Load PT_LOAD segments
  2. Apply relocations (all library symbols now available)
```

### 15.4 Symbol Resolution

Symbol resolution follows a two-tier hierarchy:

**Tier 1 - Kernel runtime symbols** (binary search, O(log n)):

Over 200 functions are built into the kernel and shared with userspace. The `kernel_runtime_symbols[]` table is sorted alphabetically for binary search. Categories include:

| Category | Examples | Count |
|---|---|---|
| **Integer arithmetic** | `__subleq_mul`, `__subleq_sdivrem`, `__subleq_udivrem` | 5 |
| **64-bit arithmetic** | `__divdi3`, `__moddi3`, `__udivdi3`, `__umoddi3` | 4 |
| **Bitwise operations** | `__subleq_and`, `__subleq_or`, `__subleq_xor` + 31 constant-mask variants each | ~96 |
| **Shift operations** | `__subleq_shl`, `__subleq_srl`, `__subleq_sra` + 31 constant-shift variants each | ~96 |
| **Sub-word access** | `__subleq_lb`, `__subleq_sb`, `__subleq_lh`, `__subleq_sh` + byte-position variants | ~16 |
| **Memory operations** | `__subleq_memcpy`, `__subleq_memset`, `__subleq_memmove` + aligned variants | 6 |
| **Soft-float** | `__adddf3`, `__muldf3`, `__fixdfsi`, `__floatsidf`, etc. | ~40 |
| **Syscall entry** | `__subleq_syscall` | 1 |

This design avoids duplicating ~2.4MB of runtime code in every binary. User binaries call these kernel functions directly (they execute in user context despite residing in kernel text).

**Tier 2 - Library symbols** (DJB2 hash table, O(1) average):

Symbols exported by shared libraries are stored in an 8192-entry open-addressing hash table using DJB2 hashing. DJB2 was chosen over FNV-1a because its `hash * 33 + c` (implemented as `(hash << 5) + hash + c`) uses shifts instead of multiplication-12× faster per character on Subleq.

Hash entries store **pointers** into the library's string table (not copies), reducing per-entry memory from 256 bytes to 12 bytes (~96KB total table).

**Pre-scan optimization**: Before processing relocations, ALL undefined symbols are resolved eagerly into a per-symbol cache array:
- `cache[i] = 0` → defined symbol (just add `load_offset`)
- `cache[i] = 1` → unresolved (weak → zero, else warning)
- `cache[i] > 1` → resolved address

This moves hash lookups out of the 42K-iteration hot loop, where the per-relocation fast path reduces to a cache read + integer addition.

### 15.5 Relocation Types

| Type | ID | Formula | Usage |
|---|---|---|---|
| `R_386_32` | 1 | `*patch += sym_value + load_offset` | Absolute address references |
| `R_386_RELATIVE` | 8 | `*patch += load_offset` | PIC base-relative addresses |
| `R_SUBLEQ_NEG32` | 200 | `*patch -= sym_value + load_offset` | Negated addresses (for register storage patterns) |

**Weak symbol handling**: Unresolved weak symbols (`STB_WEAK`) have their patch sites zeroed to prevent stale link-time values from leaking into runtime.

### 15.6 RELR Compression - `elf_process_relr_section.S`

RELR (Packed Relative Relocations) is a space-efficient encoding for `R_*_RELATIVE` relocations. It achieves 90–98% space savings over traditional REL format.

The RELR section consists of two entry types:
- **Address entries** (even values): Set the base relocation address
- **Bitmap entries** (odd values): Each set bit at position N means "apply relative relocation at `base + N*4`"

[elf_process_relr_section.S](linux/arch/subleq/kernel/elf_process_relr_section.S) (~40KB) is a hand-optimized Subleq assembly implementation. Key optimizations:

- **Early-exit bit-peeling**: LSB extraction with checkpoints after bits 8, 16, 24 saves ~100 instructions for typical sparse bitmaps
- **Unrolled table-driven bitmap loop**: Avoids expensive shift-per-bit patterns
- **Approximate counter**: Uses `nentries * 11` estimate (~11 relocs per RELR entry on average) instead of an exact counter, saving cycles per entry
- **Dedicated T-register mapping**: `T0`–`T9` scratchpad minimizes stack traffic

### 15.7 Stack, Heap, and Memory Setup

After loading and relocating:

1. **Stack**: Allocated via `vm_mmap()`, default 1MB (or from `PT_GNU_STACK` p_memsz). Stack layout follows the standard ELF ABI:
   ```
   [high] strings ("arg0\0arg1\0...env0\0env1\0...")
          alignment padding
          auxv[]: {AT_PAGESZ, PAGE_SIZE}, {AT_NULL, 0}
          envp[]: pointers + NULL
          argv[]: pointers + NULL
   [SP]   argc
   ```

2. **Heap**: 1MB pre-allocated region for `brk()`/`sbrk()`. The `mm->context.end_brk` field tracks the upper limit. Larger allocations use `mmap()` which allocates dynamically.

3. **Memory ranges**: `start_data` is set to `stack_base` (not the actual data segment) to prevent unsigned wraparound in NOMMU `task_statm()` which computes `(start_stack - start_data) >> PAGE_SHIFT`.

### 15.8 Differences from Standard Linux ELF Loading

| Aspect | Standard `binfmt_elf.c` | Subleq `binfmt_elf_subleq.c` |
|---|---|---|
| **MMU** | Maps segments to virtual addresses | Allocates contiguous physical memory, relocates |
| **Dynamic linker** | `ld.so` handles symbol resolution | Kernel performs all symbol resolution in-kernel |
| **Runtime functions** | Provided by `libc.so` / `libgcc_s.so` | 200+ functions built into kernel, shared via direct calls |
| **Relocation volume** | Hundreds to thousands | Hundreds of thousands (every instruction word is an address) |
| **Custom reloc** | None | `R_SUBLEQ_NEG32` for negated address storage |
| **RELR processing** | C implementation | Hand-optimized Subleq assembly (~40KB) |
| **Symbol lookup** | `dlsym` / PLT/GOT | Binary search (kernel) + DJB2 hash table (libraries) |
| **Heap** | On-demand via page faults | Pre-allocated 1MB region |
| **ET_EXEC** | Supported | Rejected (PIE-only) |

---

## 16. Runtime Library

### 16.1 Kernel Runtime - `lib/subleq_runtime.S`

[subleq_runtime.S](linux/arch/subleq/lib/subleq_runtime.S) (2.4MB) provides software implementations of operations impossible in a one-instruction architecture:

| Category | Functions |
|---|---|
| **Arithmetic** | `__subleq_mul`, `__subleq_sdivrem`, `__subleq_udivrem` |
| **64-bit** | `__divdi3`, `__moddi3`, `__udivdi3`, `__umoddi3` |
| **Bitwise** | `__subleq_and`, `__subleq_or`, `__subleq_xor` |
| **Shifts** | `__subleq_shl`, `__subleq_srl`, `__subleq_sra`, `__ashldi3`, `__lshrdi3`, `__ashrdi3` |
| **Sub-word** | `__subleq_lb/sb` (byte), `__subleq_lh/sh` (halfword) |
| **Memory** | `__subleq_memcpy`, `__subleq_memset`, `__subleq_memmove` |

The kernel's `arch/subleq/include/asm/string.h` aliases `memcpy` → `__subleq_memcpy`, `memset` → `__subleq_memset`, `memmove` → `__subleq_memmove` to use the optimized assembly implementations.

### 16.2 Soft-Float - `lib/subleq_runtime_softfloat.c`

[subleq_runtime_softfloat.c](linux/arch/subleq/lib/subleq_runtime_softfloat.c) (58KB) provides software floating-point emulation for any kernel code that requires it.

---

## 17. Kernel Configuration

### 17.1 Architecture Features - `Kconfig`

Key [Kconfig](linux/arch/subleq/Kconfig) selections:

| Config | Purpose |
|---|---|
| `MMU=n` | NOMMU architecture |
| `THREAD_INFO_IN_TASK` | thread_info embedded in task_struct (vs stack base) |
| `GENERIC_ATOMIC64` | Software 64-bit atomics |
| `LEGACY_TIMER_TICK` | Uses `legacy_timer_tick()` for jiffies |
| `UACCESS_MEMCPY` | User access via memcpy (no MMU protection) |
| `SET_FS` | Enables `set_fs()` for NOMMU uaccess |
| `HAVE_PREEMPT_LAZY` | Supports lazy preemption |
| `ARCH_SUPPORTS_LTO_CLANG` | Clang LTO compatible |
| `ARCH_FORCE_MAX_ORDER=13` | Up to 128MB contiguous allocations |
| `PGTABLE_LEVELS=1` | Minimal (dummy) page tables |
| `HZ=100` | 100 Hz timer (10ms tick) |

### 17.2 Defconfig Highlights

- `CONFIG_PREEMPT=y` - Full preemption
- `CONFIG_FRAMEBUFFER_CONSOLE=y` - Graphical console
- `CONFIG_NET=y`, `CONFIG_INET=y` - TCP/IP networking
- `CONFIG_BINFMT_ELF_SUBLEQ=y` - Custom ELF loader
- `random.trust_bootloader=on` - Trust entropy from clock seeding

---

## 18. Linker Script

[vmlinux.lds.S](linux/arch/subleq/kernel/vmlinux.lds.S) defines the kernel binary layout:

```
0x1000  ──  .text (HEAD_TEXT, TEXT_TEXT, SCHED_TEXT, LOCK_TEXT, etc.)
        ──  RO_DATA (read-only data, exception tables)
        ──  .data (RW_DATA with THREAD_SIZE alignment for init stack)
        ──  PERCPU_SECTION
        ──  .init (text, data, setup, initcalls, initramfs - freed after boot)
        ──  BSS_SECTION (4-byte alignment - critical for Subleq)
```

Output format: `elf32-subleq`. Entry point: `_start`. All BSS alignments are 4 bytes to match Subleq's word-alignment requirement.

---

## 19. Traps and Debugging

### 19.1 Trap Init - `traps.c`

[trap_init](linux/arch/subleq/kernel/traps.c#L22-L25) is a no-op - Subleq has no hardware traps or exceptions.

### 19.2 Stack Trace

`show_stack()` performs a heuristic stack walk, scanning up to 128 words from SP for values that fall within kernel text range (`_stext`–`_etext`).

### 19.3 Register Dump

`show_regs()` prints PC, SP, RA, R20, and R21 from pt_regs, using `PT_REG_GET` to convert from negated storage.

### 19.4 `/proc/cpuinfo`

Reports:
```
processor    : 0
model name   : Subleq OISC Virtual Machine
BogoMips     : <calibrated value>
```

---

## 20. File Inventory

### Assembly Files

| File | Lines | Purpose |
|---|---|---|
| [head.S](linux/arch/subleq/kernel/head.S) | 110 | Boot entry, init stack setup |
| [entry.S](linux/arch/subleq/kernel/entry.S) | 3,041 | IRQ entry/exit, `__switch_to`, `ret_from_fork`, `__subleq_syscall`, `ret_from_user_rt_signal`, `jump_to_userspace` |
| [direct_putcs_asm.S](linux/arch/subleq/kernel/direct_putcs_asm.S) | ~3,000 | Optimized character rendering |
| [elf_process_relr_section.S](linux/arch/subleq/kernel/elf_process_relr_section.S) | ~1,200 | RELR relocation engine |

### C Files

| File | Lines | Purpose |
|---|---|---|
| [setup.c](linux/arch/subleq/kernel/setup.c) | 220 | Machine setup, early console, BSS clear |
| [irq.c](linux/arch/subleq/kernel/irq.c) | 265 | C-level IRQ handler, `subleq_do_work` |
| [time.c](linux/arch/subleq/kernel/time.c) | 223 | Clocksource, sched_clock, delay, entropy |
| [process.c](linux/arch/subleq/kernel/process.c) | 326 | copy_thread, start_thread, idle, halt |
| [signal.c](linux/arch/subleq/kernel/signal.c) | 649 | Signal delivery, sigreturn, restart |
| [syscall_entry.c](linux/arch/subleq/kernel/syscall_entry.c) | 317 | Syscall C dispatcher |
| [tty.c](linux/arch/subleq/kernel/tty.c) | 227 | TTY/console driver |
| [keyboard.c](linux/arch/subleq/kernel/keyboard.c) | 218 | Keyboard polling driver |
| [fbcon.c](linux/arch/subleq/kernel/fbcon.c) | 3,445 | Framebuffer console |
| [bitblit.c](linux/arch/subleq/kernel/bitblit.c) | ~400 | Framebuffer blit operations |
| [binfmt_elf_subleq.c](linux/arch/subleq/kernel/binfmt_elf_subleq.c) | ~2,000 | Custom ELF loader |
| [traps.c](linux/arch/subleq/kernel/traps.c) | 108 | Stack trace, register dump |
| [mm/init.c](linux/arch/subleq/mm/init.c) | 91 | Zone init, zero page |
| [mm/nommu.c](linux/arch/subleq/mm/nommu.c) | ~1,500 | NOMMU memory allocator |

### Key Headers

| Header | Purpose |
|---|---|
| [ptrace.h](linux/arch/subleq/include/asm/ptrace.h) | pt_regs structure, negated storage macros, user_mode() |
| [irqflags.h](linux/arch/subleq/include/asm/irqflags.h) | IRQ enable/disable with nested interrupt prevention |
| [subleq-regs.h](linux/arch/subleq/include/asm/subleq-regs.h) | Register addresses for assembly |
| [switch_context.h](linux/arch/subleq/include/asm/switch_context.h) | switch_stack layout |
| [subleq_fb.h](linux/arch/subleq/include/asm/subleq_fb.h) | Framebuffer constants |
| [current.h](linux/arch/subleq/include/asm/current.h) | `__current_task` global |
| [processor.h](linux/arch/subleq/include/asm/processor.h) | thread_struct, task_pt_regs |
| [string.h](linux/arch/subleq/include/asm/string.h) | memcpy/memset/memmove aliases to runtime |
