#!/usr/bin/env python3
"""
Hand-written Subleq runtime functions.
This generates assembly code that can be concatenated with compiled code.

Calling convention (standard C ABI):
- First arg in R21, second arg in R22
- Return value in R20
- Return address is in the RA register (RA-direct convention)
- Callee returns via JMP RA|I (subleq Z, Z, RA|I)

This file now serves as the central module that:
1. Defines shared constants (ADDR_*)
2. Provides the shared emit_return_sequence() function
3. Imports and assembles all runtime functions via emit_all()

Individual runtime functions are in separate files:
- emit_udiv_o32.py, emit_urem_o32.py, emit_sdiv_o32.py, emit_srem_o32.py (O(32) optimized)
- emit_mul_o32.py (optimized O(32) multiplication)
- emit_and.py, emit_or.py, emit_xor.py
- emit_shl.py, emit_shift_o32.py (optimized SRL/SRA)
- emit_lb_o1.py (optimized LB), emit_sb.py
"""

# Memory addresses - BYTE addresses (word * 4) for CHAR_BIT=8 support
# VM divides by 4 when accessing memory
ADDR_Z = 3 * 4        # = 12
ADDR_SP = 4 * 4       # = 16
ADDR_RA = 5 * 4       # = 20
ADDR_ZERO = 36 * 4    # = 144
ADDR_MINUS_ONE = 38 * 4  # = 152, Constant -1
ADDR_ONE = 39 * 4      # = 156, Constant 1
# New ABI registers (R20-R24): word addresses 24-28, byte addresses 96-112
ADDR_R20 = 24 * 4     # = 96, Return value register (new ABI)
ADDR_R21 = 25 * 4     # = 100, First argument register (new ABI)
ADDR_R22 = 26 * 4     # = 104, Second argument register (new ABI)
ADDR_R23 = 27 * 4     # = 108, Third argument register (new ABI)
ADDR_R24 = 28 * 4     # = 112, Fourth argument register (new ABI)
ADDR_T0 = 40 * 4      # = 160, Temporaries
ADDR_T1 = 41 * 4      # = 164
ADDR_T2 = 42 * 4      # = 168
ADDR_T3 = 43 * 4      # = 172
ADDR_T4 = 44 * 4      # = 176
ADDR_T5 = 45 * 4      # = 180
ADDR_T6 = 46 * 4      # = 184
ADDR_T7 = 47 * 4      # = 188
ADDR_T8 = 48 * 4      # = 192
ADDR_T9 = 49 * 4      # = 196
ADDR_T10 = 50 * 4     # = 200
ADDR_T11 = 51 * 4     # = 204
ADDR_T12 = 52 * 4     # = 208
ADDR_T13 = 53 * 4     # = 212
ADDR_T14 = 54 * 4     # = 216
ADDR_T15 = 55 * 4     # = 220
# Sentinel for halt/output: -4 (becomes -1 after VM's /4)
ADDR_SPECIAL = -4

# Subleq+ indirect addressing flag (bit 1)
INDIRECT_FLAG = 1

# --- Centralized Constant Pool ---
# Each numeric constant (e.g. 1, -1, 4, -2147483648) gets a single label
# in a shared .rodata section, eliminating duplication across emit modules.
_const_pool = {}       # value -> label name
_const_pool_order = [] # (label, value) in allocation order

def const_from_pool(value):
    """Return the assembler label for a pooled constant.

    On first call for a given *value*, allocates a new label and records
    it for later emission by emit_const_pool().  Subsequent calls with
    the same value return the same label.

    Naming: .Lconst_<value>  for value >= 0
            .Lconst_n<abs>   for value < 0
    """
    if value in _const_pool:
        return _const_pool[value]
    if value >= 0:
        label = f".Lconst_{value}"
    else:
        label = f".Lconst_n{abs(value)}"
    _const_pool[value] = label
    _const_pool_order.append((label, value))
    return label


def emit_const_pool():
    """Emit the accumulated constant pool as a .rodata section.

    Handles the __main__ vs gen_runtime module identity issue: when
    gen_runtime.py runs as __main__, the emit modules import a separate
    'gen_runtime' module copy, so the pool state lives there.
    """
    import sys
    mod = sys.modules.get('gen_runtime', sys.modules[__name__])
    pool_order = mod._const_pool_order
    asm = []
    asm.append('        .section .rodata.const_pool,"a",@progbits')
    for label, value in pool_order:
        asm.append(f"{label}:")
        asm.append(f"        .word   {value}")
    return asm

