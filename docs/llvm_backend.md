# Eternal Software Initiative LLVM Backend Documentation

This document provides a complete, self-contained reference for the ESI LLVM backend-a custom LLVM target that compiles C (and C++) code to the ESI architecture, a One Instruction Set Computer based on the Subleq architecture where the only operation is *subtract and branch if less than or equal to zero*.

For the VM, memory layout, boot sequence, and inline-assembly conventions, see [`docs/machine_architecture.md`](docs/machine_architecture.md). For the runtime library generators, see `runtime/gen_runtime.py`.

---

## Table of Contents

1. [High-Level Architecture](#1-high-level-architecture)
2. [Directory Layout](#2-directory-layout)
3. [Register Map](#3-register-map)
4. [Calling Convention](#4-calling-convention)
5. [Type Legalization](#5-type-legalization)
6. [Instruction Selection (ISel)](#6-instruction-selection-isel)
7. [MIR Instruction Set](#7-mir-instruction-set)
8. [The AsmPrinter: From MIR to Subleq Triples](#8-the-asmprinter-from-mir-to-subleq-triples)
9. [The Two-Pass (DryRun) Architecture](#9-the-two-pass-dryrun-architecture)
10. [Constant Pool](#10-constant-pool)
11. [Peephole Optimizations](#11-peephole-optimizations)
12. [Branch and Comparison Lowering](#12-branch-and-comparison-lowering)
13. [Sub-word Memory Access (CHAR_BIT = 8)](#13-sub-word-memory-access-char_bit--8)
14. [Bitwise and Shift Operations](#14-bitwise-and-shift-operations)
15. [Multiplication and Division](#15-multiplication-and-division)
16. [Function Calls and Returns](#16-function-calls-and-returns)
17. [Frame Lowering](#17-frame-lowering)
18. [Register Allocation Hints](#18-register-allocation-hints)
19. [ELF Object Support and Relocations](#19-elf-object-support-and-relocations)
20. [Target Transform Info (Cost Model)](#20-target-transform-info-cost-model)
21. [Exception Handling (SJLJ)](#21-exception-handling-sjlj)
22. [Soft-Float and Libcall Configuration](#22-soft-float-and-libcall-configuration)
23. [Atomics and Concurrency](#23-atomics-and-concurrency)
24. [Inline Assembly Support](#24-inline-assembly-support)
25. [Assembly Parser](#25-assembly-parser)
26. [Compilation Pipeline Summary](#26-compilation-pipeline-summary)

---

## 1. High-Level Architecture

The Subleq backend follows the standard LLVM target architecture, but with a critical twist: because the underlying machine has **no native instructions other than `subleq(A, B, C)`**, every pseudo-instruction defined in the backend's TableGen files is expanded to sequences of subleq triples during the **AsmPrinter** phase-not during instruction selection or MC lowering.

```
C source
  │  clang frontend
  ▼
LLVM IR
  │  SubleqTargetLowering (ISel lowering)
  ▼
SelectionDAG
  │  SubleqDAGToDAGISel (pattern matching)
  ▼
Machine IR (MIR) - pseudo-instructions like ADD, LW, CALL, BR_SLT
  │  Register allocation, frame lowering, branch analysis
  ▼
Machine IR (post-RA)
  │  SubleqAsmPrinter (two-pass: DryRun + emit)
  ▼
Raw subleq triples (.word A, B, C) → ELF object file
```

The `SubleqAsmPrinter` is by far the largest file (~7,700 lines, 153 functions) and is the heart of codegen. It contains an `expand*` function for every MIR opcode, translating each to a hand-optimized sequence of `subleq` triples.

---

## 2. Directory Layout

```
llvm/lib/Target/Subleq/
├── Subleq.td                          # Top-level TableGen: includes, processor, target
├── SubleqRegisterInfo.td              # Register definitions (GPR, AllRegs)
├── SubleqCallingConv.td               # CC_Subleq, RetCC_Subleq, CSR_Subleq
├── SubleqInstrInfo.td                 # All MIR instruction definitions (~910 lines)
├── Subleq.h                           # SubleqISD namespace (custom ISD nodes)
├── SubleqAsmPrinter.cpp               # MIR → subleq triples (7,714 lines)
├── SubleqISelLowering.cpp/.h          # DAG lowering (BR_CC, SELECT_CC, calls, etc.)
├── SubleqISelDAGToDAG.cpp/.h          # Pattern selection (Select, AddrFI matching)
├── SubleqFrameLowering.cpp/.h         # Prologue/epilogue, CSR spill/restore
├── SubleqRegisterInfo.cpp/.h          # Reserved regs, frame index elimination, hints
├── SubleqInstrInfo.cpp/.h             # copyPhysReg, analyzeBranch, insertBranch
├── SubleqTargetMachine.cpp/.h         # TargetMachine, pass pipeline
├── SubleqSubtarget.cpp/.h             # Subtarget (generic CPU, no features)
├── SubleqTargetTransformInfo.cpp/.h   # Instruction cost model
├── SubleqMachineFunctionInfo.h        # Per-function state (VarArgsFrameIndex)
├── SubleqSelectionDAGInfo.cpp/.h      # (minimal)
├── MCTargetDesc/
│   ├── SubleqMCAsmInfo.cpp/.h         # Assembly syntax, ELF config, SJLJ
│   ├── SubleqMCTargetDesc.cpp/.h      # MC component registration
│   ├── SubleqMCCodeEmitter.cpp        # Instruction encoding (word-oriented)
│   ├── SubleqAsmBackend.cpp           # Fixup application, NOP data, reloc eval
│   ├── SubleqELFObjectWriter.cpp      # ELF relocation types (R_386_32, R_SUBLEQ_NEG32)
│   ├── SubleqELFStreamer.cpp/.h       # Streamer customization
│   ├── SubleqFixupKinds.h             # fixup_subleq_neg32
│   └── SubleqInstPrinter.cpp/.h       # Textual instruction printing
├── AsmParser/
│   └── SubleqAsmParser.cpp            # Assembly parsing (.word directives, labels)
└── TargetInfo/
    └── SubleqTargetInfo.cpp/.h        # Target registration (getTheSubleqTarget)
```

---

## 3. Register Map

Subleq has no hardware registers. All "registers" are fixed memory locations in low memory (words 0–67, bytes 0x00–0x10C). The backend defines them in `SubleqRegisterInfo.td`:

| Register | Word | Byte Addr | Role | Saved By |
|----------|------|-----------|------|----------|
| Z | 3 | 0x0C | Scratch zero (cleared before use) | - (reserved) |
| SP | 4 | 0x10 | Stack pointer | - (reserved) |
| RA | 5 | 0x14 | Return address scratch | - (reserved) |
| R3–R19 | 7–23 | 0x1C–0x5C | General purpose | Callee |
| R20 | 24 | 0x60 | Return value | Caller |
| R21–R24 | 25–28 | 0x64–0x70 | Function arguments 1–4 | Caller |
| R25–R31 | 29–35 | 0x74–0x8C | General purpose | Callee |
| ZERO | 36 | 0x90 | Constant 0 | - (constant) |
| FP | 37 | 0x94 | Frame pointer | Callee |
| MINUS_ONE | 38 | 0x98 | Constant −1 | - (constant) |
| ONE | 39 | 0x9C | Constant 1 | - (constant) |
| T0–T15 | 40–55 | 0xA0–0xDC | Compiler temporaries | - (reserved) |

**Register classes:**

- **`GPR`** - All allocatable registers: FP, RA, SP (for type compat, marked reserved), R3–R31. Only `i32` type.
- **`AllRegs`** - GPR + ZERO, Z, T0–T15. Used for instructions that reference non-allocatable locations.

**Reserved registers** (cannot be allocated): Z, SP, RA, FP (when frame pointer is needed), ZERO, T0–T15. The `getReservedRegs()` function in `SubleqRegisterInfo.cpp` marks these.

---

## 4. Calling Convention

Defined in `SubleqCallingConv.td`:

### Arguments

| Convention | Behavior |
|---|---|
| `CC_Subleq` | i1/i8/i16 promoted to i32. First 4 i32 args in R21–R24; rest on stack (4-byte aligned). |
| `CC_Subleq_VarArg` | **All** arguments on stack (enables `va_arg` iteration). |

### Return Values

| Type | Location |
|---|---|
| i32 (or smaller) | R20 |
| i64 / struct | Hidden sret pointer in R21 |

### Register Categories

- **Caller-saved** (clobbered by calls): R20–R24, T0–T15
- **Callee-saved** (preserved): R3–R19, R25–R31
- **CSR_NoRegs**: Used for SJLJ dispatch-forces spilling of all live registers before `invoke` calls.

### Stack Frame

The stack grows **downward**. Caller cleans up stack arguments. The frame layout:

```
High addresses
+---------------------------+
| Argument N (if > 4 args)  |
| ...                       |
| Argument 5                |
+---------------------------+ ← SP on entry
| Return address (RA)       |
| Saved FP (if used)        |
| Saved callee-saved regs   |
| Local variables           |
| RuntimeCallStackPadding   |  ← 16 bytes reserved for nested runtime calls
+---------------------------+ ← SP during function
Low addresses
```

---

## 5. Type Legalization

Configured in the `SubleqTargetLowering` constructor:

- **Legal type**: `i32` only. LLVM automatically expands `i64` to pairs of `i32`.
- **`i8`/`i16`**: All arithmetic is **promoted** to `i32`. Loads and stores of `i8`/`i16` are **Legal** (handled by patterns that emit `LB`/`SB`/`LH`/`SH` pseudo-instructions).
- **`i64` operations**: Shifts expand to libcalls (`__ashldi3`, `__lshrdi3`, `__ashrdi3`). Division/remainder uses `__divdi3`, `__moddi3`, `__udivdi3`, `__umoddi3`.
- **Floating-point**: Not legal. All `f32`/`f64` operations are lowered to **soft-float** libcalls (compiler-rt compatible: `__addsf3`, `__muldf3`, etc.) implemented in `subleq_runtime_softfloat.c`.
- **Atomics**: 32-bit atomics are "supported" via `AtomicExpandPass`-it strips the atomic ordering and emits plain loads/stores (safe on single-core Subleq). Fences are no-ops.

---

## 6. Instruction Selection (ISel)

### DAG Lowering (`SubleqISelLowering.cpp`)

`LowerOperation()` dispatches to custom handlers for:

| ISD Node | Handler | Strategy |
|---|---|---|
| `GlobalAddress` | `LowerGlobalAddress` | Wrap in `SubleqISD::WRAPPER` |
| `BlockAddress` | `LowerBlockAddress` | Wrap in `SubleqISD::WRAPPER` |
| `ConstantPool` | `LowerConstantPool` | Wrap in `SubleqISD::WRAPPER` |
| `JumpTable` | `LowerJumpTable` | Wrap in `SubleqISD::WRAPPER` |
| `BR_CC` | `LowerBR_CC` | Rich comparison lowering (see §12) |
| `SETCC` | `LowerSETCC` | Route through `SELECT_CC` with 0/1 |
| `SELECT_CC` | `LowerSELECT_CC` | 12 SELECT variants (see §12) |
| `SDIV`/`SREM`/etc. | `LowerSDIVREM` | Combined SDIVREM/UDIVREM pseudo |
| `VASTART` | `LowerVASTART` | Store varargs frame pointer |
| `RETURNADDR`/`FRAMEADDR` | Custom | Walk frame chain |
| `EH_SJLJ_*` | Custom | SJLJ exception handling |
| `INTRINSIC_WO_CHAIN` | Custom | `eh_sjlj_lsda` intrinsic |
| `ATOMIC_FENCE` | Custom | No-op (return chain) |

**Multiply-by-constant strength reduction** is enabled via `decomposeMulByConstant()`, which returns `true` so LLVM transforms `x * 3` → `(x << 1) + x`, `x * 5` → `(x << 2) + x`, etc.

**Power-of-2 division/remainder**: `BuildSDIVPow2()` and `BuildSREMPow2()` prevent LLVM's default strength reduction (which would use ADD+SRA+SRL sequences) and instead let the operations go through the normal SDIV/SREM path, which the backend handles more efficiently.

### DAG-to-DAG Selection (`SubleqISelDAGToDAG.cpp`)

The `Select()` method handles:

- **`ISD::Constant`** → `Subleq::LI` (load immediate)
- **`ISD::LOAD`** → `Subleq::LW` or `Subleq::LWO` (with offset folding for frame indices)
- **`ISD::STORE`** → `Subleq::SW` or `Subleq::SWO` (with offset folding)
- **`SubleqISD::CALL`** → `Subleq::CALL` or `Subleq::CALLR`
- **`SubleqISD::WRAPPER`** → `Subleq::LISym` (load symbol address)

**ComplexPattern matchers:**

- `SelectAddrFI` - Matches bare `FrameIndex` nodes for `LEA_FI`.
- `SelectAddrFI_Byte` - Matches `(add frameindex, const)` or `(or frameindex, const)` for byte-offset sub-word operations (LBO/SBO/LHO/SHO). The OR variant is needed because LLVM's DAGCombiner converts `(add X, C)` to `(or X, C)` when alignment guarantees no bit overlap.

---

## 7. MIR Instruction Set

All instructions are defined in `SubleqInstrInfo.td` (~910 lines). None have real encodings-they are pseudo-instructions expanded in the AsmPrinter. Key categories:

### Data Movement

| Instruction | Operands | Description |
|---|---|---|
| `MOV` | `dst, src` | Register-to-register move |
| `LI` | `dst, imm` | Load 32-bit immediate |
| `LISym` | `dst, sym` | Load symbol address |
| `LW` | `dst, addr` | Load word from memory |
| `LWO` | `dst, base, offset` | Load word with offset |
| `SW` | `src, addr` | Store word to memory |
| `SWO` | `src, base, offset` | Store word with offset |
| `CLR` | `dst` | Clear register to zero |

### Sub-word Memory (with `Defs = [R20, R21, R22]`)

| Instruction | Description |
|---|---|
| `LB` / `LBs` | Load byte (zero-ext / sign-ext) |
| `SB` | Store byte (read-modify-write) |
| `LBO` / `LBOs` / `SBO` | Byte ops with frame-relative offset |
| `LH` / `LHs` / `SH` | Halfword ops |
| `LHO` / `LHOs` / `SHO` | Halfword ops with offset |

### Arithmetic

| Instruction | Pattern | Description |
|---|---|---|
| `ADD` | `(add r, r)` | dst = src1 + src2 |
| `ADDI` | `(add r, imm)` | dst = src + imm |
| `SUB` | `(sub r, r)` | dst = src1 − src2 |
| `SUBI` | `(sub r, imm)` | dst = src − imm |
| `NEG` | `(sub 0, r)` | dst = −src |
| `LEA_FI` | `frameindex` | Materialize frame address |

### Bitwise (with `Defs = [R20, R21, R22]` - runtime calls)

| Instruction | Pattern | Description |
|---|---|---|
| `AND` / `ANDI` | `(and r, r/imm)` | Bitwise AND |
| `OR` / `ORI` | `(or r, r/imm)` | Bitwise OR |
| `XOR` / `XORI` | `(xor r, r/imm)` | Bitwise XOR |
| `NOT` | `(not r)` | Bitwise complement (inline, no runtime) |

### Shifts (with `Defs = [R20, R21, R22]` - runtime calls)

| Instruction | Pattern |
|---|---|
| `SHL` / `SHLI` | `(shl r, r/imm)` |
| `SRL` / `SRLI` | `(srl r, r/imm)` |
| `SRA` / `SRAI` | `(sra r, r/imm)` |

### Multiplication and Division (with `Defs = [R20, R21, R22]`)

| Instruction | Description |
|---|---|
| `MUL` | 32-bit multiply |
| `SDIV` / `UDIV` | Signed/unsigned division |
| `SREM` / `UREM` | Signed/unsigned remainder |
| `SDIVREM` / `UDIVREM` | Combined quotient+remainder (single pass) |

### Control Flow

| Instruction | Description |
|---|---|
| `JMP` | Unconditional jump |
| `JMPR` | Indirect jump (computed goto) |
| `BLEZ` | Branch if ≤ 0 (native subleq semantics) |
| `BGTZ` | Branch if > 0 (also matches `brcond`) |
| `BLTZ` | Branch if < 0 |
| `BGEZ` | Branch if ≥ 0 |
| `BREQ0` | Branch if == 0 (two-check) |
| `BRNE0` | Branch if ≠ 0 |
| `BR_SLT/SGT/SGE/SLE` | Signed comparisons (two-operand, overflow-safe) |
| `BR_ULT/UGT/UGE/ULE` | Unsigned comparisons (two-operand, MSB-aware) |
| `BEQ` / `BNE` | Two-operand equal/not-equal |

### Conditional Selects

12 `SELECT_*` pseudo-instructions implement `SELECT_CC`:

- Single-operand (condition vs 0): `SELECT_EQ0`, `SELECT_NE0`, `SELECT_LE0`, `SELECT_GT0`, `SELECT_LT0`, `SELECT_GE0`
- Two-operand unsigned: `SELECT_UGT`, `SELECT_ULT`, `SELECT_UGE`, `SELECT_ULE`
- Two-operand signed: `SELECT_SLT`, `SELECT_SGT`, `SELECT_SLE`, `SELECT_SGE`

### Function Calls

| Instruction | Description |
|---|---|
| `CALL` | Direct call (Defs R20–R24, Uses R21–R24) |
| `CALLR` | Indirect call |
| `RET` | Return (Uses RA, R20) |
| `ADJCALLSTACKDOWN/UP` | Call sequence pseudos for stack adjustment |

### Batch Callee-Save/Restore

| Instruction | Description |
|---|---|
| `CSR_SPILL_START` | Compute T4 = base + offset, save first reg |
| `CSR_SPILL_NEXT` | Decrement T4 by 4, save next reg |
| `CSR_RELOAD_START` | Compute T4 = base + offset, load first reg |
| `CSR_RELOAD_NEXT` | Decrement T4 by 4, load next reg |

These reduce per-register spill cost from ~30 words to ~15 words for subsequent registers by batching the address computation.

### I/O and Special

| Instruction | Description |
|---|---|
| `PUTCHAR` | Output character (VM sentinel −4 in B) |
| `GETCHAR` | Input character (VM sentinel −4 in A) |
| `HALT` | Exit program with return code |
| `NOP` | No-operation (subleq Z, Z, next) |

### SJLJ Exception Handling

| Instruction | Description |
|---|---|
| `EH_SjLj_SetJmp` | Save context, return 0 / non-zero on longjmp |
| `EH_SjLj_LongJmp` | Restore context and jump back |
| `EH_SjLj_Setup_Dispatch` | Set up landing pad dispatch |
| `SJLJ_DISPATCH_MARKER` | No-op marker with register mask |

---

## 8. The AsmPrinter: From MIR to Subleq Triples

`SubleqAsmPrinter.cpp` is the core of the backend. Every MIR instruction dispatches to an `expand*` function that emits raw `.word` triples. Key primitives:

### Emission Helpers

| Helper | Words | Description |
|---|---|---|
| `emitSubleq(A, B, C)` | 3 | Raw subleq triple |
| `emitSubleqNext(A, B)` | 3 | subleq with fall-through (C = PC + 12) |
| `emitClear(dst)` | 3 | dst = 0 via `subleq(dst, dst, next)` |
| `emitMove(dst, src)` | 12 | dst = src (clear dst, Z = −src, dst = −Z, clear Z) |
| `emitNegate(dst, src)` | 6–18 | dst = −src |
| `emitAdd(dst, s1, s2)` | 9–15 | dst = s1 + s2 (optimized for dst == s1 or dst == s2) |
| `emitSub(dst, s1, s2)` | 3–21 | dst = s1 − s2 (optimized for dst == s1) |
| `emitLoadImm(dst, val)` | 0–6 | Load constant via constant pool |
| `emitJumpReloc(target)` | 3 | Unconditional jump (relocatable) |
| `emitJumpToSymbol(sym)` | 3 | Jump to MCSymbol |

### Key Expansion Sizes

Some representative expansion sizes (in words / 3 = subleq instructions):

| MIR Instruction | Words (typical) |
|---|---|
| `MOV` | 12 |
| `LI` (imm ≠ 0) | 6 (or 3 with delta, or 0 if known) |
| `ADD` (general) | 15 |
| `ADD` (dst == src1) | 9 |
| `ADDI` (in-place) | 3 |
| `SUB` (general) | 21 |
| `LW` (general) | 30 |
| `LW` (direct reg) | 12 |
| `SW` (general) | 30 |
| `BLEZ` | 3 |
| `BGTZ` | 18–21 |
| `BR_SLT` (signed) | ~90 |
| `BR_ULT` (unsigned) | ~90 |
| `CALL` | ~66 |
| `RET` | 9 |

### Register Address Translation

`getRegAddr(unsigned Reg)` maps LLVM register enums to byte addresses. For example, `Subleq::R3` → `ADDR_R3` (= 7 × 4 = 28). The `SubleqMemLayout` enum encodes all fixed memory addresses.

---

## 9. The Two-Pass (DryRun) Architecture

Because subleq has no conditional branch with an *arbitrary* target encoding-the branch target is a literal address word-the AsmPrinter must know the exact byte address of every basic block *before* emitting code. This creates a chicken-and-egg problem: you need block addresses to emit branches, but you need to emit code to know block addresses.

**Solution: Two-pass emission.**

1. **DryRun pass** (`calculateBlockAddresses`): Sets `DryRun = true`. Iterates over all basic blocks and instructions, calling the same `expand*` functions. These update `PC` without emitting any bytes. After each block, the resulting `PC` is recorded as that block's address in `LabelAddresses`. Peephole state (`KnownRegValues`, `PeepholeR21Valid`, `PeepholeT0Valid`) and `ReturnLabelID` are saved and restored to ensure bit-exact consistency.
2. **Real pass**: Sets `DryRun = false`. Iterates again, now emitting real `.word` directives. Branch targets are resolved from `LabelAddresses`.

**Critical invariant:** The DryRun and real passes must produce *exactly the same code size* for every instruction. If they diverge, branch targets will be wrong, causing silent miscompilation or crashes. A historical bug (Heisenbug in `cred.c`) was traced to `INLINEASM` instructions incorrectly invalidating peephole states between passes.

**Per-section PCs:** When a translation unit has functions in multiple sections (e.g., `.text` and `.sched.text`), each section maintains its own `PC` counter via the `SectionPCs` map.

---

## 10. Constant Pool

Subleq cannot encode immediate values in instructions-everything is a memory address. To load an immediate value `V`, the backend:

1. Stores `−V` at a constant pool location (a labeled word at the end of the section).
2. Emits `subleq(const_addr, dst, next)` which computes `dst = 0 − (−V) = V`.

### Per-Section Constant Pools

To avoid cross-section references (which cause Linux kernel `modpost` warnings), constants are duplicated per-section. The pools are:

| Pool | Key | Purpose |
|---|---|---|
| `SectionConstantPool` | (section, int32_t) | Integer constants |
| `SectionSymbolConstantPool` | (section, string) | Symbol addresses |
| `SectionSymbolOffsetConstantPool` | (section, name, offset) | Symbol + offset (folds GV+offset into `R_SUBLEQ_NEG32`) |
| `SectionMCSymbolConstantPool` | (section, MCSymbol*) | Block address symbols |
| `CodeAddressConstantPool` | int32_t | Code addresses needing relocation |

The `emitImmediateConstantPool()` function is called at the end of each section to emit all accumulated constants.

---

## 11. Peephole Optimizations

The AsmPrinter implements several peephole optimizations that operate during emission:

### P1: Sub-word Address Reuse (`PeepholeR21Valid`)

When a sub-word store (SHO/SBO) computes a word-aligned byte address into R21, the next sub-word load/store to the same address can skip the address computation. This saves ~44 subleq instructions per reuse. The state tracks:
- `PeepholeR21BaseReg` - the base register used
- `PeepholeR21WordOffset` - the word-aligned byte offset
- `PeepholeR21HalfPos` / `PeepholeR21BytePos` - which sub-word position

Reset at: basic block boundaries, any instruction that clobbers R21.

### P2: Store-Load Forwarding (`PeepholeT0Valid`)

When `expandSW` stores a value, it leaves `−src` in T0 as a side effect. If the next instruction loads from the same address, it can reuse T0 instead of re-reading memory. Tracks `PeepholeT0NegatedSrc`.

### H3: LI Delta (`KnownRegValues`)

Tracks known integer values loaded into registers via `emitLoadImm`. When loading a new constant into a register that already holds a known value, emits a 3-word delta subtraction instead of a 6-word clear+load:

```
; Instead of 6 words (clear + load from pool):
; Just 3 words: dst -= (oldValue - newValue)
subleq(delta_pool_addr, dst, next)
```

This optimization also detects when a register already holds the desired value (0-word no-op).

### Dead Operand Analysis (`getCmpOperandDeadFlags`)

For branch instructions, analyzes liveness (via `LivePhysRegs`) to determine if comparison operands are dead after use. Dead operands can be used as temporaries directly, avoiding `emitMove` copies (saving 12 words each).

### Instruction Fusion (`SkipMIs`)

The `expandLBO`/`expandSBO` and related functions can look ahead at the next instruction and fuse operations (e.g., an LBO followed by an SBO to the same byte can share address computation).

---

## 12. Branch and Comparison Lowering

This is the most complex part of the backend, because subleq only has a ≤ 0 branch, and signed/unsigned comparisons can overflow.

### BR_CC Lowering Strategy

`LowerBR_CC()` in `SubleqISelLowering.cpp` implements a multi-tier strategy:

**Tier 1: Comparison against zero (3–21 words)**

When RHS is constant zero, uses cheap single-operand branch nodes:
- `SETLE` → `SubleqISD::BLEZ` (3 words - maps directly to subleq)
- `SETLT` → `SubleqISD::BLTZ` (15 words)
- `SETGT` → `SubleqISD::BGTZ` (18–21 words)
- `SETGE` → `SubleqISD::BGEZ` (15 words)

Also handles constant-zero LHS by swapping the comparison.

**Tier 2: Equality/inequality (diff-based)**

- `SETEQ` → `SubleqISD::BEQ0` on `(LHS − RHS)` (27 words)
- `SETNE` → `SubleqISD::BNE0` on `(LHS − RHS)` (21 words)

**Tier 3: Two-operand comparisons (overflow-safe, ~90 words)**

For signed comparisons like `SETLT`, computing `LHS − RHS` can overflow (e.g., `INT_MIN − 1` wraps). The backend uses two-operand branch nodes (`BR_SLT`, `BR_SGT`, `BR_SGE`, etc.) that check operand signs before subtracting:

```
; BR_SLT: branch if LHS < RHS (signed)
; 1. Check signs: if LHS ≥ 0 and RHS < 0 → LHS > RHS, fall through
; 2. If LHS < 0 and RHS ≥ 0 → LHS < RHS, branch
; 3. Same signs → safe to subtract: branch if (LHS − RHS) < 0
```

**Unsigned comparisons** (`BR_ULT`, `BR_UGT`, `BR_UGE`, `BR_ULE`) use MSB (sign-bit) analysis to determine the unsigned magnitude comparison: if MSBs differ, the one with MSB=1 is unsigned-greater; if MSBs are the same, the lower 31 bits can be compared with signed subtraction.

### SELECT_CC Lowering

`LowerSELECT_CC()` follows a similar strategy: for comparisons against zero, emits single-operand selects (`SELECT_EQ0`, `SELECT_GT0`, etc.); for signed/unsigned comparisons, emits two-operand selects (`SELECT_SLT`, `SELECT_UGT`, etc.) that implement overflow-safe control flow inline.

---

## 13. Sub-word Memory Access (CHAR_BIT = 8)

With `CHAR_BIT = 8`, the Subleq backend packs 4 bytes per 32-bit word (little-endian):

```
Byte Address 4N+0 → bits [7:0]    (least significant byte)
Byte Address 4N+1 → bits [15:8]
Byte Address 4N+2 → bits [23:16]
Byte Address 4N+3 → bits [31:24]  (most significant byte)
```

### Byte Operations

The general-case `LB`/`SB` instructions call runtime functions (`__subleq_lb`, `__subleq_sb`) that:
1. Compute the word address: `word_addr = byte_addr & ~3`
2. Compute the byte position: `pos = byte_addr & 3`
3. Use a bit-lattice to extract/insert the relevant byte

### Optimized Frame-Relative Operations (LBO/SBO/LHO/SHO)

When the byte offset is known at compile time (frame-relative accesses), the backend uses **split entry points** (`__subleq_lb_b0`, `__subleq_lb_b1`, `__subleq_lb_b2`, `__subleq_lb_b3`) that skip the modulo lattice, saving ~44 subleq instructions per call. These are selected via the `AddrFI_Byte` ComplexPattern in `SubleqISelDAGToDAG.cpp`.

The `traceAddrToGlobal()` helper traces address definitions backward through MOV/COPY/ADDI/LISym chains to identify compile-time-known byte offsets for global variables.

---

## 14. Bitwise and Shift Operations

Since subleq can only subtract, bitwise operations require creative implementations:

### Bitwise AND/OR/XOR

**Register-register operations** call runtime functions (`__subleq_and`, `__subleq_or`, `__subleq_xor`) that use a 32-iteration bit-by-bit lattice: doubling the input values each iteration, testing the sign bit via BLEZ, and accumulating the result.

**Immediate operations** (ANDI/ORI/XORI) use **split entry points** (`__subleq_and_bN`) that skip iterations for bits that are known 0 or 1 in the immediate, reducing iteration count.

### NOT

`NOT` is the only bitwise op expanded inline (no runtime call): `dst = −1 − src`. This is just `subleq(src, MINUS_ONE_copy, ...)`.

### Shifts

Shifts also call runtime functions (`__subleq_shl`, `__subleq_srl`, `__subleq_sra`). For **immediate shift amounts** (SHLI/SRLI/SRAI), the backend uses split entry points to skip to the correct lattice position.

---

## 15. Multiplication and Division

### Multiplication

`expandMUL` moves operands to R21/R22, calls `__subleq_mul`, and moves R20 to the destination. The runtime uses shift-and-add: for each bit of the multiplier, conditionally add the multiplicand.

### Division and Remainder

The backend coalesces `SDIV`+`SREM` pairs into single `SDIVREM` pseudo-instructions (and `UDIV`+`UREM` into `UDIVREM`). These call `__subleq_sdivrem` / `__subleq_udivrem`, which compute both quotient (in R20) and remainder (in R21) in one pass.

For 64-bit division, standard libcalls (`__divdi3`, `__moddi3`, `__udivdi3`, `__umoddi3`) are used.

---

## 16. Function Calls and Returns

### CALL Expansion

`expandCALL` emits:
1. Push return address to stack (via `emitPushRALabel`)
2. Jump to target function

The return address is an MCSymbol label emitted immediately after the jump. `emitPushRALabel` computes the label address, decrements SP, and stores it to the stack via indirect addressing (`[SP|I]`).

### CALLR Expansion

Indirect calls work similarly but the jump target comes from a register (using Subleq+ indirect addressing for the jump: `subleq(Z, Z, target|I)`).

### RET Expansion

`expandRET` emits:
1. Pop return address from stack into RA (`emitPopRA`)
2. Jump to RA (indirect: `subleq(Z, Z, RA|I)`)

### Runtime Calls

Many MIR instructions (AND, SHL, MUL, LB, etc.) expand to runtime library calls. `emitRuntimeCall(funcName)` handles the push-RA / jump-to-symbol / emit-return-label sequence. `emitSetupRuntimeArgs` handles the register shuffling to place operands in R21/R22 without clobbering, considering all four possible conflict cases.

---

## 17. Frame Lowering

`SubleqFrameLowering.cpp` handles prologue/epilogue generation:

### Prologue (`emitPrologue`)

1. Compute total frame size (locals + spills + `RuntimeCallStackPadding`)
2. Emit `SUBI SP, SP, frameSize` (decrement stack pointer)
3. If frame pointer needed: `MOV FP, SP` then `ADDI FP, FP, adjustment`

### Epilogue (`emitEpilogue`)

1. If frame pointer used: `MOV SP, FP` then `ADDI SP, SP, adjustment`
2. Else: `ADDI SP, SP, frameSize`

### RuntimeCallStackPadding

A fixed 16-byte padding is added to every frame. This prevents runtime function return addresses (which are pushed onto the stack by CALL sequences) from overwriting spill slots. Runtime functions can nest up to 4 levels deep.

### Batch CSR Spill/Restore

`spillCalleeSavedRegisters()` groups contiguous callee-saved registers and emits `CSR_SPILL_START` + `CSR_SPILL_NEXT` sequences. The first register in a group costs ~30 words (address computation + store); subsequent registers cost only ~15 words (decrement T4 by 4 + store). The restore path uses `CSR_RELOAD_START` / `CSR_RELOAD_NEXT` symmetrically.

### Frame Index Elimination

`SubleqRegisterInfo::eliminateFrameIndex()` is a substantial function (~290 lines) that replaces `FrameIndex` references in MIR instructions with `SP + offset` or `FP + offset`. It handles special cases for:
- Direct register loads/stores from stack slots
- Sub-word operations (LBO/SBO/LHO/SHO) where the byte offset must be preserved
- `LEA_FI` → `ADDI base, offset`

---

## 18. Register Allocation Hints

`SubleqRegisterInfo::getRegAllocationHints()` provides non-binding hints to the register allocator:

### Runtime-Call Operand Hints

For instructions that expand to runtime calls (AND, SHL, MUL, LB, SB, etc.), hints suggest:
- **Output → R20**: Avoids a 12-word `emitMove` from R20 to the destination
- **Input 1 → R21**: Avoids copying to R21 before the call
- **Input 2 → R22**: Avoids copying to R22 before the call

### In-Place Hints

For instructions like `ADDI`, `ADD`, `SUB`, `SUBI`, `SHLI`, `SRLI`, `SRAI`, the first source operand is hinted to match the destination register. When `dst == src1`, the expansion is dramatically cheaper (e.g., `ADDI` in-place is 3 words vs. 15 general).

### Identification

`isRuntimeCallPseudo()` identifies the ~30 opcodes that benefit from R20/R21/R22 hints. `benefitsFromInPlace()` identifies opcodes where `dst == src1` saves significant code. Notably, `NEG` and `NOT` are **excluded** from in-place hints because their in-place forms are actually *worse*.

---

## 19. ELF Object Support and Relocations

The backend produces standard ELF object files with:

- **Machine type**: `EM_SUBLEQ` (custom ELF machine ID)
- **Endianness**: Little-endian
- **Word size**: 32-bit

### Relocation Types

| Type | Description |
|---|---|
| `R_386_32` | Standard 32-bit absolute relocation |
| `R_SUBLEQ_NEG32` | Negated 32-bit: resolves to `−(S + A)` |

The `R_SUBLEQ_NEG32` relocation is essential for the constant pool mechanism. When loading an immediate value `V`, the backend stores `−V` in the constant pool. At link time, the relocation resolves to `−(symbol_value + addend)`, producing the negated address needed by the `subleq` copy idiom.

### Fixup Handling

`SubleqAsmBackend::applyFixup()` applies fixups to the data section. For `fixup_subleq_neg32`, it negates the value only when fully resolved (no relocation emitted). When a relocation *is* emitted, the addend is written normally; the linker's `relocate()` handles the negation.

`evaluateFixup()` overrides the base class to force relocations for undefined symbols, ensuring proper ELF relocations for external references like `__text_start`.

### MCAsmInfo Configuration

Key settings in `SubleqMCAsmInfo.cpp`:
- `CommentString = "#"`
- `Data32bitsDirective = "\t.word\t"`
- `ExceptionsType = ExceptionHandling::SjLj`
- `SupportsDebugInformation = true`
- `UseIntegratedAssembler = true`
- `ParseInlineAsmUsingAsmParser = true`

---

## 20. Target Transform Info (Cost Model)

`SubleqTargetTransformInfo.cpp` provides LLVM's optimization passes with realistic instruction costs based on measured step counts:

| Operation | Measured Steps | Cost |
|---|---|---|
| Add / Sub | ~85 | 1 |
| Shifts | 143–172 | 2 |
| AND / OR | 193–194 | 2 |
| XOR | ~236 | 3 |
| Multiply | 188–286 | 3 |
| Division / Remainder | 354–947 | 8 |
| ICmp | - | 2 |
| Select | - | 3 |

These costs guide LLVM's decisions on loop unrolling, inlining, and instruction selection trade-offs.

---

## 21. Exception Handling (SJLJ)

The backend uses **SJLJ (SetJmp/LongJmp)** exception handling, the only EH model feasible without hardware stack unwinding support.

### Implementation Status

SJLJ exception handling is **fully implemented** across the backend:

- **ISel lowering** (`SubleqISelLowering.cpp`): Custom lowering for `ISD::EH_SJLJ_SETJMP`, `ISD::EH_SJLJ_LONGJMP`, `ISD::EH_SJLJ_SETUP_DISPATCH`, and `eh_sjlj_lsda` intrinsic.
- **Dispatch block** (`emitSjLjDispatchBlock`, ~300 lines): Creates dispatch MBBs, a dense jump table (one entry per call site index), a trap BB (calls `abort` for out-of-range indices), and stores the dispatch address into `jbuf[1]` of the function context.
- **Two-pass compatibility**: `calculateBlockAddresses()` explicitly calls `emitJumpTableInfo()` during the DryRun pass, ensuring jump table symbols are registered *before* they are referenced.
- **Register handling**: `CSR_NoRegs` callee-saved set forces spilling of all live values before `invoke` calls. `SJLJ_DISPATCH_MARKER` carries the register mask for the dispatch block.
- **Unwind resume**: `RTLIB::UNWIND_RESUME` is configured to call `_Unwind_SjLj_Resume` for correct nested exception propagation.

> [!NOTE]
> The stale comments in `SubleqMCAsmInfo.cpp` describing SJLJ as "BLOCKED" or "PARTIALLY implemented" are outdated and refer to problems that have since been fixed.

---

## 22. Soft-Float and Libcall Configuration

Since Subleq has no floating-point hardware, the constructor configures comprehensive libcall mappings:

| Category | Example Functions |
|---|---|
| f32 arithmetic | `__addsf3`, `__subsf3`, `__mulsf3`, `__divsf3` |
| f64 arithmetic | `__adddf3`, `__subdf3`, `__muldf3`, `__divdf3` |
| Float ↔ int | `__fixsfsi`, `__fixdfdi`, `__floatsisf`, `__floatdidf`, etc. |
| Precision conversion | `__extendsfdf2`, `__truncdfsf2` |
| Comparisons | `__eqsf2`, `__ltdf2`, `__unordsf2`, etc. |
| Rounding | `floor`, `ceil`, `trunc`, `round`, `nearbyint`, `rint` |
| Trig / exp / log | `sin`, `cos`, `exp`, `log`, `pow`, `sqrt`, etc. |

Implementations come from two sources:
- **Compiler-rt builtins** (`subleq_runtime_softfloat.c`) for basic operations
- **uClibc-ng** (`libc.a`) for math library functions

Memory operations use `__subleq_memcpy`, `__subleq_memset`, `__subleq_memmove` (prefixed to avoid conflicts with user-defined versions). Inline expansion of memcpy/memset/memmove is completely disabled (`MaxStoresPerMemcpy = 0`) because byte-level operations are ~30× slower than word-level runtime functions.

---

## 23. Atomics and Concurrency

Subleq is a single-core, single-threaded machine. The backend handles atomics as follows:

- **`setMaxAtomicSizeInBitsSupported(32)`**: Tells LLVM that 32-bit atomics are "supported."
- **`AtomicExpandPass`**: Added in `addIRPasses()`, converts atomic operations to non-atomic equivalents (the `shouldExpandAtomicLoadInIR/StoreInIR` overrides return `NotAtomic`).
- **Fences**: `ATOMIC_FENCE` is custom-lowered to a no-op (just returns the chain). No store buffers or cache coherence to worry about.

---

## 24. Inline Assembly Support

The backend supports GCC-style inline assembly with:

### Constraints

| Constraint | Type | Description |
|---|---|---|
| `r` | Register | Any GPR |
| `m` | Memory | Memory operand (byte address of variable) |
| `i` | Immediate | Integer constant |

### Operand Printing

`PrintAsmOperand()` handles:
- Register operands: prints the byte address (e.g., `28` for R3)
- Extra code `n`: prints negated immediate values
- Extra code `b`: byte number (addr & 3) for sub-word access

`PrintAsmMemoryOperand()` prints the byte address of memory operands.

### Inline Assembly Memory Operand

`SelectInlineAsmMemoryOperand()` accepts any address as a valid memory operand for `m`, `o`, and other memory constraints.

Since Subleq has no named instructions, inline assembly uses `.word A, B, C` directives to emit raw subleq triples.

---

## 25. Assembly Parser

`SubleqAsmParser.cpp` (~300 lines) parses Subleq assembly:

- **`.word` directives**: The primary instruction format (three 32-bit integers per subleq triple)
- **Labels**: Standard label definitions and references
- **Expressions**: Arithmetic on labels and constants (e.g., `.+4` for fall-through)
- **Registers**: Parsed by name (`r3`, `sp`, `zero`, etc.) and mapped to byte addresses
- **Negated symbols**: Supports `-.Lsymbol` for `R_SUBLEQ_NEG32` relocations

---

## 26. Compilation Pipeline Summary

The complete LLVM pass pipeline for Subleq:

```
1. AtomicExpandPass        - Lower atomics to plain loads/stores
2. Standard IR passes      - LLVM's optimization pipeline
3. SubleqDAGToDAGISel      - Instruction selection (patterns + custom Select())
4. Register allocation     - Greedy RA with custom hints
5. SubleqFrameLowering     - Prologue/epilogue insertion, CSR batch spill
6. Branch analysis         - analyzeBranch / insertBranch / removeBranch
7. SubleqAsmPrinter        - Two-pass: DryRun (size calculation) + emit
   ├── calculateBlockAddresses()  - DryRun pass
   ├── emitFunctionBodyStart()    - Function label, peephole reset
   ├── emitBasicBlockStart()      - Block label
   ├── emitInstruction()          - Dispatch to expand* functions
   ├── emitBasicBlockEnd()        - Pending branch resolution
   ├── emitImmediateConstantPool() - Emit section constants
   └── emitEndOfAsmFile()         - Final cleanup
8. MC layer                - ELF object emission with R_386_32 / R_SUBLEQ_NEG32
```

### Quick Build Reference

#### Baremetal (standalone binary for the VM)

```bash
# Compile C to object
clang -target subleq -c -O2 -fno-builtin -ffreestanding -o prog.o prog.c

# Assemble runtime
llvm-mc -triple=subleq -filetype=obj -o runtime.o runtime/subleq_runtime.s

# Link
ld.lld -T subleq.ld -o prog.elf prog.o runtime.o

# Extract binary + add boot sequence
llvm-objcopy -O binary --only-section=.text prog.elf prog_code.bin
python3 tools/add_boot.py prog_code.bin prog.bin --text-start 4096 --stack-size 8388608

# Run
./vm/vm prog.bin
```

#### Linux ELF (userspace application for the Subleq kernel)

```bash
# Compile C to ELF executable
# No -target, -fno-builtin, or -ffreestanding needed - use the cross-compiler directly.
# The core Subleq runtime and soft-float libcalls are part of the kernel;
# fixups are handled by the kernel's ELF loader. No explicit runtime link required.
clang --sysroot=/path/to/subleq-sysroot -O2 -o prog prog.c

# Or compile to object and link separately
clang --sysroot=/path/to/subleq-sysroot -c -O2 -o prog.o prog.c
ld.lld --sysroot=/path/to/subleq-sysroot -o prog prog.o -lc
```
