# Eternal Software Initiative Machine Architecture

This document provides a complete reference for the ESI OISC machine architecture, covering the instruction set, register file, addressing modes, calling convention, register allocation, code patterns, I/O model, interrupt mechanism, and compilation flow. All code examples use the `.word A, B, C` assembly syntax.

---

## Table of Contents

1.  [Instruction Set Architecture](#1-instruction-set-architecture)
2.  [Addressing Modes (Subleq+)](#2-addressing-modes-subleq)
3.  [Register File](#3-register-file)
4.  [Calling Convention](#4-calling-convention)
5.  [Register Allocation](#5-register-allocation)
6.  [Common Subleq Patterns](#6-common-subleq-patterns)
7.  [I/O Model](#7-io-model)
8.  [Timer Interrupts](#8-timer-interrupts)
9.  [Runtime Library](#9-runtime-library)
10. [Compilation Flow](#10-compilation-flow)
11. [Virtual Machine Reference](#11-virtual-machine-reference)
12. [Inline Assembly](#12-inline-assembly)

---

## 1. Instruction Set Architecture

### 1.1 The Single Instruction

Subleq (Subtract and Branch if Less than or Equal to zero) is a One Instruction Set Computer. Every program is a sequence of one instruction:

```
subleq(A, B, C):  m[B] -= m[A];  if m[B] <= 0 then PC = C else PC += 12
```

### 1.2 Encoding

Each instruction is **3 words × 4 bytes = 12 bytes**:

```
Byte address:   PC      PC+4    PC+8
Contents:       A       B       C
```

- `A`, `B`, `C` are 32-bit signed integers representing **byte addresses**
- All operand addresses must be **4-byte aligned** (divisible by 4)
- The VM converts to word indices internally: `m[addr / 4]`
- Unaligned addresses cause a VM halt

### 1.3 Key Properties

| Property | Value |
|---|---|
| Word size | 32-bit (Two's complement) |
| Byte order | Little-endian |
| Address space | 1.5 GB (3 × 2²⁷ words) |
| Instruction width | 12 bytes (3 words) |
| Registers | None (all memory-mapped) |
| Natural operation | Subtraction + conditional branch |

---

## 2. Addressing Modes (Subleq+)

Since all addresses are 4-byte aligned, bits 0–1 are normally zero. Subleq+ repurposes **bit 0** as an indirection flag:

| Bit 0 | Mode | Behavior |
|---|---|---|
| 0 | Direct | Use address as-is (standard Subleq) |
| 1 | Indirect | Dereference: read `m[addr]` and use that as the actual address |

**Notation**: `addr|I` denotes address `addr` with bit 0 set (e.g., `16|I` = `17`).

### 2.1 Indirect Memory Operations

```asm
; Load: dst = m[ptr]   (ptr holds an address)
; Direct: ~27 words with self-modifying code
; Indirect: 6 words (2 instructions)
.word   ptr|I, Z, .+4       ; Z = -m[m[ptr]]
.word   Z, dst, .+4         ; dst -= Z = dst + m[m[ptr]]

; Store: m[ptr] = src
.word   Z, Z, .+4           ; Z = 0
.word   src, Z, .+4         ; Z = -src
.word   Z, ptr|I, .+4       ; m[m[ptr]] -= Z = m[m[ptr]] + src

; Indirect jump (jump to address stored in `target`)
.word   Z, Z, target|I      ; PC = m[target]
```

### 2.2 Why Indirection Matters

Without bit 0 indirection, Subleq programs must use **self-modifying code** to dereference pointers: patching instruction operands at runtime. This makes code non-re-entrant-an interrupt firing during SMC could corrupt the in-flight instruction. Subleq+ eliminates SMC entirely, enabling:

- Re-entrant interrupt handlers
- Re-entrant context switching
- Shared runtime functions between kernel and userspace

### 2.3 Backward Compatibility

Existing Subleq binaries work unchanged because all traditional addresses have bit 0 = 0. The VM masks bit 0 before use, so `0`, `4`, `8`, etc. behave identically.

---

## 3. Register File

Since Subleq has no hardware registers, all "registers" are fixed memory-mapped locations in the first 272 bytes. The boot loader initializes constants; the kernel reserves this region via `memblock_reserve(0, 0x1000)`.

### 3.1 Complete Register Map

| Word | Byte | Name | Category | Details |
|------|------|------|----------|---------|
| 0 | `0x00` | `INT_HANDLER` | IRQ | Handler address (0 = disabled) |
| 1 | `0x04` | `INT_SAVED_PC` | IRQ | VM writes PC here on interrupt |
| 2 | `0x08` | `INT_SAVED_HANDLER` | IRQ | Saved handler for enable/disable |
| 3 | `0x0C` | `Z` | Core | Scratch zero register |
| 4 | `0x10` | `SP` | Core | Stack pointer |
| 5 | `0x14` | `RA` | Core | Return address scratch |
| 6 | `0x18` | - | - | Reserved |
| 7–23 | `0x1C`–`0x5C` | `R3`–`R19` | GPR | Callee-saved |
| 24 | `0x60` | `R20` | GPR | Return value (caller-saved) |
| 25–28 | `0x64`–`0x70` | `R21`–`R24` | GPR | Arguments 1–4 (caller-saved) |
| 29–35 | `0x74`–`0x8C` | `R25`–`R31` | GPR | Callee-saved |
| 36 | `0x90` | `ZERO` | Const | Always 0 |
| 37 | `0x94` | `FP` | Core | Frame pointer (callee-saved) |
| 38 | `0x98` | `MINUS_ONE` | Const | Always −1 |
| 39 | `0x9C` | `ONE` | Const | Always +1 |
| 40–55 | `0xA0`–`0xDC` | `T0`–`T15` | Scratch | Compiler/runtime temporaries |
| 56 | `0xE0` | `INT_Z` | IRQ | Interrupt entry scratch |
| 57 | `0xE4` | `INT_Z2` | IRQ | pt_regs population pointer |
| 58 | `0xE8` | `SAVE_SP` | IRQ | Saved interrupted SP |
| 59 | `0xEC` | `SYSCALL_JMPTGT` | Syscall | Task-persistent jump target |
| 60 | `0xF0` | `SAVE_JMPTGT` | IRQ | Return PC (may be signal-redirected) |
| 61 | `0xF4` | `SW_Z` | CtxSw | Context switch scratch |
| 62 | `0xF8` | `SW_Z2` | CtxSw | Context switch second scratch |
| 63 | `0xFC` | `SYSCALL_SCRATCH` | Syscall | Syscall return pointer |
| 64–66 | `0x100`–`0x108` | `CLOCK_*` | Clock | SEC_LO, SEC_HI, NS |

### 3.2 Register Categories

**Core registers** - Used by all compiled code:

| Register | Byte | Save Convention | Usage |
|---|---|---|---|
| `Z` | 12 | Reserved | Scratch zero - cleared before each use |
| `SP` | 16 | Reserved | Stack pointer (grows downward) |
| `RA` | 20 | Reserved | Return address temporary (pushed in prologue) |
| `FP` | 148 | Reserved | Frame pointer for dynamic stack functions |
| `R3`–`R19` | 28–92 | Callee-saved | General purpose (17 registers) |
| `R20` | 96 | Caller-saved | Function return value |
| `R21`–`R24` | 100–112 | Caller-saved | Function arguments 1–4 |
| `R25`–`R31` | 116–140 | Callee-saved | General purpose (7 registers) |

**Constant registers** - Pre-initialized by boot loader, never modified:

| Register | Byte | Value | Purpose |
|---|---|---|---|
| `ZERO` | 144 | 0 | Zero constant (cheaper than clearing Z) |
| `MINUS_ONE` | 152 | −1 | Used for `x++` patterns: `subleq(MINUS_ONE, x, .+4)` |
| `ONE` | 156 | +1 | Used for `x--` patterns: `subleq(ONE, x, .+4)` |

**Compiler temporaries** (`T0`–`T15`, bytes 160–220):

Reserved for the LLVM backend's instruction expansion (AsmPrinter). Every pseudo-instruction (MUL, AND, SHL, etc.) expands to sequences that use these as scratch. User code **never** touches them. Each T-register has a specific role during expansion:

| Register | Typical Use |
|---|---|
| `T0`–`T2` | Primary scratch for most operations (copy, negate, compare) |
| `T3`–`T5` | Secondary scratch for complex operations (mul, div) |
| `T6`–`T9` | Extended scratch for 64-bit operations |
| `T10`–`T15` | Available for RELR engine and other kernel assembly |

**Kernel/interrupt registers** (bytes 224–252):

These are partitioned by context to prevent corruption:

| Partition | Registers | Used By |
|---|---|---|
| IRQ entry/exit | `INT_Z`, `INT_Z2`, `SAVE_SP`, `SAVE_JMPTGT` | `subleq_irq_entry` in entry.S |
| Context switch | `SW_Z`, `SW_Z2` | `__switch_to`, `ret_from_fork` |
| Syscall return | `SYSCALL_JMPTGT`, `SYSCALL_SCRATCH` | `__subleq_syscall` (saved/restored by IRQ handler) |

### 3.3 The Z Register

`Z` (byte 12) is the most important register in Subleq programming. Since subleq naturally subtracts, `Z` serves as a negation buffer:

```asm
; Copy: dst = src (4 instructions, 12 words)
.word   dst, dst, .+4     ; dst = 0
.word   Z, Z, .+4         ; Z = 0
.word   src, Z, .+4       ; Z = -src
.word   Z, dst, .+4       ; dst = -(-src) = src
```

`Z` must be cleared before each use because subleq accumulates into it. The convention is:
- Clear Z → load negated value into Z → subtract Z from destination

### 3.4 Negated Storage Optimization

The kernel stores register values **negated** in `pt_regs` and `sigcontext`. This is efficient because `subleq(src, dst, next)` naturally stores `-(m[src])` at `dst`. Saving registers without negation would require an extra clear+subtract per register. C code accesses values via macros:

```c
#define PT_REG_GET(regs, field)       ((unsigned long)(-(long)(regs)->field))
#define PT_REG_SET(regs, field, val)  ((regs)->field = (unsigned long)(-(long)(val)))
```

---

## 4. Calling Convention

### 4.1 Argument Passing

| Parameter | Location |
|---|---|
| Arg 1 | `R21` (byte 100) |
| Arg 2 | `R22` (byte 104) |
| Arg 3 | `R23` (byte 108) |
| Arg 4 | `R24` (byte 112) |
| Arg 5+ | Stack (right-to-left, above return address) |

**Variadic functions**: ALL arguments are passed on the stack (not in registers) to support `va_arg` sequential iteration.

### 4.2 Return Values

| Return Type | Location |
|---|---|
| `i32` (or smaller) | `R20` (byte 96) |
| `i64` | sret: caller passes hidden pointer in `R21`, callee writes through it |
| `struct` (by value) | sret convention via hidden pointer in `R21` |

### 4.3 Register Save Convention

| Registers | Convention | Responsibility |
|---|---|---|
| `R3`–`R19`, `R25`–`R31`, `FP` | Callee-saved | Function must save in prologue, restore in epilogue |
| `R20`–`R24`, `T0`–`T15` | Caller-saved | Caller must save before call if values are needed |
| `SP`, `RA`, `Z` | Reserved | Not allocatable |
| `ZERO`, `MINUS_ONE`, `ONE` | Constants | Never modified |

### 4.4 Stack Frame Layout

```
[High addresses]
+---------------------------+
| Arg N (if > 4 args)       |  ← pushed by caller (right-to-left)
| ...                       |
| Arg 5                     |
+---------------------------+ ← SP on entry (before prologue)
| Return address (RA)       |  ← pushed in prologue
| Saved FP (if frame ptr)   |
| Saved callee-saved regs   |
| Local variables           |
+---------------------------+ ← SP during function body
[Low addresses]
```

The stack grows **downward**. The caller cleans up stack arguments after the call.

### 4.5 Function Prologue/Epilogue

**Prologue** (generated by LLVM):
```asm
; Allocate frame: SP -= frame_size
.word   .Lframe_size, SP, .+4

; Push RA to [SP]
.word   Z, Z, .+4
.word   RA, Z, .+4        ; Z = -RA
.word   Z, SP|I, .+4      ; m[SP] = RA

; Save FP if needed
; ... save callee-saved registers to frame ...
```

**Epilogue**:
```asm
; ... restore callee-saved registers from frame ...

; Pop RA from [SP]
.word   RA, RA, .+4       ; RA = 0
.word   SP|I, RA, .+4     ; RA = -m[SP] (negated)
.word   RA, RA, .+4       ; ... (negate back)  - actually uses Z pattern

; Deallocate frame: SP += frame_size
.word   .Lneg_frame_size, SP, .+4

; Return via indirect jump through RA
.word   Z, Z, RA|I        ; jump to m[RA]
```

### 4.6 Function Call Sequence

```asm
; Call: result = foo(a, b, c)
; Set up arguments
.word   Z, Z, .+4
.word   a, Z, .+4
.word   Z, R21, .+4       ; R21 = a (arg 1)

.word   Z, Z, .+4
.word   b, Z, .+4
.word   Z, R22, .+4       ; R22 = b (arg 2)

.word   Z, Z, .+4
.word   c, Z, .+4
.word   Z, R23, .+4       ; R23 = c (arg 3)

; Push return address, call
; (LLVM emits this as a single CALL pseudo)
.word   .Lret_neg, SP, .+4   ; SP -= 4 (allocate RA slot)
.word   Z, Z, .+4
.word   .Lret_addr_neg, Z, .+4
.word   Z, SP|I, .+4         ; m[SP] = return addr
.word   Z, Z, foo             ; jump to foo

.Lret_addr:
; Return value is in R20
```

### 4.7 SJLJ Exception Handling

For SetJmp/LongJmp exception handling, `invoke` calls are treated as clobbering **all** registers (including callee-saved). The register allocator spills all live values before invokes. This ensures correct state during longjmp unwinding, which only restores `FP` and `SP`.

---

## 5. Register Allocation

### 5.1 LLVM Register Classes

The LLVM backend defines two register classes in `SubleqRegisterInfo.td`:

**GPR** - General Purpose Registers (allocatable for virtual registers):
```
FP, RA, SP,                           ← reserved (in class for type compat)
R3–R20,                                ← 18 allocatable
R21–R24,                               ← 4 allocatable (argument/caller-saved)
R25–R31                                ← 7 allocatable
```
Total allocatable: **29 registers** (after removing reserved FP, RA, SP).

**AllRegs** - All addressable locations (for constraints and special instructions):
```
ZERO, Z, SP, RA, FP, R3–R31, T0–T15
```

### 5.2 Reserved Registers

The following are excluded from allocation:

| Register | Reason |
|---|---|
| `Z` | Scratch for every instruction expansion |
| `SP` | Stack pointer |
| `RA` | Return address temporary |
| `FP` | Frame pointer |
| `ZERO` | Constant 0 |
| `T0`–`T15` | Instruction expansion scratch |

This leaves **29 allocatable GPRs**: R3–R31 (but R20–R24 are caller-saved, so they're more expensive to use across calls).

### 5.3 Register Allocation Hints

The LLVM backend provides non-binding hints to the register allocator to reduce `emitMove` copies:

**Hint 1: Runtime-call pseudo-instructions**

Pseudo-instructions like `MUL`, `AND`, `SHL`, `LB`, etc. expand in the AsmPrinter to calls that pass arguments in `R21`/`R22` and return in `R20`. If the allocator assigns these physical registers directly, the 12-word `emitMove` copies are eliminated:

```
Without hints: MUL %vreg3, %vreg1, %vreg2
  → emitMove(R21, %vreg1)    ; 12 words
  → emitMove(R22, %vreg2)    ; 12 words
  → call __subleq_mul
  → emitMove(%vreg3, R20)    ; 12 words
  Total: 36 extra words

With hints, if %vreg1→R21, %vreg2→R22, %vreg3→R20:
  → call __subleq_mul        ; 0 extra words
```

**Hint 2: In-place operations**

For `ADD`, `SUB`, `ADDI`, `SUBI` pseudo-instructions, the in-place path (dst == src1) is dramatically cheaper:

| Operation | General | In-place | Savings |
|---|---|---|---|
| `ADDI` | 15 words | 3 words | 5× |
| `ADD` | 27 words | 3 words | 9× |
| `SUB` | 27 words | 3 words | 9× |

The allocator hints that `dst` and `src1` should use the same physical register.

---

## 6. Common Subleq Patterns

Every high-level operation decomposes into sequences of the single `subleq(A, B, C)` instruction. Here are the fundamental patterns:

### 6.1 Unconditional Jump

```asm
.word   Z, Z, target       ; Z -= Z = 0; 0 ≤ 0 → always branch
```

### 6.2 Conditional Branch (value ≤ 0)

```asm
.word   ZERO, value, target  ; value -= 0; if value ≤ 0 → branch
```

### 6.3 Copy (dst = src)

```asm
.word   dst, dst, .+4      ; dst = 0
.word   Z, Z, .+4          ; Z = 0
.word   src, Z, .+4        ; Z = -src
.word   Z, dst, .+4        ; dst = -(-src) = src
```
**4 instructions, 12 words.**

### 6.4 Negate (dst = −src)

```asm
.word   dst, dst, .+4      ; dst = 0
.word   src, dst, .+4      ; dst = 0 - src = -src
```
**2 instructions, 6 words.**

### 6.5 Add (dst += src)

```asm
.word   Z, Z, .+4          ; Z = 0
.word   src, Z, .+4        ; Z = -src
.word   Z, dst, .+4        ; dst -= (-src) = dst + src
```
**3 instructions, 9 words.** This is the **in-place add** path - the most efficient primitive after subtraction itself.

### 6.6 Add with Immediate (dst += imm)

```asm
.word   .Lneg_imm, dst, .+4  ; dst -= (-imm) = dst + imm
; ...
.Lneg_imm: .word -imm         ; constant pool entry
```
**1 instruction + 1 constant, 4 words.** The compiler pre-negates the constant.

### 6.7 Subtract (dst -= src)

```asm
.word   src, dst, .+4       ; dst -= src
```
**1 instruction, 3 words.** Subtraction is the native operation.

### 6.8 Increment / Decrement

```asm
; dst++
.word   MINUS_ONE, dst, .+4  ; dst -= (-1) = dst + 1

; dst--
.word   ONE, dst, .+4         ; dst -= 1
```
**1 instruction each, 3 words.** These use the pre-initialized constants.

### 6.9 Compare and Branch

```asm
; if (a > b) goto target:
.word   Z, Z, .+4           ; Z = 0
.word   a, Z, .+4           ; Z = -a
.word   Z, T0, .+4          ; T0 = a (via double negate, or use copy pattern)
.word   b, T0, target       ; T0 = a - b; if a - b ≤ 0 → branch
                             ; (actually: if a ≤ b → branch, so negate logic)
```

The compiler generates various patterns depending on the comparison type. Unsigned comparisons require lattice-based algorithms in the runtime.

### 6.10 Store Word to Stack

```asm
; m[SP + offset] = src  (using SWO pseudo-instruction expansion)
; 1. Compute address: T0 = SP + offset
; 2. Store via indirect: m[T0] = src
.word   Z, Z, .+4
.word   SP, Z, .+4          ; Z = -SP
.word   Z, T0, .+4          ; T0 = SP
.word   .Loffset, T0, .+4   ; T0 = SP + offset (offset is negated)
.word   Z, Z, .+4
.word   src, Z, .+4          ; Z = -src
.word   Z, T0|I, .+4         ; m[T0] = src
```

### 6.11 Load Word from Stack

```asm
; dst = m[SP + offset]  (using LWO pseudo-instruction expansion)
.word   Z, Z, .+4
.word   SP, Z, .+4           ; Z = -SP
.word   Z, T0, .+4           ; T0 = SP
.word   .Loffset, T0, .+4    ; T0 = SP + offset
.word   dst, dst, .+4        ; dst = 0
.word   T0|I, dst, .+4       ; dst = -m[T0] (negated load)
; ... (negate back if needed, or leave negated for pt_regs)
```

---

## 7. I/O Model

I/O operations use the sentinel value `−4` (byte address), which becomes `−1` after the VM's internal `/4` conversion:

### 7.1 Operations

| Operation | Encoding (`.word A, B, C`) | Semantics |
|---|---|---|
| **PUTCHAR** | `addr, -4, target` | Output `m[addr]` as character, jump to `target` |
| **GETCHAR** | `-4, addr, target` | Read character into `m[addr]`, jump to `target` |
| **HALT** | `-4, addr, -4` | Exit with code `m[addr]` |

The roles follow the natural subleq semantics:
- **PUTCHAR**: Operand A is the data source; operand B (`−4`) is the infinite sink
- **GETCHAR**: Operand A (`−4`) is the stream source; operand B is the destination
- **HALT**: Both A and C are `−4`

### 7.2 Compiler Intrinsics

The LLVM backend provides two intrinsic functions that compile to inline subleq I/O instructions (not function calls):

```c
extern void __subleq_putchar(int c);   // → .word addr, -4, .+4
extern int __subleq_getchar(void);     // → .word -4, addr, .+4
```

`__subleq_getchar()` is **non-blocking**: returns 0 if no input is pending, otherwise the ASCII code.

### 7.3 Framebuffer I/O

When compiled with SDL support, the VM memory-maps a framebuffer at `0x5E700000` (800×512 pixels, 32bpp XRGB8888). Writes to this region immediately update the SDL display. Keyboard input is delivered via `__subleq_getchar()` as SDL scancodes (positive = keydown, negative = keyup).

### 7.4 Clock Registers

The VM exposes wall-clock time through memory-mapped registers:

| Byte Addr | Name | Contents |
|---|---|---|
| `0x100` | `CLOCK_S_LO` | Low 32 bits of seconds since epoch |
| `0x104` | `CLOCK_S_HI` | High 32 bits of seconds |
| `0x108` | `CLOCK_NS` | Nanoseconds (0–999,999,999) |

Updated lazily: the VM calls `timespec_get()` when word 64 is read as operand A.

---

## 8. Timer Interrupts

### 8.1 Mechanism

Every N instruction cycles (N = 300,000 in the production VM), if `m[0]` is non-zero:

```c
if (mem[0] && timer++ > 300000) {
    timer = 0;
    mem[1] = pc * 4;     // Save PC (as byte address) to INT_SAVED_PC
    pc = mem[0] / 4;     // Jump to handler at INT_HANDLER
}
```

The timer check occurs **only after non-branching subleq instructions** (when `m[B] > 0`). This ensures the interrupt doesn't fire during I/O or taken branches.

### 8.2 Enable/Disable

```asm
; Disable interrupts (save handler, clear m[0]):
.word   0, 8, .+4         ; m[2] -= m[0]  → m[2] = handler (since m[2] was 0)
.word   0, 0, .+4         ; m[0] -= m[0]  → m[0] = 0 (disabled)

; Enable interrupts (restore handler from m[2]):
.word   Z, Z, .+4
.word   8, Z, .+4         ; Z = -m[2]
.word   Z, 0, .+4         ; m[0] -= Z → m[0] = handler
.word   Z, Z, .+4         ; clear Z
```

### 8.3 Return from Interrupt

```asm
; Return to interrupted code via indirect jump to m[1]:
.word   INT_Z, INT_Z, .+4    ; INT_Z = 0
.word   4, INT_Z, .+4        ; INT_Z = -m[1] = -saved_pc
.word   INT_Z, INT_Z, 5      ; jump to m[1] (addr 4 | bit0 = 5)
```

Uses `INT_Z` (byte 224) exclusively - the only register safe to use without saving, because no compiled code allocates it.

### 8.4 Boot State

At power-on: `m[0] = m[1] = m[2] = 0`. Interrupts are disabled. User code must explicitly install a handler and enable interrupts.

---

## 9. Runtime Library

Since subleq can only subtract and branch, all other operations are implemented in software:

### 9.1 Core Functions

| Category | Function | Inputs | Output | Approx. Cost |
|---|---|---|---|---|
| **Multiply** | `__subleq_mul` | R21, R22 | R20 | ~200 insns |
| **Signed div/mod** | `__subleq_sdivrem` | R21, R22 | R20 (quot), R22 (rem) | ~500 insns |
| **Unsigned div/mod** | `__subleq_udivrem` | R21, R22 | R20 (quot), R22 (rem) | ~500 insns |
| **AND** | `__subleq_and` | R21, R22 | R20 | ~200 insns |
| **OR** | `__subleq_or` | R21, R22 | R20 | ~200 insns |
| **XOR** | `__subleq_xor` | R21, R22 | R20 | ~200 insns |
| **Shift left** | `__subleq_shl` | R21 (val), R22 (amt) | R20 | ~100 insns |
| **Logical shift right** | `__subleq_srl` | R21 (val), R22 (amt) | R20 | ~150 insns |
| **Arith shift right** | `__subleq_sra` | R21 (val), R22 (amt) | R20 | ~150 insns |
| **Load byte** | `__subleq_lb` | R21 (byte addr) | R20 | ~30 insns |
| **Store byte** | `__subleq_sb` | R21 (byte addr), R22 (val) | - | ~30 insns |
| **Load halfword** | `__subleq_lh` | R21 (byte addr) | R20 | ~20 insns |
| **Store halfword** | `__subleq_sh` | R21 (byte addr), R22 (val) | - | ~20 insns |

### 9.2 Constant-Specialized Variants

For known-at-compile-time operands, the backend emits calls to specialized variants that skip the per-invocation setup:

- **Bitwise**: `__subleq_and_b0` through `__subleq_and_b30` (single-bit mask AND), same for OR/XOR
- **Shifts**: `__subleq_srl_1` through `__subleq_srl_31` (fixed shift amount), same for SHL/SRA
- **Sub-word**: `__subleq_lb_b0` through `__subleq_lb_b3` (known byte position within word)

### 9.3 64-bit Operations

libgcc-compatible names for cross-compilation compatibility:

| Function | Description |
|---|---|
| `__ashldi3` | 64-bit shift left |
| `__lshrdi3` | 64-bit logical shift right |
| `__ashrdi3` | 64-bit arithmetic shift right |
| `__divdi3` | 64-bit signed division |
| `__moddi3` | 64-bit signed modulo |
| `__udivdi3` | 64-bit unsigned division |
| `__umoddi3` | 64-bit unsigned modulo |

### 9.4 Memory Operations

| Function | Description |
|---|---|
| `__subleq_memcpy` | Word-aligned bulk copy (forward) |
| `__subleq_memset` | Word-aligned bulk zero/fill |
| `__subleq_memmove` | Overlap-safe copy (forward or backward) |
| `__subleq_memcpy_aligned` | Guaranteed word-aligned variant |
| `__subleq_memmove_aligned` | Guaranteed word-aligned, ~6.1 insns/word |
| `__subleq_memset_aligned` | Guaranteed word-aligned zero |

### 9.5 Soft-Float

Full IEEE 754 software floating-point: single-precision (`__addsf3`, `__mulsf3`, etc.), double-precision (`__adddf3`, `__muldf3`, etc.), conversions (`__fixdfsi`, `__floatsidf`, etc.), and complex arithmetic (`__mulsc3`, `__divdc3`, etc.).

### 9.6 Runtime Generation

The runtime is generated from Python scripts:

```bash
cd runtime
python3 gen_runtime.py > subleq_runtime.s
```

Each generator script (e.g., `emit_mul.py`, `emit_and.py`, `emit_shl.py`) produces optimized Subleq assembly for its operation class. The generators use algorithmic techniques (non-restoring lattice division, unrolled doubling chains for shifts, etc.) that would be impractical to write by hand.

---

## 10. Compilation Flow

### 10.1 Toolchain

| Tool | Purpose |
|---|---|
| `clang -target subleq` | C → Subleq object file |
| `llvm-mc -triple=subleq` | Assembly → object file |
| `ld.lld` | Linker (ELF output) |
| `llvm-objcopy -O binary` | Extract raw binary from ELF |
| `tools/add_boot.py` | Prepend boot loader |
| `vm/vm` | Execute the binary |

### 10.2 Compilation Steps

```bash
# 1. Compile C to object
clang -target subleq -c -O2 -fno-builtin -ffreestanding -o prog.o prog.c

# 2. Assemble runtime
llvm-mc -triple=subleq -filetype=obj -o runtime.o runtime/subleq_runtime.s

# 3. Link
ld.lld -T subleq.ld -o prog.elf prog.o runtime.o

# 4. Extract binary
llvm-objcopy -O binary --only-section=.text prog.elf prog_code.bin

# 5. Add boot sequence
python3 tools/add_boot.py prog_code.bin prog.bin \
    --text-start 4096 --stack-size 8388608

# 6. Run
./vm/vm prog.bin
```

### 10.3 Boot Sequence

The boot loader (`add_boot.py`) generates a 4KB header at address 0:

```
Word 0–2:  subleq(0, 0, 12)                ; Jump to word 3
Word 3–5:  subleq(ZERO, SP_init, final)    ; Initialize SP
           (Word 4 = stack_size value = SP)
...
Word 36:   0                                ; ZERO constant
Word 38:   -1                               ; MINUS_ONE constant
Word 39:   1                                ; ONE constant
...
Last 3:    subleq(Z, Z, text_start+main)   ; Jump to main
```

**SP initialization trick**: Word 4 holds the stack size value (e.g., 8MB). The compiler reads `SP` from byte address 16 (= word 4), so SP is "initialized" simply by having the correct value pre-stored in the boot area.

### 10.4 Linker Script

```ld
MEMORY {
  RAM (rwx) : ORIGIN = 0x1000, LENGTH = 1024M
}
ENTRY(main)
SECTIONS {
  .text : {
    *(.text*) *(.rodata*) *(.data*) *(.bss*)
    . = ALIGN(4);
  } > RAM
  /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
```

All sections are merged into a single flat segment. No separate data/BSS - everything is contiguous for the NOMMU memory model.

---

## 11. Virtual Machine Reference

The production VM is 49 lines of C:

```c
#include <stdio.h>
#include <unistd.h>
#include <time.h>

#define MEM_SIZE 3<<27

int mem[MEM_SIZE];  /* 1.5GB Memory */
int pc;             /* Program counter (word index) */
int timer;          /* Timer counter */

int fetch_operand(void) {
    int raw = mem[pc++];
    if (raw & 1)                          /* Indirect (bit 0 set) */
        return mem[raw / 4] / 4;
    else                                  /* Direct */
        return raw / 4;
}

int main(int argc, char *argv[]) {
    int a, b, c;
    fread(mem, 4, MEM_SIZE, fopen(argv[1], "r"));
    do {
        a = fetch_operand(), b = fetch_operand(), c = fetch_operand();
        if (a == -1)                      /* GETCHAR */
            read(0, &mem[b], 1);
        else if (b == -1)                 /* PUTCHAR */
            write(1, &mem[a], 1);
        else {                            /* Standard SUBLEQ */
            if (a == 64) timespec_get((struct timespec *)&mem[64], 1);
            mem[b] -= mem[a];
            if (mem[b] <= 0)
                pc = c;                   /* Branch taken */
            else if (mem[0] && timer++ > 300000) {
                timer = 0;                /* Timer interrupt */
                mem[1] = pc * 4;
                pc = mem[0] / 4;
            }
        }
    } while(c);
}
```

Key design choices:
- **Clock-on-read**: `timespec_get` is called only when word 64 is accessed as operand A, avoiding per-instruction overhead
- **Branch-only timer**: Interrupt check occurs only when `m[B] > 0` (no branch taken), ensuring atomicity of multi-instruction patterns
- **FD-based I/O**: `read(0, ...)` / `write(1, ...)` for single-byte I/O
- **Exit via `c == 0`**: The `while(c)` loop exits when the C operand is zero (legacy halt)

---

## 12. Inline Assembly

Since Subleq has no named instructions, inline assembly uses `.word` directives:

### 12.1 Basic Usage

```c
__asm__ volatile (
    ".word A, B, C\n"
    :                    // outputs
    :                    // inputs
    : "memory"           // clobbers
);
```

### 12.2 Accessing C Variables

Use the `"m"` constraint for memory operands:

```c
volatile int my_var = 42;

void read_to_r3(void) {
    __asm__ volatile (
        ".word 28, 28, .+4\n"      // R3 = 0
        ".word %0, 12, .+4\n"      // Z = -my_var
        ".word 12, 28, .+4\n"      // R3 = my_var
        ".word 12, 12, .+4\n"      // Z = 0
        :: "m" (my_var) : "memory"
    );
}
```

### 12.3 Naked Functions

For interrupt handlers and low-level routines:

```c
void irq_handler(void) __attribute__((naked));
void irq_handler(void) {
    __asm__ volatile (
        // Disable interrupts
        ".word 0, 8, .+4\n"         // m[2] = -m[0] (save handler)
        ".word 0, 0, .+4\n"         // m[0] = 0 (disable)

        // ... handler body ...

        // Re-enable and return
        ".word 12, 12, .+4\n"       // Z = 0
        ".word 8, 12, .+4\n"        // Z = -m[2]
        ".word 12, 0, .+4\n"        // m[0] = handler
        ".word 12, 12, .+4\n"       // Z = 0
        ".word 224, 224, 5\n"        // indirect jump to m[1]
        ::: "memory"
    );
}
```

### 12.4 Local Labels

```c
__asm__ volatile (
    "1:\n"
    ".word 144, 100, 1b\n"   // loop if R21 ≤ 0
    ::: "memory"
);
```

`.+4` (next instruction) is the most common branch target for sequential execution.