def emit_push_ra(asm):
    """Push RA onto the stack (for non-leaf runtime function entry).
    
    Call this once at the top of any runtime function that calls other
    functions via emit_call_sequence.  Pair with emit_pop_ra before return.
    
    Emits 3 instructions:
      SP -= 4, *SP = 0, *SP -= RA  (push -RA)
    """
    asm.append(f"        .word {const_from_pool(4)}, {ADDR_SP}, .+4")            # SP -= 4
    asm.append(f"        .word {ADDR_SP | INDIRECT_FLAG}, {ADDR_SP | INDIRECT_FLAG}, .+4")  # *SP = 0
    asm.append(f"        .word {ADDR_RA}, {ADDR_SP | INDIRECT_FLAG}, .+4")  # *SP -= RA = -RA


def emit_pop_ra(asm):
    """Pop RA from the stack (for non-leaf runtime function exit).
    
    Call this once before emit_return_sequence in any runtime function
    that called emit_push_ra at entry.
    
    Emits 3 instructions:
      clear RA, RA -= *SP, SP += 4  (pop RA)
    """
    asm.append(f"        .word {ADDR_RA}, {ADDR_RA}, .+4")          # clear RA
    asm.append(f"        .word {ADDR_SP | INDIRECT_FLAG}, {ADDR_RA}, .+4")  # RA = 0 - (-savedRA) = +savedRA
    asm.append(f"        .word {const_from_pool(-4)}, {ADDR_SP}, .+4")         # SP += 4


def emit_call_sequence(asm, ret_label, target_func):
    """Generate a call to another runtime function (RA-direct, no push/pop).
    
    The caller must have already called emit_push_ra at function entry
    and must call emit_pop_ra before returning.
    
    Emits 3 instructions + the return point label:
      1-2. LI RA: clear RA, RA -= (-retaddr)   (load retaddr)
      3.   JMP target
      [ret_label:]   ← return point (callee returns here)
    
    The caller must define a constant pool entry:
        {ret_label}_neg:
            .word -{ret_label}
    
    Args:
        asm: List to append assembly lines to
        ret_label: Label name for the return point (e.g., ".Lmemset_head_sb_ret").
                   The CP entry "{ret_label}_neg" must store -({ret_label}).
        target_func: Target function symbol
    """
    # LI RA, retLabel (2 instructions)
    asm.append(f"        .word {ADDR_RA}, {ADDR_RA}, .+4")          # clear RA
    asm.append(f"        .word {ret_label}_neg, {ADDR_RA}, .+4")    # RA = 0 - (-retaddr) = +retaddr
    # JMP target (1 instruction)
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {target_func}")
    # Return point label (callee returns here via JMP RA|I)
    asm.append(f"{ret_label}:")


def emit_call_sequence_naked(asm, target_func):
    """Generate a call without setting RA (naked call).
    
    Use when RA is already set to the correct return label from a
    previous emit_call_sequence to the same return point.
    Saves 2 instructions vs emit_call_sequence.
    
    The caller must ensure RA still holds the correct return address.
    
    Emits 1 instruction:
      1. JMP target
    """
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {target_func}")


def emit_return_sequence(prefix):
    """Generate the return sequence for runtime functions (RA-direct).
    
    With the RA-direct convention, the return address is already in RA.
    Just jump to it: subleq(Z, Z, RA|I).
    
    Total: 1 instruction (was 4 + 2 constants)
    
    Args:
        prefix: Label prefix for this function (e.g., "udiv", "urem")
    
    Returns:
        List of assembly lines
    """
    asm = []
    
    # === Return via RA|I ===
    asm.append(f".L{prefix}_pop:")
    
    # Jump to return address using indirect addressing on C
    # subleq(Z, Z, RA|I): Z -= Z = 0, always branches to m[RA]
    asm.append(f"        .word   {ADDR_Z}")
    asm.append(f"        .word   {ADDR_Z}")
    asm.append(f"        .word   {ADDR_RA | INDIRECT_FLAG}")
    
    # NOTE: per-function _neg1/_neg4 constants removed.
    # Callers should use const_from_pool(-1) / const_from_pool(-4).
    
    return asm


