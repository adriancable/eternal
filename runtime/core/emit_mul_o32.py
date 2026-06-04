#!/usr/bin/env python3
"""
Optimized O(32) single-phase Zephyr multiplication algorithm for Subleq.

Algorithm (reverse accumulation):
1. Handle signs: negate negative operands, track if result should be negative
2. Single phase (bit 30 down to 0):
   - Double the result (shifts all previous contributions up by one bit)
   - If R3 >= 2^i: R3 -= 2^i, result += R4
3. Handle bit 31 specially (for INT_MIN case)
4. Negate result if signs differed

OPTIMIZATION (Biased Lattice):
- Multiplier (T1) is biased by +1 to enable Non-Restoring logic.
- Loop Bits 30 down to 0:
  - Double Accumulator (T0 = T0 + T0).
  - Check Multiplier Bit k (Lattice Transition):
    - State Pos: Sub 2^k. If > 0, Bit is 1 (Stay Pos). If <= 0, Bit is 0 (Go Neg).
    - State Neg: Add 2^k. If > 0, Bit is 1 (Go Pos). If <= 0, Bit is 0 (Stay Neg).
  - If Bit 1 (implied by transition): Add Multiplicand (R22) to Accumulator.
- Eliminates "Restore" step, fusing check and transition.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen_runtime import (emit_return_sequence, ADDR_Z, ADDR_SP, ADDR_RA, ADDR_ZERO, ADDR_R20, ADDR_R21, ADDR_R22, ADDR_T0, ADDR_T1, ADDR_T2, ADDR_T3, ADDR_T4, ADDR_T5, ADDR_T6, INDIRECT_FLAG, const_from_pool, ADDR_ONE, ADDR_MINUS_ONE)


def emit_lattice_mul_core(asm):
    """Emit the lattice core for Multiplication with early exit checkpoints.
     bits 30 down to 0.
     R20 = Accumulator (Result, directly in return register).
     T1 = Multiplier (Biased).
     R22 = Multiplicand (Positive).
     
     Early exit checkpoints at bits 24, 16, 8:
     After processing each checkpoint bit in Pos state, if T1 == 1 (biased zero),
     all remaining bits are 0 and we can skip to a fast-finish that just doubles R20.
    """
    current_states = {'Pos'}
    checkpoint_bits = {24, 16, 8}
    
    for bit in range(30, -1, -1):
        power = 1 << bit
        
        lbl_base = f".Lmul_lat_b{bit}"
        
        # Next state labels
        if bit == 0:
            next_base_pos = ".Lmul_lat_done"
            next_base_neg = ".Lmul_lat_done"
        else:
            next_base_pos = f".Lmul_lat_b{bit-1}_Pos"
            next_base_neg = f".Lmul_lat_b{bit-1}_Neg"
            
        next_states = set()
        
        # Helper to emit the "Double R20" logic (3 inst)
        # R20 = R20 + R20
        # subleq Z, Z; subleq R20, Z; subleq Z, R20
        def emit_double_t0():
             asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
             asm.append(f"        .word   {ADDR_R20}, {ADDR_Z}, .+4")
             asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .+4")

        # --- Pos State ---
        if 'Pos' in current_states:
            asm.append(f"{lbl_base}_Pos:")
            emit_double_t0()
            
            # Sub 2^bit from T1.
            # If <= 0 (Jump) -> Neg state (Bit 0).
            # If > 0 (Fallthrough) -> Pos state (Bit 1).
            
            asm.append(f"        .word   {const_from_pool(power)}, {ADDR_T1}, {next_base_neg}")
            if bit > 0: next_states.add('Neg')
            
            # --- Pos -> Pos (Bit 1) ---
            # Bit is 1. R20 += R22.
            # Use precomputed T5 = -R22.
            # R20 -= T5  => R20 -= -R22 => R20 += R22
            
            asm.append(f"        .word   {ADDR_T5}, {ADDR_R20}, .+4")
            
            # Early exit checkpoint (Pos state only)
            # After subtracting 2^bit, if T1 == 1 (biased zero), all remaining bits are 0.
            # OPTIMIZED: Destructive test+restore (2 ops instead of 5).
            # T1 is always >= 1 in Pos state (biased). If T1=1, T1-1=0 <= 0, exit.
            # If T1>1, T1-1 >= 1 > 0, no branch; restore T1 += 1.
            if bit in checkpoint_bits:
                asm.append(f"        .word   {ADDR_ONE}, {ADDR_T1}, .Lmul_fast_{bit}")  # T1 -= 1; if <= 0 → early exit
                asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .+4")  # T1 += 1 (restore; T1 >= 2 > 0, always falls through)
            
            # Jump to Next Pos: inline double_T0 + test to replace Z,Z with useful work
            if 'Neg' in current_states and bit > 0:
                # INLINE next Pos's double_T0: Z,Z,.+4 replaces dead Z,Z,next_Pos
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")   # double_T0 step 1 (useful Z,Z)
                asm.append(f"        .word   {ADDR_R20}, {ADDR_Z}, .+4") # double_T0 step 2
                asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .+4") # double_T0 step 3
                # Inline T1 test for next bit
                next_bit = bit - 1
                if next_bit == 0:
                    inl_neg = ".Lmul_lat_done"
                else:
                    inl_neg = f".Lmul_lat_b{next_bit-1}_Neg"
                asm.append(f"        .word   {const_from_pool(1 << next_bit)}, {ADDR_T1}, {inl_neg}")
                # Inline accumulate (bit=1)
                asm.append(f"        .word   {ADDR_T5}, {ADDR_R20}, .+4")
                # Skip over next Neg (inline's own skip)
                if next_bit == 0:
                    inl_pos = ".Lmul_lat_done"
                else:
                    inl_pos = f".Lmul_lat_b{next_bit-1}_Pos"
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {inl_pos}")
            elif 'Neg' in current_states:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_base_pos}")
            # else: fall through directly to next Pos
            if bit > 0: next_states.add('Pos')
            
        # --- Neg State ---
        if 'Neg' in current_states:
            asm.append(f"{lbl_base}_Neg:")
            emit_double_t0()
            
            # Add 2^bit (Sub -2^bit).
            # If <= 0 (Jump) -> Neg state (Bit 0).
            # If > 0 (Fallthrough) -> Pos state (Bit 1).
            
            asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_T1}, {next_base_neg}")
            if bit > 0: next_states.add('Neg')
            
            # --- Neg -> Pos (Bit 1) ---
            # Bit 1. R20 += R22. Use T5.
            
            asm.append(f"        .word   {ADDR_T5}, {ADDR_R20}, .+4")
            
            # Fallthrough optimization: if Neg is the last state for this bit
            # and the next emitted label is next_base_pos, we can fall through
            # instead of emitting Z,Z,<next_base_pos>.
            # For bit > 0: next Pos is emitted next.
            # For bit == 0: .Lmul_lat_done is emitted next (also a fallthrough).
            if 'Pos' in next_states or bit == 0:
                # fall through (no jump needed)
                pass
            else:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_base_pos}")
            if bit > 0: next_states.add('Pos')
            
        current_states = next_states
    
    asm.append(".Lmul_lat_done:")
    # Lattice done. R20 has result.
    # Note: fast-finish routines are emitted separately in emit_mul_o32()
    # to avoid fallthrough from normal execution path.


def emit_mul_o32():
    """Generate __subleq_mul: R3 = R3 * R4 (signed multiplication) - O(32) single-phase.
    """
    asm = []
    asm.append("")
    asm.append("        .globl  __subleq_mul")
    asm.append("        .type   __subleq_mul,@function")
    asm.append("")
    asm.append("# __subleq_mul: R3 = R3 * R4 (signed multiplication) - Biased Lattice Optimization")
    asm.append("__subleq_mul:")
    
    # === ZERO FAST PATH ===
    # 35.85% of calls have R21=0, 24.19% have R22=0.
    # If either operand is zero, result is zero. Return immediately.
    # Cost: 1 op each on non-zero hot path (just the branch test).
    # Check R21: subleq(ZERO, R21, r21_le0) — branches if R21 <= 0
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Lmul_r21_zchk")
    # R21 > 0: check R22
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lmul_r22_zchk")
    # Both > 0: FALL THROUGH to begin (hot-path layout opt: removed Z,Z,begin jump)
    
    asm.append(".Lmul_begin:")
    # Initialize sign flag T3 = 0
    asm.append(f"        .word   {ADDR_T3}, {ADDR_T3}, .+4")  # T3 = 0
    
    # === Check if R3 is negative ===
    # Finding G: Test R21 directly — no need to copy to T1 first (T1 is overwritten later)
    asm.append(".Lmul_chk_r3_sign:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Lmul_r3_le0")  # R21 ≤ 0 → check
    # R21 > 0: FALL THROUGH to chk_r4_sign (hot-path layout opt: removed Z,Z,chk_r4_sign jump)
    
    # === Check if R4 is negative ===
    # Finding F: Test R22 directly — no need to copy to T1 first
    asm.append(".Lmul_chk_r4_sign:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lmul_r4_le0")  # R22 ≤ 0 → check
    # R22 > 0: FALL THROUGH to main_init (hot-path layout opt: removed Z,Z,main_init jump)
    

    
    # === Main init ===
    asm.append(".Lmul_main_init:")
    # Both R21 and R22 are non-negative at this point.
    # === Operand Swap: put smaller value in R21 (→ T1 lattice) ===
    # This maximizes early-exit checkpoint hits since a smaller multiplier
    # reaches biased-zero sooner.
    # Compare: T2 = R21 - R22. If T2 <= 0 → R21 <= R22 → no swap needed.
    asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")       # T2 = 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")         # Z = 0
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")       # Z = -R21
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T2}, .+4")        # T2 = R21
    asm.append(f"        .word   {ADDR_R22}, {ADDR_T2}, .Lmul_swap_done")  # T2 -= R22; T2 = R21 - R22; if <= 0 → no swap
    # T2 > 0 → R21 > R22 → need swap, fall through to do_swap
    
    asm.append(".Lmul_do_swap:")
    # Residue-based swap: T2 = R21 - R22 (from comparison, T2 > 0 here)
    # R21 -= T2 → R21 - (R21 - R22) = R22  ✓
    # R22 += T2 → R22 + (R21 - R22) = R21  ✓ (via negate-and-subtract through Z)
    asm.append(f"        .word   {ADDR_T2}, {ADDR_R21}, .+4")       # R21 -= T2 → R21 = R22
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")          # Z = 0
    asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")         # Z = -T2
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R22}, .+4")        # R22 -= (-T2) = R22 + T2 = R21
    
    asm.append(".Lmul_swap_done:")
    # T1 = R21 (smaller operand, or unchanged if already smaller)
    # R20 = 0 (result accumulator — directly in return register)
    asm.append(f"        .word   {ADDR_T1}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T1}, .+4")
    
    # Precompute T5 = -R22 (Negative Multiplicand)
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4") # T5 = 0
    asm.append(f"        .word   {ADDR_R22}, {ADDR_T5}, .+4") # T5 = -R22
    
    # Clear R20
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .Lmul_chk_8bit")
    
    # === Magnitude Fast Paths ===
    # Only R21 (the lattice multiplier = T1) determines how many bits to process.
    # R22 (multiplicand) can be any magnitude — it's just added to the accumulator.
    # With operand swap, R21 <= R22, so checking R21 alone is sufficient.
    asm.append(".Lmul_chk_8bit:")
    # Check R21 == 0 fast exit (result is 0)
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Lmul_bit31")
    # Check R21 < 256: T2 = 256 - R21; if T2 <= 0, R21 >= 256 → check 16-bit
    asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")       # T2 = 0
    asm.append(f"        .word   {const_from_pool(-256)}, {ADDR_T2}, .+4")      # T2 = 256
    asm.append(f"        .word   {ADDR_R21}, {ADDR_T2}, .Lmul_chk_16bit")  # T2 -= R21; if <= 0, R21 >= 256
    # R21 < 256: bias T1 and jump to bit 7
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .+4")  # Bias T1 += 1
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lmul_lat_b7_Pos")
    
    # === 16-bit Fast Path (cascading residual reuse, 1 op was 3) ===
    asm.append(".Lmul_chk_16bit:")
    # T2 = 256 - R21 (from 8-bit check, T2 <= 0 since R21 >= 256)
    # R21 < 65536 iff T2 + (65536 - 256) = T2 + 65280 > 0
    asm.append(f"        .word   {const_from_pool(-65280)}, {ADDR_T2}, .Lmul_chk_24bit")  # T2 += 65280; if <= 0 → R21 >= 65536
    # R21 < 65536: bias T1 and jump to bit 15
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .+4")  # Bias T1 += 1
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lmul_lat_b15_Pos")
    
    # === 24-bit Fast Path (cascading residual reuse, 1 op was 3) ===
    asm.append(".Lmul_chk_24bit:")
    # T2 = 65536 - R21 (from 16-bit cascade, T2 <= 0 since R21 >= 65536)
    # R21 < 16777216 iff T2 + (16777216 - 65536) = T2 + 16711680 > 0
    asm.append(f"        .word   {const_from_pool(-16711680)}, {ADDR_T2}, .Lmul_bit31")  # T2 += 16711680; if <= 0 → R21 >= 16M
    # R21 < 16777216: bias T1 and jump to bit 23
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lmul_lat_b23_Pos")
    
    
    # === Bit 31 + Lattice Setup ===
    asm.append(".Lmul_bit31:")
    # OPTIMIZED: 1-op non-destructive test (was 7 ops copy-and-test).
    # subleq(ZERO, T1, le0) does T1 -= 0 = T1 (unchanged), branches if T1 <= 0.
    # Since zero fast path already handled R21=0, T1 <= 0 uniquely means T1 = INT_MIN.
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T1}, .Lmul_b31_le0")
    # T1 > 0: no bit 31. Fall through directly to bias.
    
    asm.append(".Lmul_lat_setup:")
    # Bias T1 += 1
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .+4")
    
    # === Lattice Bits 30-0 ===
    emit_lattice_mul_core(asm)
    
    # === Final Negate Check ===
    # T3 is sign parity: 0 = positive, 1 = negate, 2 = positive
    # Test directly (T3 is dead after this)
    asm.append(".Lmul_chk_negate:")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T3}, .+4")  # T3 -= 1
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T3}, .Lmul_maybe_neg")  # if T3 <= 0 (was 0 or 1)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lmul_exit")  # T3 was 2: no negate
    
    asm.append(".Lmul_maybe_neg:")
    # T3 = -1 (was 0, no negate) or T3 = 0 (was 1, negate)
    # MINUS_ONE restores T3: -1+1=0 ≤ 0 → exit (no negate); 0+1=1 > 0 → fall through (negate)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T3}, .Lmul_exit")
    
    asm.append(".Lmul_negate:")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_T1}, .+4") # T1 = -R20
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .+4") # R20 = -R20 (negated)
    
    # R20 already has the final result — fall through to exit
    
    asm.append(".Lmul_exit:")
    asm.extend(emit_return_sequence("mul"))
    
    # === COLD PATHS (relocated from hot path for fallthrough optimization) ===
    
    # --- Zero check cold paths ---
    asm.append(".Lmul_r21_zchk:")
    # R21 <= 0: disambiguate R21 = 0 from R21 < 0
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .Lmul_r21_neg_restore")  # R21 += 1; if <= 0 → negative
    # R21 was 0 (now 1): restore and return 0
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Lmul_ret_zero")  # restore+branch
    
    asm.append(".Lmul_r21_neg_restore:")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .+4")  # restore+branch
    # R21 < 0: not zero, check R22 then proceed
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lmul_r22_zchk")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lmul_begin")
    
    asm.append(".Lmul_r22_zchk:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .Lmul_r22_neg_restore")  # R22 += 1; if <= 0 → negative
    # R22 was 0 (now 1): restore and return 0
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .Lmul_ret_zero")  # restore+branch
    
    asm.append(".Lmul_r22_neg_restore:")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .+4")  # restore+branch
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lmul_begin")
    
    asm.append(".Lmul_ret_zero:")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lmul_exit")
    
    # --- R3 sign handling cold path ---
    asm.append(".Lmul_r3_le0:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .Lmul_r3_neg_restore")  # R21 += 1; if <= 0 → negative
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Lmul_chk_r4_sign")  # R21 was 0: restore+branch
    
    asm.append(".Lmul_r3_neg_restore:")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .+4")  # restore+branch
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T3}, .+4")  # T3 += 1 (sign flag)
    asm.append(f"        .word   {ADDR_T1}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_T1}, .+4")   # T1 = -R21 = abs(R21)
    asm.append(f"        .word   {ADDR_R21}, {ADDR_R21}, .+4")  # R21 = 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")     # Z = -T1
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R21}, .+4")    # R21 = abs(R21)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lmul_chk_r4_sign")  # unconditional jump
    
    # --- R4 sign handling cold path ---
    asm.append(".Lmul_r4_le0:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .Lmul_r4_neg_restore")  # R22 += 1; if <= 0 → negative
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .Lmul_main_init")  # R22 was 0: restore+branch
    
    asm.append(".Lmul_r4_neg_restore:")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .+4")  # restore+branch
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T3}, .+4")  # T3 += 1 (sign flag)
    asm.append(f"        .word   {ADDR_T1}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_T1}, .+4")   # T1 = -R22 = abs(R22)
    asm.append(f"        .word   {ADDR_R22}, {ADDR_R22}, .+4")  # R22 = 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")     # Z = -T1
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R22}, .+4")    # R22 = abs(R22)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lmul_main_init")  # unconditional jump
    
    # --- Bit 31 cold path (T1 = INT_MIN only, since zero fast path catches T1=0) ---
    asm.append(".Lmul_b31_le0:")
    # T1 = INT_MIN guaranteed (zero case already returned)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .+4")  # R20 += R22
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_T1}, .Lmul_lat_setup")  # T1 -= INT_MIN → T1 = 0, always branches
    
    # Fast-finish routines for early exit checkpoints.
    # These are only reached via explicit jumps from checkpoints, not by fallthrough.
    # They double R20 the remaining number of times and then jump to .Lmul_chk_negate.
    for remaining in [24, 16, 8]:
        asm.append(f".Lmul_fast_{remaining}:")
        for _ in range(remaining):
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
            asm.append(f"        .word   {ADDR_R20}, {ADDR_Z}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lmul_chk_negate")
    
    asm.append(".size __subleq_mul, . - __subleq_mul")
    return asm

if __name__ == "__main__":
    final_asm = emit_mul_o32()
    for line in final_asm:
        print(line)
