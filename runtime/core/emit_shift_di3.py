#!/usr/bin/env python3
"""
Generate 64-bit shift libcall functions for Subleq.

Functions:
  __ashldi3 - Arithmetic (logical) left shift
  __lshrdi3 - Logical right shift  
  __ashrdi3 - Arithmetic right shift

Signature: void __XXXdi3(i64* result_ptr, i64 a, i32 b);

Register-Based Calling Convention:
- Arg 0 (R21): result_ptr (pointer to memory for return value)
- Arg 1 (R22): a_lo
- Arg 2 (R23): a_hi  
- Arg 3 (R24): b (shift amount, 32-bit)

OPTIMIZED V4: Unrolled approach for ALL shifts.
- Left shift: fallthrough doubling chain (from V3)
- Right shift: DECOMPOSED into 3 inline lattice operations per shift amount:
    result_lo = SRL(a_lo, N) | SHL(a_hi, 32-N)
    result_hi = SRL(a_hi, N)  [or SRA for arithmetic]
  This is O(90) per lattice walk (regardless of N) vs old O(225*N) per-bit loop.

CRITICAL: Lattice exit can leave Z dirty (bit=0 branch path). Every post-lattice
join point must start with Z,Z,.+4 before using Z for register copies.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_runtime import (emit_return_sequence, ADDR_Z, ADDR_SP, ADDR_ZERO, ADDR_R20, ADDR_R21, ADDR_R22, ADDR_T0, ADDR_T1, ADDR_T2, ADDR_T3, ADDR_T11, INDIRECT_FLAG, ADDR_R23, ADDR_R24, const_from_pool)

ADDR_T4 = 44 * 4
ADDR_T5 = 45 * 4
ADDR_T6 = 46 * 4
ADDR_T7 = 47 * 4
ADDR_T8 = 48 * 4
ADDR_T9 = 49 * 4
ADDR_T10 = 50 * 4


def emit_inline_srl_lattice(asm, shift_amount, input_reg, result_reg, prefix, const_prefix, done_label):
    """Emit inline SRL lattice for input_reg >> shift_amount, accumulating into result_reg.
    
    Assumes: bit 31 handled/cleared, input biased +1.
    WARNING: Z may be DIRTY on exit (bit=0 branch path). Caller must clean Z.
    """
    current_states = {'Pos'}
    
    for bit in range(30, shift_amount - 1, -1):
        power = 1 << bit
        output_val = 1 << (bit - shift_amount)
        
        lbl_base = f"{prefix}_b{bit}"
        if bit == shift_amount:
            next_base_pos = done_label
            next_base_neg = done_label
        else:
            next_base_pos = f"{prefix}_b{bit-1}_Pos"
            next_base_neg = f"{prefix}_b{bit-1}_Neg"
            
        next_states = set()
        
        if 'Pos' in current_states:
            asm.append(f"{lbl_base}_Pos:")
            asm.append(f"        .word   {const_prefix}c{power}, {input_reg}, {next_base_neg}")
            if bit > shift_amount: next_states.add('Neg')
            asm.append(f"        .word   {const_prefix}n{output_val}, {result_reg}, .+4")
            if 'Neg' in current_states or bit == shift_amount:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_base_pos}")
            if bit > shift_amount: next_states.add('Pos')
            
        if 'Neg' in current_states:
            asm.append(f"{lbl_base}_Neg:")
            asm.append(f"        .word   {const_prefix}n{power}, {input_reg}, {next_base_neg}")
            if bit > shift_amount: next_states.add('Neg')
            asm.append(f"        .word   {const_prefix}n{output_val}, {result_reg}, .+4")
            if bit > shift_amount and 'Pos' in next_states:
                pass  # fall through
            else:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_base_pos}")
            if bit > shift_amount: next_states.add('Pos')
            
        current_states = next_states


def emit_inline_shl_lattice(asm, shift_amount, input_reg, result_reg, prefix, const_prefix, done_label):
    """Emit inline SHL lattice for input_reg << shift_amount, accumulating into result_reg.
    
    Assumes: bit 31 handled/cleared, input biased +1.
    Only accumulates bits where B+shift_amount < 32 (no overflow).
    WARNING: Z may be DIRTY on exit. Caller must clean Z.
    """
    current_states = {'Pos'}
    
    for bit in range(30, -1, -1):
        power = 1 << bit
        should_accumulate = (bit + shift_amount < 32)
        
        if should_accumulate:
            output_val = 1 << (bit + shift_amount)
        
        lbl_base = f"{prefix}_b{bit}"
        if bit == 0:
            next_base_pos = done_label
            next_base_neg = done_label
        else:
            next_base_pos = f"{prefix}_b{bit-1}_Pos"
            next_base_neg = f"{prefix}_b{bit-1}_Neg"
            
        next_states = set()
        
        if 'Pos' in current_states:
            asm.append(f"{lbl_base}_Pos:")
            asm.append(f"        .word   {const_prefix}c{power}, {input_reg}, {next_base_neg}")
            if bit > 0: next_states.add('Neg')
            if should_accumulate:
                asm.append(f"        .word   {const_prefix}n{output_val}, {result_reg}, .+4")
                # Need jump to next_pos if Neg in current_states or last bit
                if 'Neg' in current_states or bit == 0:
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_base_pos}")
            else:
                # No accumulate — always need to jump to next_pos
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_base_pos}")
            if bit > 0: next_states.add('Pos')
            
        if 'Neg' in current_states:
            asm.append(f"{lbl_base}_Neg:")
            asm.append(f"        .word   {const_prefix}n{power}, {input_reg}, {next_base_neg}")
            if bit > 0: next_states.add('Neg')
            if should_accumulate:
                asm.append(f"        .word   {const_prefix}n{output_val}, {result_reg}, .+4")
                if bit > 0 and 'Pos' in next_states:
                    pass  # fall through to next bit's Pos
                else:
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_base_pos}")
            else:
                # No accumulate — need jump to next_pos (can't just fall through)
                if bit > 0 and 'Pos' in next_states:
                    pass  # fall through to next bit's Pos
                else:
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_base_pos}")
            if bit > 0: next_states.add('Pos')
            
        current_states = next_states


def emit_bit31_check_clear(asm, input_reg, prefix, const_prefix, set_label, clear_label):
    """Emit bit 31 check and clear for input_reg.
    If bit 31 set: clears it, jumps to set_label (Z clean).
    If bit 31 not set: jumps to clear_label (Z clean).
    Z must be clean at entry. Z is clean at exit on all paths.
    """
    asm.append(f"{prefix}_b31:")
    asm.append(f"        .word   {ADDR_ZERO}, {input_reg}, {prefix}_b31_le0")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {clear_label}")
    
    asm.append(f"{prefix}_b31_le0:")
    asm.append(f"        .word   {const_prefix}n1, {input_reg}, {prefix}_b31_neg_restore")
    asm.append(f"        .word   {const_prefix}c1, {input_reg}, {clear_label}")
    
    asm.append(f"{prefix}_b31_neg_restore:")
    asm.append(f"        .word   {const_prefix}c1, {input_reg}, .+4")
    asm.append(f"        .word   {const_prefix}cmin, {input_reg}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {set_label}")


def emit_store_result(asm, p):
    """Emit code to store T5 (lo) and T6 (hi) to *T9 using indirect addressing."""
    asm.append(f".L{p}_done:")
    
    # Store T5 to m[T9]
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T0}, .+4")  # T0 = -T5
    asm.append(f"        .word   {ADDR_T9 | INDIRECT_FLAG}, {ADDR_T9 | INDIRECT_FLAG}, .+4")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T9 | INDIRECT_FLAG}, .+4")
    
    # Store T6 to m[T9+4]
    asm.append(f"        .word   .L{p}_m4, {ADDR_T9}, .+4")  # T9 += 4
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T0}, .+4")  # T0 = -T6
    asm.append(f"        .word   {ADDR_T9 | INDIRECT_FLAG}, {ADDR_T9 | INDIRECT_FLAG}, .+4")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T9 | INDIRECT_FLAG}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{p}_ret")
    
    # Restore T9 to R20, return
    asm.append(f".L{p}_ret:")
    asm.append(f"        .word   .L{p}_const4, {ADDR_T9}, .+4")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_T9}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{p}_pop")
    
    asm.extend(emit_return_sequence(p))


def emit_shift_di3():
    """Generate __ashldi3, __lshrdi3, __ashrdi3 shift functions."""
    asm = []
    asm.append("")
    asm.append("# ===== 64-bit Shift Libcall Functions (V4 - Fully Unrolled) =====")
    
    # === __ashldi3: unchanged from V3 ===
    func_name = "__ashldi3"
    p = "ashldi3"
    asm.append("")
    asm.append(f"        .globl  {func_name}")
    asm.append(f"        .type   {func_name},@function")
    asm.append(f"# {func_name}: 64-bit left shift (unrolled fallthrough chain)")
    asm.append(f"{func_name}:")
    
    # Save result pointer (R21) to T9
    asm.append(f"        .word   {ADDR_T9}, {ADDR_T9}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T9}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    
    # Copy R22 -> T5, R23 -> T6
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T5}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word   {ADDR_R23}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")
    
    # Check R24 <= 0
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R24}, .L{p}_done")
    
    # Check R24 >= 64
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   .L{p}_n64, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R24}, {ADDR_T0}, .L{p}_zero")
    
    # Check R24 >= 32
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   .L{p}_n32, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R24}, {ADDR_T0}, .L{p}_swap")
    
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{p}_disp")
    
    # Word swap: T6 = T5, T5 = 0, R24 -= 32
    asm.append(f".L{p}_swap:")
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T5}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word   .L{p}_c32, {ADDR_R24}, .L{p}_done")
    
    # Dispatch 1..31
    asm.append(f".L{p}_disp:")
    for i in range(1, 32):
        asm.append(f"        .word   .L{p}_c1, {ADDR_R24}, .L{p}_do_{i}")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{p}_done")
    
    asm.append(f".L{p}_zero:")
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .L{p}_done")
    
    # Fallthrough doubling chain for 64-bit left shift
    for i in range(31, 0, -1):
        asm.append(f".L{p}_do_{i}:")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T5}, .L{p}_chk{i}")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{p}_d{i}")
        
        asm.append(f".L{p}_chk{i}:")
        asm.append(f"        .word   .L{p}_n1, {ADDR_T5}, .L{p}_carry{i}")
        asm.append(f"        .word   .L{p}_c1, {ADDR_T5}, .L{p}_d{i}")
        
        asm.append(f".L{p}_carry{i}:")
        asm.append(f"        .word   .L{p}_c1, {ADDR_T5}, .+4")
        asm.append(f"        .word   .L{p}_n1, {ADDR_T7}, .L{p}_d{i}")
        
        asm.append(f".L{p}_d{i}:")
        # Double T5
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T5}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T5}, .+4")
        # Double T6
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")
        # Add carry
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")
    
    emit_store_result(asm, p)
    
    asm.append(f".L{p}_c1:  .word   1")
    asm.append(f".L{p}_n1:  .word   -1")
    asm.append(f".L{p}_const4:  .word   4")
    asm.append(f".L{p}_m4:  .word   -4")
    asm.append(f".L{p}_c32: .word   32")
    asm.append(f".L{p}_n32: .word   -32")
    asm.append(f".L{p}_n64: .word   -64")
    
    asm.append(f"        .size   {func_name}, . - {func_name}")

    # === __lshrdi3 / __ashrdi3: V4 unrolled decomposition ===
    for func_name, is_arithmetic in [
        ("__lshrdi3", False),
        ("__ashrdi3", True),
    ]:
        p = func_name.replace("__", "")
        lp = p
        asm.append("")
        asm.append(f"        .globl  {func_name}")
        asm.append(f"        .type   {func_name},@function")
        asm.append(f"# {func_name}: 64-bit {'arithmetic' if is_arithmetic else 'logical'} right shift (V4)")
        asm.append(f"{func_name}:")
        
        # Save result pointer (R21) to T9
        asm.append(f"        .word   {ADDR_T9}, {ADDR_T9}, .+4")
        asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T9}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        
        # Copy R22 -> T5 (lo), R23 -> T6 (hi)
        asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
        asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T5}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_R23}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")
        
        # Check R24 <= 0
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R24}, .L{lp}_done")
        
        # Check R24 >= 64
        asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
        asm.append(f"        .word   .L{lp}_n64, {ADDR_T0}, .+4")
        asm.append(f"        .word   {ADDR_R24}, {ADDR_T0}, .L{lp}_big")
        
        # Check R24 >= 32
        asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
        asm.append(f"        .word   .L{lp}_n32, {ADDR_T0}, .+4")
        asm.append(f"        .word   {ADDR_R24}, {ADDR_T0}, .L{lp}_swap")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_disp")
        
        # Big shift (>=64)
        asm.append(f".L{lp}_big:")
        if is_arithmetic:
            # If hi < 0 -> all -1, else all 0
            asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .L{lp}_bchk")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_zero")
            asm.append(f".L{lp}_bchk:")
            # T6 <= 0: disambiguate 0 from negative
            asm.append(f"        .word   .L{lp}_n1, {ADDR_T6}, .L{lp}_allneg")  # T6+=1; if <=0, neg
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_zero")  # was 0
            asm.append(f".L{lp}_allneg:")
            asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
            asm.append(f"        .word   .L{lp}_c1, {ADDR_T5}, .+4")  # T5 = -1
            asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
            asm.append(f"        .word   .L{lp}_c1, {ADDR_T6}, .L{lp}_done")  # T6 = -1
        else:
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_zero")
            
        asm.append(f".L{lp}_zero:")
        asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .L{lp}_done")
        
        # Word swap: T5 = T6, T6 = 0 or sign-extended
        asm.append(f".L{lp}_swap:")
        asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T5}, .+4")   # T5 = T6
        asm.append(f"        .word   .L{lp}_c32, {ADDR_R24}, .+4")  # R24 -= 32
        
        if is_arithmetic:
            # Sign extend: T6 = (old T6 < 0) ? -1 : 0
            # T5 = old T6 now. Check T5 sign.
            asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T5}, .L{lp}_se_le0")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_se_pos")
            asm.append(f".L{lp}_se_le0:")
            asm.append(f"        .word   .L{lp}_n1, {ADDR_T5}, .L{lp}_se_neg")  # T5+=1; <=0 -> neg
            asm.append(f"        .word   .L{lp}_c1, {ADDR_T5}, .L{lp}_se_pos")  # was 0, restore
            asm.append(f".L{lp}_se_neg:")
            asm.append(f"        .word   .L{lp}_c1, {ADDR_T5}, .+4")  # restore T5
            asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
            asm.append(f"        .word   .L{lp}_c1, {ADDR_T6}, .L{lp}_chk0")  # T6 = -1
            asm.append(f".L{lp}_se_pos:")
            asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .L{lp}_chk0")  # T6 = 0
        else:
            asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .L{lp}_chk0")  # T6 = 0
        
        # Check R24 == 0 (shift was exactly 32)
        asm.append(f".L{lp}_chk0:")
        asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_R24}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T0}, .+4")
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T0}, .L{lp}_done")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_disp")
        
        # Dispatch 1..31
        asm.append(f".L{lp}_disp:")
        for i in range(1, 32):
            asm.append(f"        .word   .L{lp}_c1, {ADDR_R24}, .L{lp}_shift_{i}")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_done")
        
        # ===== UNROLLED SHIFT PATHS =====
        const_prefix = f".L{lp}_"
        
        for N in range(1, 32):
            asm.append(f"")
            asm.append(f".L{lp}_shift_{N}:")
            
            # ---- Step 1: T2 = SRL(T5, N) ----
            asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")
            
            emit_bit31_check_clear(asm, ADDR_T5, f".L{lp}_s{N}_lo", const_prefix,
                                   f".L{lp}_s{N}_lo_b31set", f".L{lp}_s{N}_lo_bias")
            
            asm.append(f".L{lp}_s{N}_lo_b31set:")
            out_val = 1 << (31 - N)
            asm.append(f"        .word   {const_prefix}n{out_val}, {ADDR_T2}, .+4")
            
            asm.append(f".L{lp}_s{N}_lo_bias:")
            asm.append(f"        .word   {const_prefix}n1, {ADDR_T5}, .+4")
            if N <= 30:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_s{N}_lo_lat_b30_Pos")
                emit_inline_srl_lattice(asm, N, ADDR_T5, ADDR_T2,
                                        f".L{lp}_s{N}_lo_lat", const_prefix,
                                        f".L{lp}_s{N}_carry")
            else:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_s{N}_carry")
            
            # ---- Step 2: T0 = SHL(T6, 32-N) ----
            shl_amount = 32 - N
            asm.append(f".L{lp}_s{N}_carry:")
            # Z MAY BE DIRTY from lattice exit — clean it (N<=30 only;
            # for N=31 no lattice runs and all paths arrive via Z,Z,label)
            if N <= 30:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
            asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
            
            # Copy T6 -> T1 (preserve T6 for step 4)
            asm.append(f"        .word   {ADDR_T1}, {ADDR_T1}, .+4")
            asm.append(f"        .word   {ADDR_T6}, {ADDR_Z}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_T1}, .+4")   # T1 = T6
            
            emit_bit31_check_clear(asm, ADDR_T1, f".L{lp}_s{N}_cr", const_prefix,
                                   f".L{lp}_s{N}_cr_b31set", f".L{lp}_s{N}_cr_bias")
            
            asm.append(f".L{lp}_s{N}_cr_b31set:")
            # Bit 31 shifted left always overflows 32 bits. No contribution.
            
            asm.append(f".L{lp}_s{N}_cr_bias:")
            asm.append(f"        .word   {const_prefix}n1, {ADDR_T1}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_s{N}_cr_lat_b30_Pos")
            emit_inline_shl_lattice(asm, shl_amount, ADDR_T1, ADDR_T0,
                                    f".L{lp}_s{N}_cr_lat", const_prefix,
                                    f".L{lp}_s{N}_combine")
            
            # ---- Step 3: T5 = T2 + T0 ----
            asm.append(f".L{lp}_s{N}_combine:")
            # Z MAY BE DIRTY from lattice exit — clean it
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
            asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
            asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_T5}, .+4")   # T5 = T2
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
            asm.append(f"        .word   {ADDR_T0}, {ADDR_Z}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_T5}, .+4")   # T5 += T0
            
            # ---- Step 4: T6 = SRL(T6, N) or SRA(T6, N) ----
            asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")
            
            if is_arithmetic:
                # SRA: ~(~x >> N). Check sign, compute NOT, SRL, then NOT result.
                asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")  # T0 = sign flag
                
                emit_bit31_check_clear(asm, ADDR_T6, f".L{lp}_s{N}_hi", const_prefix,
                                       f".L{lp}_s{N}_hi_b31set", f".L{lp}_s{N}_hi_bias")
                
                asm.append(f".L{lp}_s{N}_hi_b31set:")
                asm.append(f"        .word   {const_prefix}n1, {ADDR_T0}, .+4")  # T0 = 1 (sign set)
                # T6 has bit 31 cleared. Compute NOT: T6 = INT_MAX - T6
                # T6 = -T6 + INT_MAX
                asm.append(f"        .word   {ADDR_T1}, {ADDR_T1}, .+4")
                asm.append(f"        .word   {ADDR_T6}, {ADDR_T1}, .+4")      # T1 = -T6
                asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")      # T6 = 0
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")       # T6 = -old_T6
                asm.append(f"        .word   {const_prefix}nintmax, {ADDR_T6}, .+4")  # T6 += INT_MAX
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_s{N}_hi_bias")
                
                asm.append(f".L{lp}_s{N}_hi_bias:")
                asm.append(f"        .word   {const_prefix}n1, {ADDR_T6}, .+4")
                if N <= 30:
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_s{N}_hi_lat_b30_Pos")
                    emit_inline_srl_lattice(asm, N, ADDR_T6, ADDR_T2,
                                            f".L{lp}_s{N}_hi_lat", const_prefix,
                                            f".L{lp}_s{N}_hi_fix")
                else:
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_s{N}_hi_fix")
                
                # Fix: if was negative, result = ~T2 = -T2 - 1
                asm.append(f".L{lp}_s{N}_hi_fix:")
                # Z MAY BE DIRTY from lattice exit — clean it (N<=30 only;
                # for N=31 no lattice runs and all paths arrive via Z,Z,label)
                if N <= 30:
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T0}, .L{lp}_s{N}_hi_pos")
                # T0 > 0: was negative
                asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
                asm.append(f"        .word   {ADDR_T2}, {ADDR_T6}, .+4")      # T6 = -T2
                asm.append(f"        .word   {const_prefix}c1, {ADDR_T6}, .L{lp}_done")  # T6 = -T2-1 = ~T2
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_done")
                
                asm.append(f".L{lp}_s{N}_hi_pos:")
                # T0 = 0: was positive
                asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
                asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_done")
            else:
                # LSHR: straight SRL
                emit_bit31_check_clear(asm, ADDR_T6, f".L{lp}_s{N}_hi", const_prefix,
                                       f".L{lp}_s{N}_hi_b31set", f".L{lp}_s{N}_hi_bias")
                
                asm.append(f".L{lp}_s{N}_hi_b31set:")
                out_val = 1 << (31 - N)
                asm.append(f"        .word   {const_prefix}n{out_val}, {ADDR_T2}, .+4")
                
                asm.append(f".L{lp}_s{N}_hi_bias:")
                asm.append(f"        .word   {const_prefix}n1, {ADDR_T6}, .+4")
                if N <= 30:
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_s{N}_hi_lat_b30_Pos")
                    emit_inline_srl_lattice(asm, N, ADDR_T6, ADDR_T2,
                                            f".L{lp}_s{N}_hi_lat", const_prefix,
                                            f".L{lp}_s{N}_hi_copy")
                else:
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_s{N}_hi_copy")
                
                asm.append(f".L{lp}_s{N}_hi_copy:")
                # Z MAY BE DIRTY from lattice exit — clean it (N<=30 only;
                # for N=31 no lattice runs and all paths arrive via Z,Z,label)
                if N <= 30:
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
                asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{lp}_done")
        
        emit_store_result(asm, lp)
        
        # Constants — deduplicated
        consts = {}
        consts[f".L{lp}_c1"] = 1
        consts[f".L{lp}_n1"] = -1
        consts[f".L{lp}_const4"] = 4
        consts[f".L{lp}_m4"] = -4
        consts[f".L{lp}_c32"] = 32
        consts[f".L{lp}_cmin"] = -2147483648
        if is_arithmetic:
            consts[f".L{lp}_nintmax"] = -2147483647
        for i in range(1, 31):
            consts[f".L{lp}_c{1 << i}"] = 1 << i
        for i in range(0, 32):
            consts[f".L{lp}_n{1 << i}"] = -(1 << i)
        for label, val in consts.items():
            asm.append(f"{label}:")
            asm.append(f"        .word   {val}")
        
        asm.append(f"        .size   {func_name}, . - {func_name}")
    
    return asm


if __name__ == "__main__":
    for line in emit_shift_di3():
        print(line)
