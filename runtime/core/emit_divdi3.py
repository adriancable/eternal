#!/usr/bin/env python3
"""
Generate 64-bit division libcall wrappers for Subleq.

These functions implement the GCC libcall ABI for targets that return 64-bit values via invisible pointer (sret).
LLVM's Subleq backend (standard configuration) forces "sret" for i64 returns.

Signature: void __divdi3(i64* result_ptr, i64 a, i64 b);

Register-Based Calling Convention (new ABI):
- Arg 0 (R21): result_ptr (pointer to memory for return value)
- Arg 1 (R22): a_lo
- Arg 2 (R23): a_hi
- Arg 3 (R24): b_lo
- Arg 4 (Stack): b_hi (5th arg overflows to stack)

With RA-direct convention:
- RA is in the register (not pushed to stack)
- SP+0 = b_hi (no RA on stack)

Function Logic:
1. Save result_ptr (from R21) to a preserved temporary (T11).
2. Load arguments into proper registers for __subleq_sdivrem64:
   - R21 = a_lo (from R22)
   - R22 = a_hi (from R23)
   - R23 = b_lo (from R24)
   - R24 = b_hi (from SP+4)
   Note: __subleq_sdivrem64 expects R21:R22 = dividend (lo:hi), R23:R24 = divisor (lo:hi)
3. Call __subleq_sdivrem64 / __subleq_udivrem64.
   - Returns R21:R22 = quotient (lo:hi), R23:R24 = remainder (lo:hi).
4. If Modulo, move Remainder (R23:R24) to Result regs (R21:R22).
5. Store Result (R21:R22) to memory at [result_ptr] (restored from T11).
6. Restore result_ptr to R20 (return value register).
7. Return.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_runtime import (emit_return_sequence, emit_call_sequence, emit_push_ra, emit_pop_ra, ADDR_Z, ADDR_SP, ADDR_RA, ADDR_ZERO, ADDR_T0, ADDR_T1, ADDR_T2, ADDR_T3, ADDR_T11, ADDR_R20, ADDR_R21, ADDR_R22, ADDR_R23, ADDR_R24, INDIRECT_FLAG, const_from_pool)

def emit_load_from_sp_offset(asm, prefix, stage, dest_reg, offset):
    """Generate code to load a value from [SP + offset] into dest_reg using indirect addressing."""
    # Goal: compute addr = SP + offset into T1, then use T1|I for indirect load
    
    # Step 1: T1 = SP (copy SP to T1)
    asm.append(f".L{prefix}_{stage}_1:")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_T1}, .+4")  # T1 = 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")    # Z = 0
    asm.append(f"        .word   {ADDR_SP}, {ADDR_Z}, .+4")   # Z = -SP
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T1}, .+4")   # T1 = -Z = SP
    
    # Step 2: T1 = T1 + offset = SP + offset  (using T1 -= -offset)
    asm.append(f"        .word   .L{prefix}_soff{offset}, {ADDR_T1}, .+4")  # T1 = T1 - (-offset) = SP + offset
    
    # Step 3: Load from m[T1] using indirect addressing
    asm.append(f"        .word   {dest_reg}, {dest_reg}, .+4")  # dest = 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")      # Z = 0
    # Use T1|I on A operand: Z = Z - m[m[ADDR_T1]] = Z - m[T1] = -m[T1]
    asm.append(f"        .word   {ADDR_T1 | INDIRECT_FLAG}, {ADDR_Z}, .+4")
    # dest = dest - Z = 0 - (-m[T1]) = m[T1]
    asm.append(f"        .word   {ADDR_Z}, {dest_reg}, .L{prefix}_{stage}_done")
    asm.append(f".L{prefix}_{stage}_done:")


def emit_store_to_ptr_corrected(asm, prefix, stage, val_reg, ptr_reg):
    """Store val_reg to m[ptr_reg] using indirect addressing (no SMC)."""
    # ptr_reg is address of a register (e.g., ADDR_T11) which contains the destination address
    # We use ptr_reg|I to access m[m[ptr_reg]]
    
    # 1. Compute T1 = -val
    asm.append(f".L{prefix}_{stage}_st1:")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {val_reg}, {ADDR_T1}, .+4") # T1 = -val
    
    # 2. Clear m[ptr] using indirect addressing: m[m[ptr_reg]] = 0
    # subleq(ptr_reg|I, ptr_reg|I, next) does: m[m[ptr_reg]] = m[m[ptr_reg]] - m[m[ptr_reg]] = 0
    asm.append(f"        .word   {ptr_reg | INDIRECT_FLAG}, {ptr_reg | INDIRECT_FLAG}, .+4")
    
    # 3. Store val to m[ptr]: m[m[ptr_reg]] -= T1, so m[m[ptr_reg]] = 0 - (-val) = val
    asm.append(f"        .word   {ADDR_T1}, {ptr_reg | INDIRECT_FLAG}, .L{prefix}_{stage}_done")
    asm.append(f".L{prefix}_{stage}_done:")


def emit_divdi3():
    """Generate wrappers with sret support using REGISTER-BASED calling convention (new ABI)."""
    asm = []
    asm.append("")
    asm.append("# ===== 64-bit Division Libcall Wrappers (SRET) =====")
    asm.append("# Register-based Calling Convention: R21=sret, R22=a_lo, R23=a_hi, R24=b_lo, Stack=b_hi")
    
    needed_offsets = set()
    
    for func_name, is_signed, returns_quotient in [
        ("__divdi3", True, True),
        ("__moddi3", True, False),
        ("__udivdi3", False, True),
        ("__umoddi3", False, False),
    ]:
        asm.append("")
        asm.append(f"        .globl  {func_name}")
        asm.append(f"        .type   {func_name},@function")
        asm.append(f"{func_name}:")
        emit_push_ra(asm)
        
        prefix = func_name.replace("__", "")
        divrem_func = "__subleq_sdivrem64" if is_signed else "__subleq_udivrem64"
        
        # Arguments on entry (RA-direct convention):
        # R21 = sret_ptr (first arg)
        # R22 = a_lo (second arg)
        # R23 = a_hi (third arg)
        # R24 = b_lo (fourth arg)
        # SP+0 = b_hi (fifth arg, overflows to stack; no RA on stack)
        
        # 1. Save Result Pointer (R21) to T11
        # T11 = R21 (Z clean at function entry from caller's return)
        asm.append(f"        .word   {ADDR_T11}, {ADDR_T11}, .+4") # Clear T11
        asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")  # Z = -R21
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T11}, .+4")  # T11 = -Z = R21
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")   # Clear Z
        
        # 2. Copy arguments from new ABI registers to runtime registers
        # __subleq_sdivrem64 expects:
        #   R21:R22 = dividend (lo:hi)
        #   R23:R24 = divisor (lo:hi)
        #
        # R22 (a_lo) -> R21
        # R23 (a_hi) -> R22
        # R24 (b_lo) -> R23
        # SP+4 (b_hi) -> R24
        
        # R21 = R22 (a_lo)
        asm.append(f"        .word   {ADDR_R21}, {ADDR_R21}, .+4") # Clear R21
        asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")  # Z = -R22
        asm.append(f"        .word   {ADDR_Z}, {ADDR_R21}, .+4")   # R21 = -Z = R22
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")    # Clear Z
        
        # R22 = R23 (a_hi)
        asm.append(f"        .word   {ADDR_R22}, {ADDR_R22}, .+4") # Clear R22
        asm.append(f"        .word   {ADDR_R23}, {ADDR_Z}, .+4")  # Z = -R23
        asm.append(f"        .word   {ADDR_Z}, {ADDR_R22}, .+4")   # R22 = -Z = R23
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")    # Clear Z
        
        # R23 = R24 (b_lo)
        # OPT-5: Skip trailing Z-clear — emit_load_from_sp_offset clears Z itself
        asm.append(f"        .word   {ADDR_R23}, {ADDR_R23}, .+4") # Clear R23
        asm.append(f"        .word   {ADDR_R24}, {ADDR_Z}, .+4")  # Z = -R24
        asm.append(f"        .word   {ADDR_Z}, {ADDR_R23}, .+4")   # R23 = -Z = R24

        
        # R24 = [SP+4] (b_hi from stack; +4 because emit_push_ra pushed RA)
        needed_offsets.add(4)
        emit_load_from_sp_offset(asm, prefix, "bhi", ADDR_R24, 4)
        
        # 3. Call divrem using RA-direct call sequence
        asm.append(f"        # Call {divrem_func}")
        emit_call_sequence(asm, f".L{prefix}_post_call", divrem_func)
        
        # 4. Handle Result (Mod vs Div)
        # __subleq_sdivrem64 returns: R21:R22 = quotient (lo:hi), R23:R24 = remainder (lo:hi)
        if not returns_quotient:
            # Move R23:R24 to R21:R22 (remainder to quotient position)
             asm.append(f"        .word   {ADDR_R21}, {ADDR_R21}, .+4")
             asm.append(f"        .word   {ADDR_R23}, {ADDR_Z}, .+4")
             asm.append(f"        .word   {ADDR_Z}, {ADDR_R21}, .+4") # R21 = R23 (rem_lo)
             asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
             
             asm.append(f"        .word   {ADDR_R22}, {ADDR_R22}, .+4")
             asm.append(f"        .word   {ADDR_R24}, {ADDR_Z}, .+4")
             asm.append(f"        .word   {ADDR_Z}, {ADDR_R22}, .+4") # R22 = R24 (rem_hi)
             asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        
        # 5. Store Result R21:R22 to [T11]
        # Low word at [T11]
        emit_store_to_ptr_corrected(asm, prefix, "st_lo", ADDR_R21, ADDR_T11)
        
        # High word at [T11+4]
        # Increment T11 by 4
        asm.append(f".L{prefix}_inc_ptr:")
        asm.append(f"        .word   {const_from_pool(-4)}, {ADDR_T11}, .+4") # T11 -= -4 => T11 += 4
        emit_store_to_ptr_corrected(asm, prefix, "st_hi", ADDR_R22, ADDR_T11)
        
        # Restore T11 to original value?
        # Function returns `result_ptr`.
        # T11 is now `ptr+4`. We need `ptr`.
        # Subtract 4.
        asm.append(f"        .word   .L{prefix}_c4, {ADDR_T11}, .+4")
        
        # 6. Restore result_ptr to R20 (return value register in new ABI)
        # R20 = T11
        asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
        asm.append(f"        .word   {ADDR_T11}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .+4")
        
        # 7. Return
        emit_pop_ra(asm)
        asm.extend(emit_return_sequence(prefix))
        
        # Constants
        asm.append(f".L{prefix}_c4:")
        asm.append("        .word   4")
        # Note: neg4 is already defined by emit_return_sequence
        asm.append(f".L{prefix}_post_call_neg:")
        asm.append(f"        .word   -.L{prefix}_post_call")
        
        for offset in needed_offsets:
             asm.append(f".L{prefix}_soff{offset}:")
             asm.append(f"        .word   -{offset}")
             
        asm.append(f"        .size   {func_name}, . - {func_name}")

    return asm

if __name__ == "__main__":
    for line in emit_divdi3():
        print(line)
