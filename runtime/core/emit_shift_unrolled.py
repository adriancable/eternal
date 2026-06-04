#!/usr/bin/env python3
"""
Unrolled shift operations with Biased Lattice Optimization.

Instead of iterating shift_count times with 30 bit tests per iteration,
we jump directly to a code path for each specific shift amount (1-31).

Optimization (Biased Lattice):
- Unrolled Entry: Jump table dispatches to specific handler for shift amount K.
- Input (Value to Shift) is biased by +1.
- Loop Bits 30 down to K:
  - Check Input Bit (Lattice Transition):
    - State Pos: Sub 2^bit. If > 0, Bit is 1 (Stay Pos). If <= 0, Bit is 0 (Go Neg).
    - State Neg: Add 2^bit. If > 0, Bit is 1 (Go Pos). If <= 0, Bit is 0 (Stay Neg).
  - If Bit is 1 (implied by transition): Add 2^(bit-K) or 2^(bit+K) to result.
- Efficiency: Execution path contains only ~3 instructions per input bit (Sub, Add, Jump).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_runtime import (emit_return_sequence, ADDR_Z, ADDR_SP, ADDR_ZERO, ADDR_R20, ADDR_R21, ADDR_R22, ADDR_T0, ADDR_T1, ADDR_T2, ADDR_T3, const_from_pool, ADDR_ONE, ADDR_MINUS_ONE)

# Additional temporary registers
ADDR_T4 = 44 * 4      # = 176
ADDR_T5 = 45 * 4      # = 180
ADDR_T6 = 46 * 4      # = 184


def emit_binary_dispatch(asm, lo, hi, prefix, reg):
    """Emit a binary tree dispatch for shift amounts in [lo, hi].
    
    Uses binary search on reg (R22). R22 is consumed (dead after dispatch).
    prefix: label prefix for shift targets (e.g. ".Lsrl" → ".Lsrl_shift_1")
    For [1, 31]: 5 levels max, ~5 instructions per call vs ~16 average linear.
    """
    def emit_tree(entries, label_prefix, depth):
        """Binary dispatch over a list of (reg_value, target_shift) pairs."""
        n = len(entries)
        if n == 1:
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_shift_{entries[0][1]}")
            return
        
        if n == 2:
            rv = entries[0][0]
            asm.append(f"        .word   {const_from_pool(rv)}, {reg}, {prefix}_shift_{entries[0][1]}")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_shift_{entries[1][1]}")
            return
        
        mid_idx = n // 2
        left = entries[:mid_idx]
        right = entries[mid_idx:]
        threshold = left[-1][0]
        
        left_label = f"{label_prefix}_L{depth}"
        
        asm.append(f"        .word   {const_from_pool(threshold)}, {reg}, {left_label}")
        
        right_rebased = [(rv - threshold, sh) for rv, sh in right]
        emit_tree(right_rebased, label_prefix + "R", depth + 1)
        
        asm.append(f"{left_label}:")
        asm.append(f"        .word   {const_from_pool(-threshold)}, {reg}, .+4")
        emit_tree(left, label_prefix + "L", depth + 1)
    
    entries = [(i, i) for i in range(lo, hi + 1)]
    emit_tree(entries, f"{prefix}_bd", 0)






def emit_lattice_shift_core(asm, shift_amount, prefix, store_label, result_reg=None):
    """Emit the lattice core for shifting R21 into result_reg (default T2).
     Assumes Bit 31 handled/cleared.
     Assumes R21 biased by +1.
     prefix: Label prefix (e.g., 'Lsrl' or 'Lsra')
     store_label: Label to jump to when done.
    """
    if result_reg is None:
        result_reg = ADDR_T2
    current_states = {'Pos'}
    
    # Range 30 down to shift_amount
    for bit in range(30, shift_amount - 1, -1):
        power = 1 << bit
        output_val = 1 << (bit - shift_amount)
        
        lbl_base = f".{prefix}{shift_amount}_b{bit}"
        if bit == shift_amount:
            next_base_pos = store_label # Both states go to store next
            next_base_neg = store_label
        else:
            # Next is bit-1
            next_base_pos = f".{prefix}{shift_amount}_b{bit-1}_Pos"
            next_base_neg = f".{prefix}{shift_amount}_b{bit-1}_Neg"
            
        next_states = set()
        
        # --- Pos State ---
        if 'Pos' in current_states:
            asm.append(f"{lbl_base}_Pos:")
            asm.append(f"        .word   .{prefix}_c{power}, {ADDR_R21}, {next_base_neg}")
            if bit > shift_amount: next_states.add('Neg')
            
            # --- Pos -> Pos (Bit 1) ---
            asm.append(f"        .word   .{prefix}_n{output_val}, {result_reg}, .+4")
            
            if 'Neg' in current_states and bit > shift_amount:
                # INLINE: replace Z,Z,next_Pos skip with the next bit's Pos test.
                # Saves 1 op per Pos→Pos by doing useful work instead of dead skip.
                next_bit = bit - 1
                next_power = 1 << next_bit
                next_output = 1 << (next_bit - shift_amount)
                if next_bit == shift_amount:
                    inline_neg_target = store_label
                    inline_pos_target = store_label
                else:
                    inline_neg_target = f".{prefix}{shift_amount}_b{next_bit-1}_Neg"
                    inline_pos_target = f".{prefix}{shift_amount}_b{next_bit-1}_Pos"
                asm.append(f"        .word   .{prefix}_c{next_power}, {ADDR_R21}, {inline_neg_target}")
                asm.append(f"        .word   .{prefix}_n{next_output}, {result_reg}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {inline_pos_target}")
            elif bit == shift_amount:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_base_pos}")
            # else: Neg not in current_states, fall through to next Pos
            if bit > shift_amount: next_states.add('Pos')
            
        # --- Neg State ---
        if 'Neg' in current_states:
            asm.append(f"{lbl_base}_Neg:")
            asm.append(f"        .word   .{prefix}_n{power}, {ADDR_R21}, {next_base_neg}")
            if bit > shift_amount: next_states.add('Neg')
            
            # --- Neg -> Pos (Bit 1) ---
            asm.append(f"        .word   .{prefix}_n{output_val}, {result_reg}, .+4")
            # Fallthrough optimization: if next Pos is emitted next, skip the jump
            if bit > shift_amount and 'Pos' in next_states:
                pass  # fall through to next bit's Pos
            else:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_base_pos}")
            if bit > shift_amount: next_states.add('Pos')
            
            # Removed {lbl_base}_Neg_to_Neg
            
        current_states = next_states


def emit_srl_shift_path(asm, shift_amount):
    asm.append(f"")
    # Global split-entry point: skips dispatch chain entirely
    asm.append(f"        .globl  __subleq_srl_{shift_amount}")
    asm.append(f"__subleq_srl_{shift_amount}:")
    asm.append(f".Lsrl_shift_{shift_amount}:")
    
    # R20 = 0 (result — accumulate directly into return register)
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    
    # === Bit 31 (Robust) ===
    prefix = f"srl{shift_amount}_b31"
    
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .L{prefix}_chk") 
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .L{prefix}_setup")
    
    asm.append(f".L{prefix}_chk:")
    # OPTIMIZED: Combined restore+branch (operates on R21 directly)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .L{prefix}_neg_restore")  # R21 += 1; if <= 0 → negative
    # R21 was 0 (now 1): restore and skip to setup (always branches)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .L{prefix}_setup")  # restore+branch
    
    asm.append(f".L{prefix}_neg_restore:")
    # R21 was < 0: restore R21 (always branches via .+4)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .+4")  # restore+branch
    
    asm.append(f".L{prefix}_set:")
    out_val = 1 << (31 - shift_amount)
    asm.append(f"        .word   .Lsrl_c2147483648, {ADDR_R21}, .+4")
    asm.append(f"        .word   .Lsrl_n{out_val}, {ADDR_R20}, .+4")  # accumulate into R20 directly
    
    asm.append(f".L{prefix}_setup:")
    # Bias R21 += 1
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")
    
    # Lattice Core — accumulates into R20 directly
    emit_lattice_shift_core(asm, shift_amount, "Lsrl", f".Lsrl{shift_amount}_done", result_reg=ADDR_R20)
    
    # Done — R20 already has the result (no copy needed)
    asm.append(f".Lsrl{shift_amount}_done:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_ZERO}, .Lsrl_done")


def emit_sra_shift_path(asm, shift_amount):
    asm.append(f"")
    # Global split-entry point: skips dispatch chain entirely
    asm.append(f"        .globl  __subleq_sra_{shift_amount}")
    asm.append(f"__subleq_sra_{shift_amount}:")
    asm.append(f".Lsra_shift_{shift_amount}:")
    
    # T5 = 0 (sign flag)
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .Lsra{shift_amount}_chksign")
    
    asm.append(f".Lsra{shift_amount}_chksign:")
    # Non-destructive sign test: ZERO,R21 does R21 -= 0 = R21 (unchanged)
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Lsra{shift_amount}_maybe_neg")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsra{shift_amount}_pos")
    
    asm.append(f".Lsra{shift_amount}_maybe_neg:")
    # OPTIMIZED: Combined restore+branch (operates on R21 directly)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .Lsra{shift_amount}_neg_restore")  # R21 += 1; if <= 0 → negative
    # R21 was 0 (now 1): restore and skip to pos (always branches)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Lsra{shift_amount}_pos")  # restore+branch
    
    asm.append(f".Lsra{shift_amount}_neg_restore:")
    # R21 was < 0: restore R21 (always branches via .+4)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .+4")  # restore+branch 
    
    asm.append(f".Lsra{shift_amount}_neg:")
    # Negate T1 = -T1 - 1
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T5}, .+4") # T5=1
    asm.append(f"        .word   {ADDR_T3}, {ADDR_T3}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_T3}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Lsra{shift_amount}_pos")
    
    asm.append(f".Lsra{shift_amount}_pos:")
    # R20 = 0 (result — accumulate directly into return register)
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    
    # Bias Setup
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4") # R21 += 1
    
    # Jump to Lattice Start.
    if shift_amount == 31:
        # Skip Lattice. Go to sign correction.
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsra{shift_amount}_sign_correct")
    else:
        # Jump to Bit 30 Pos (Start of Lattice for SRA)
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsra{shift_amount}_b30_Pos")
    
    # Lattice Core — accumulates into R20 directly
    emit_lattice_shift_core(asm, shift_amount, "Lsra", f".Lsra{shift_amount}_sign_correct", result_reg=ADDR_R20)
    
    asm.append(f".Lsra{shift_amount}_sign_correct:")
    # Check T5 (sign flag). If T5 <= 0 (was positive), skip negation.
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T5}, .Lsra{shift_amount}_done")
    # Negate R20 in-place: R20 = -R20 - 1
    asm.append(f"        .word   {ADDR_T3}, {ADDR_T3}, .+4")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_T3}, .+4")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R20}, .+4")
    
    asm.append(f".Lsra{shift_amount}_done:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_ZERO}, .Lsra_done")


def emit_srl():
    asm = []
    asm.append(f"")
    asm.append(f"        .globl  __subleq_srl")
    asm.append(f"        .type   __subleq_srl,@function")
    asm.append(f"")
    asm.append(f"__subleq_srl:")
    
    # R21 = value to shift (used directly, no copy to T1)
    # R22 = shift amount (used directly, no copy to T0)
    
    asm.append(f".Lsrl_dispatch:")
    # Check R22 <= 0 (shift amount 0 or negative → copy input)
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lsrl_copy_input")
    # Check R22 >= 32: T3 = 32 - R22; if ≤ 0 → zero (shift ≥ 32)
    asm.append(f"        .word   {ADDR_T3}, {ADDR_T3}, .+4")
    asm.append(f"        .word   .Lsrl_n32, {ADDR_T3}, .+4")       # T3 = 32
    asm.append(f"        .word   {ADDR_R22}, {ADDR_T3}, .Lsrl_zero") # T3 -= R22; if ≤ 0, R22 ≥ 32
    # R22 is in [1, 31]. Binary tree dispatch (O(log n) instead of O(n)).
    emit_binary_dispatch(asm, 1, 31, ".Lsrl", ADDR_R22)
    
    asm.append(f".Lsrl_zero:")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .Lsrl_done")  # R20=0, always jumps
    
    for shift in range(1, 32):
        emit_srl_shift_path(asm, shift)
    
    asm.append(f".Lsrl_copy_input:")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .Lsrl_done")
    
    asm.append(f".Lsrl_done:")
    asm.extend(emit_return_sequence("srl"))
    
    # Constants for SRL
    asm.append(f"")
    asm.append(f"")
    asm.append(f"")
    
    for i in range(32):
        val = 1 << i
        asm.append(f".Lsrl_c{val}: .word {val}")
        asm.append(f".Lsrl_n{val}: .word {-val}")
        
    # .Lsrl_c2147483648 is generated by loop (i=31).

    # So we just remove the manual definition line.


    asm.append(f".size __subleq_srl, . - __subleq_srl")
    return asm


def emit_sra():
    asm = []
    asm.append(f"")
    asm.append(f"        .globl  __subleq_sra")
    asm.append(f"        .type   __subleq_sra,@function")
    asm.append(f"")
    asm.append(f"__subleq_sra:")
    
    # R21 = value to shift (used directly, no copy to T1)
    # R22 = shift amount (used directly, no copy to T0)
    
    asm.append(f".Lsra_dispatch:")
    # Check R22 <= 0 (shift amount 0 or negative → copy input)
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lsra_copy_input")
    # Check R22 >= 32: T3 = 32 - R22; if ≤ 0 → allbits (shift ≥ 32)
    asm.append(f"        .word   {ADDR_T3}, {ADDR_T3}, .+4")
    asm.append(f"        .word   .Lsra_n32, {ADDR_T3}, .+4")       # T3 = 32
    asm.append(f"        .word   {ADDR_R22}, {ADDR_T3}, .Lsra_allbits") # T3 -= R22; if ≤ 0, R22 ≥ 32
    # R22 is in [1, 31]. Binary tree dispatch.
    emit_binary_dispatch(asm, 1, 31, ".Lsra", ADDR_R22)
    
    asm.append(f".Lsra_allbits:")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_T3}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T3}, .+4")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T3}, .Lsra_ab_maybe_neg")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsra_zero")
    
    asm.append(f".Lsra_ab_maybe_neg:")
    # OPTIMIZED: Combined restore+branch (operates on R21 directly)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .Lsra_ab_neg_restore")  # R21 += 1; if <= 0 → negative
    # R21 was 0 (now 1): restore and skip to zero (always branches)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Lsra_zero")  # restore+branch
    
    asm.append(f".Lsra_ab_neg_restore:")
    # R21 was < 0: restore R21 (always branches via .+4)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .+4")  # restore+branch
    # R21 was negative: SRA by ≥32 → result is -1
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsra_minus1")
    
    asm.append(f".Lsra_zero:")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .Lsra_done")  # R20=0, always jumps
    
    asm.append(f".Lsra_minus1:")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R20}, .Lsra_done")  # R20=-1, always jumps
    
    for shift in range(1, 32):
        emit_sra_shift_path(asm, shift)
        
    asm.append(f".Lsra_copy_input:")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .Lsra_done")
    
    asm.append(f".Lsra_done:")
    asm.extend(emit_return_sequence("sra"))
    
    # Constants for SRA
    asm.append(f"")
    asm.append(f"")
    asm.append(f"")
    
    for i in range(32):
        val = 1 << i
        asm.append(f".Lsra_c{val}: .word {val}")
        asm.append(f".Lsra_n{val}: .word {-val}")
    
    # .Lsra_c2147483648 is generated by loop (i=31).

    
    asm.append(f".size __subleq_sra, . - __subleq_sra")
    return asm

if __name__ == "__main__":
    print("# ===== Unrolled SRL =====")
    for line in emit_srl():
        print(line)
    print()
    print("# ===== Unrolled SRA =====")
    for line in emit_sra():
        print(line)
    print()
    # Shared dispatch constants (used by both SRL and SRA)
    asm = []
    emit_dispatch_constants(asm, ".Lshd")
    for line in asm:
        print(line)