def emit_all():
    """Generate all runtime functions by importing from separate modules."""
    # Import individual runtime functions from their modules
    from emit_and_o32 import emit_and_o32
    from emit_or_o32 import emit_or_o32
    from emit_xor_o32 import emit_xor_o32
    from emit_shl import emit_shl
    from emit_sb_packed import emit_sb
    from emit_lh import emit_lh
    from emit_sh import emit_sh
    
    # Import optimized versions
    from emit_lb_o1 import emit_lb as emit_lb_o1
    from emit_shift_unrolled import emit_srl as emit_srl_unrolled
    from emit_shift_unrolled import emit_sra as emit_sra_unrolled
    from emit_mul_o32 import emit_mul_o32
    
    # Import combined divrem functions (replaces separate div/rem)
    from emit_sdivrem_o32 import emit_sdivrem_o32
    from emit_udivrem_o32 import emit_udivrem_o32
    
    # Import 64-bit divrem functions (v3 based on working 32-bit implementation)
    from emit_sdivrem_o64 import emit_sdivrem_o64
    from emit_udivrem_o64 import emit_udivrem_o64
    
    # Import 64-bit division libcall wrappers (actual implementation)
    from emit_divdi3 import emit_divdi3
    
    # Reset pool state (allows emit_all to be called multiple times)
    _const_pool.clear()
    _const_pool_order.clear()
    
    asm = []
    


    
    # Each module gets its own .text.<name> section so that
    # ld --gc-sections can strip unreferenced runtime functions.
    sections = []
    
    # Combined division/remainder (O(32), returns both quotient and remainder)
    # The LLVM backend now custom-lowers SDIV/SREM/UDIV/UREM to use these
    sections.append(("__subleq_sdivrem", emit_sdivrem_o32()))
    sections.append(("__subleq_udivrem", emit_udivrem_o32()))
    
    # 64-bit division/remainder (O(64), for long long operations)
    sections.append(("__subleq_sdivrem64", emit_sdivrem_o64()))
    sections.append(("__subleq_udivrem64", emit_udivrem_o64()))
    
    # 64-bit division libcall wrappers (__divdi3, __moddi3, __udivdi3, __umoddi3)
    sections.append(("__divdi3", emit_divdi3()))
    
    # Multiplication (O(32) optimized)
    sections.append(("__subleq_mul", emit_mul_o32()))
    
    # Bitwise operations (O(32) optimized)
    sections.append(("__subleq_and", emit_and_o32()))
    sections.append(("__subleq_or", emit_or_o32()))
    sections.append(("__subleq_xor", emit_xor_o32()))
    
    # Shift operations
    sections.append(("__subleq_shl", emit_shl()))
    sections.append(("__subleq_srl", emit_srl_unrolled()))  # O(32-N) unrolled version
    sections.append(("__subleq_sra", emit_sra_unrolled()))  # O(32-N) unrolled version
    
    # Byte access (CHAR_BIT=8 support)
    sections.append(("__subleq_lb", emit_lb_o1()))    # O(1) modulo + O(32) bit extraction
    sections.append(("__subleq_sb", emit_sb()))       # O(32) with true byte packing
    
    # Halfword access (16-bit support for i16/u16)
    sections.append(("__subleq_lh", emit_lh()))       # Load halfword (zero-extending)
    sections.append(("__subleq_sh", emit_sh()))       # Store halfword (read-modify-write)
    
    # 64-bit shift libcall functions (__ashldi3, __lshrdi3, __ashrdi3)
    # Using v2 with O(32) bit extraction for right shifts
    from emit_shift_di3 import emit_shift_di3
    sections.append(("__shift_di3", emit_shift_di3()))
    
    # Memory operations (memcpy, memset, memmove) for LLVM/kernel support
    from emit_memory_ops import emit_memory_ops
    sections.append(("__subleq_memops", emit_memory_ops()))
    
    for section_name, lines in sections:
        asm.append(f'        .section .text.{section_name},"ax",@progbits')
        asm.extend(lines)
        asm.append("")
    
    # Emit the centralized constant pool as the final section
    asm.extend(emit_const_pool())
    asm.append("")
    
    return "\n".join(asm)


if __name__ == "__main__":
    print(emit_all())
