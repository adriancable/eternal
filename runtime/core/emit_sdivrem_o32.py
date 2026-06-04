#!/usr/bin/env python3
"""
Optimized O(32) signed division with remainder for Subleq.

OPTIMIZATIONS:
1. Small operand fast paths (8-bit, 16-bit)
2. DIV-A: Z-clean doubling (2 insn instead of 3)
3. DIV-B: Restoring subtraction for bit extraction (+1 bias on T3)
4. DIV-C: Simplified comparison — after abs, both R22 and T1 are positive
5. DIV-H: Z-clean init copy

Algorithm:
1. Determine signs of dividend and divisor
2. Take absolute values of both operands
3. Perform inline O(32) binary long division
4. Apply signs to results:
   - Quotient sign: XOR of operand signs
   - Remainder sign: Same as dividend sign

Register interface:
- Input: R21 = dividend, R22 = divisor
- Output: R21 = quotient, R22 = remainder (both signed)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_runtime import emit_return_sequence, ADDR_Z, ADDR_SP, ADDR_RA, ADDR_ZERO, ADDR_R20, ADDR_R21, ADDR_R22, ADDR_T0, ADDR_T1, ADDR_T2, ADDR_T3, ADDR_T4, ADDR_T5, ADDR_T6, const_from_pool, ADDR_ONE, ADDR_MINUS_ONE


def emit_sdivrem_o32():
    """Generate __subleq_sdivrem: R21 = R21 / R22, R22 = R21 % R22 (signed).
    
    Register usage:
    - R21 = dividend (input), then quotient (output)
    - R22 = divisor (input), then remainder (output)
    - T0 (40) = quotient accumulator
    - T1 (41) = remainder accumulator
    - T2 (42) = scratch
    - T3 (43) = dividend copy for bit extraction (BIASED +1)
    - T4 (44) = scratch / R22-sign flag for INT_MIN edge case
    - T5 (45) = quotient sign flag (XOR of operand signs)
    - T6 (46) = dividend sign flag (for remainder sign)
    """
    asm = []
    asm.append("")
    asm.append("        .globl  __subleq_sdivrem")
    asm.append("        .type   __subleq_sdivrem,@function")
    asm.append("")
    asm.append("# __subleq_sdivrem: R21/R22 = quotient/remainder (signed)")
    asm.append("# OPTIMIZED: DIV-A/B/C/H applied")
    asm.append("__subleq_sdivrem:")
    
    # === Initialize sign flags ===
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .Lsdivrem_chk_r3")
    
    # === Check if R21 (dividend) is negative ===
    asm.append(".Lsdivrem_chk_r3:")
    # Non-destructive sign test: ZERO,R21 does R21 -= 0 = R21 (unchanged)
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Lsdivrem_r3_le0")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_chk_r4")
    
    asm.append(".Lsdivrem_r3_le0:")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_T1}, .+4")   # T1 = -R21
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T1}, .Lsdivrem_r3_ambig")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_r3_neg")
    
    asm.append(".Lsdivrem_r3_ambig:")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T1}, .Lsdivrem_chk_r4")  # R21 = 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_r3_neg")       # R21 = INT_MIN
    
    asm.append(".Lsdivrem_r3_neg:")
    # R21 < 0: set both sign flags, negate R21
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T5}, .+4")  # T5 = 1
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T6}, .Lsdivrem_neg_r3")
    asm.append(".Lsdivrem_neg_r3:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R21}, .Lsdivrem_chk_r4")
    
    # === Check if R22 (divisor) is negative ===
    asm.append(".Lsdivrem_chk_r4:")
    # Non-destructive sign test: ZERO,R22 does R22 -= 0 = R22 (unchanged)
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lsdivrem_r4_le0")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_do_div")
    
    asm.append(".Lsdivrem_r4_le0:")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T1}, .Lsdivrem_r4_ambig")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .Lsdivrem_tog1")
    
    asm.append(".Lsdivrem_r4_ambig:")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T1}, .Lsdivrem_do_div")  # R22 = 0
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .Lsdivrem_tog1")       # R22 = INT_MIN
    
    # Toggle quotient sign, negate R22
    asm.append(".Lsdivrem_tog1:")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T5}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T5}, .+4")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T5}, .Lsdivrem_neg_r4")
    asm.append(".Lsdivrem_neg_r4:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R22}, .Lsdivrem_do_div")
    
    # === O(32) unsigned division ===
    asm.append(".Lsdivrem_do_div:")
    # Initialize: T0 (quotient) = 0, T1 (remainder) = 0
    # DIV-H: Z-clean copy (Z may or may not be clean here, be safe)
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_T3}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T3}, .+4")      # T3 = R21
    # DIV-B: Bias T3 by +1
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T3}, .+4")  # T3 = R21 + 1
    
    # DIV-C: Pre-check R22 = INT_MIN edge case
    # After abs-value, R22 = INT_MIN only if original R22 was INT_MIN.
    # In that case, R22 <= 0. Normal case: R22 > 0.
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lsdivrem_r22_intmin")
    # R22 > 0: fall through to precompute + small checks.
    
    # === DIV-F: Precompute fused comparison constants ===
    # T4 = R22 - 1 (for restoring comparison test)
    # T2 = -(R22-1) = 1-R22 (for restoring comparison restore)
    # After abs, R22 > 0, so R22-1 >= 0. T1-(R22-1) > 0 ↔ T1 >= R22.
    asm.append(f"        .word   {ADDR_T4}, {ADDR_T4}, .+4")         # T4 = 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")           # Z = 0 (was dirty from R21→T3 copy)
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")         # Z = -R22
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T4}, .+4")          # T4 = R22
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T4}, .+4")     # T4 = R22 - 1
    asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")         # T2 = 0
    asm.append(f"        .word   {ADDR_T4}, {ADDR_T2}, .+4")         # T2 = -(R22-1) = 1-R22
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_chk_small")
    
    asm.append(".Lsdivrem_r22_intmin:")
    # R22 = INT_MIN. R21 is abs(dividend), so R21 >= 0 unsigned.
    # R21 > 0 signed → R21 < INT_MIN unsigned → quot=0, rem=R21.
    # R21 = 0 → quot=0, rem=0.
    # R21 = INT_MIN (abs overflow) → quot=1, rem=0.
    # Check R21 sign: R21 > 0 → quot=0/rem=R21. R21 <= 0 → disambiguate.
    asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T2}, .+4")      # T2 = R21
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T2}, .Lsdivrem_intmin_r21_le0")
    # R21 > 0: Quotient = 0, Remainder = R21. Copy R21 → T1, then jump.
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T1}, .+4")           # T1 = R21 (may be > 0)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_div_done")
    
    asm.append(".Lsdivrem_intmin_r21_le0:")
    # R21 <= 0: combined restore+branch. R21+1<=0 -> R21 was INT_MIN
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .Lsdivrem_intmin_restore")
    # R21 was 0 (now 1): restore to 0 and branch to zero path
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Lsdivrem_intmin_r21_zero")
    asm.append(".Lsdivrem_intmin_restore:")
    # R21 was INT_MIN: restore and fall through to intmin_eq
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_intmin_eq")
    
    asm.append(".Lsdivrem_intmin_r21_zero:")
    # R21 = 0. Quotient = 0, Remainder = 0 (both already 0).
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_div_done")
    asm.append(".Lsdivrem_intmin_eq:")
    # R21 = INT_MIN = R22. Quotient = 1, Remainder = 0.
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T0}, .+4")  # T0 = 1 (result > 0, no branch)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_div_done")
    
    # === SMALL OPERAND FAST PATH ===
    # NOTE: T2 and T4 hold precomputed fused-comparison constants.
    # chk_small uses scratch that doesn't conflict: reads T3, writes to Z.
    asm.append(".Lsdivrem_chk_small:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T3}, .Lsdivrem_div_chk_32")
    # Check T3 (biased) < 257 → dividend < 256 → enter at bit 7
    # Use Z as scratch (T2/T4 are reserved for fused comparison)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {const_from_pool(-257)}, {ADDR_Z}, .+4")        # Z = 257
    asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .Lsdivrem_chk_16bit")  # Z = 257-T3; if <= 0, T3 >= 257
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_bit7")
    
    asm.append(".Lsdivrem_chk_16bit:")
    # Cascade: Z += 65280 → Z = 65537-T3. (was 3 ops, now 1)
    asm.append(f"        .word   {const_from_pool(-65280)}, {ADDR_Z}, .Lsdivrem_chk_24bit")  # if <= 0, T3 >= 65537
    # Dividend 16-bit: check divisor >= 256 for accum skip
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {const_from_pool(-256)}, {ADDR_Z}, .+4")        # Z = 256
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .Lsdivrem_acc16_b15")     # R22 >= 256 → accum
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_bit15")           # R22 < 256 → full
    
    asm.append(".Lsdivrem_chk_24bit:")
    # Cascade: Z += 16711680 → Z = 16777217-T3. (was 3 ops, now 1)
    asm.append(f"        .word   {const_from_pool(-16711680)}, {ADDR_Z}, .Lsdivrem_div_chk_32")
    # Dividend 24-bit: check divisor >= 256
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {const_from_pool(-256)}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .Lsdivrem_acc24_b23")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_bit23")
    
    # Dividend 32-bit: check divisor >= 256
    asm.append(".Lsdivrem_div_chk_32:")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {const_from_pool(-256)}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .Lsdivrem_acc32_b31")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_bit31")
    
    # === ACCUMULATE-ONLY CHAINS (divisor >= 256) ===
    # When divisor >= 256, after extracting 8 bits the max remainder = 255 < 256 <= divisor,
    # so all 8 comparisons are guaranteed to produce quotient bit = 0.
    # Each chain: doubling + bit extraction only, no comparison. Saves ~4 ops/bit.
    #
    # Z state contract: Z is dirty on entry (from R22,Z,target). Each chain cleans Z first.
    # T2, T4 (fused comparison constants): NOT touched by accum chains.
    # T3 (biased dividend): modified by bit extraction (restoring subtraction).
    # T1 (remainder): accumulated by doubling + bit extraction.
    
    # --- Chain 16-bit: accum bits 15→8 (8 bits), exit → full_bit7 ---
    for i in range(15, 7, -1):
        threshold = 1 << i
        next_lbl = f".Lsdivrem_acc16_b{i-1}" if i > 8 else ".Lsdivrem_bit7"
        asm.append(f".Lsdivrem_acc16_b{i}:")
        # Z dirty: from dispatch (first bit) or from doubling (subsequent bits)
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")      # clean Z
        asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")     # Z = -T1
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T1}, .+4")     # T1 *= 2 (Z stays -T1, NOT 0)
        asm.append(f"        .word   {const_from_pool(threshold)}, {ADDR_T3}, .Lsdivrem_acc16_r{i}")
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .+4")  # bit set: T1 += 1
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl}")    # Z=0, jump
        asm.append(f".Lsdivrem_acc16_r{i}:")
        asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_T3}, .+4")  # restore
        if i == 8:  # last bit: explicit jump to exit (don't fall into next chain)
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl}")
    
    # --- Chain 24-bit: accum bits 23→16 (8 bits), exit → full_bit15 ---
    for i in range(23, 15, -1):
        threshold = 1 << i
        next_lbl = f".Lsdivrem_acc24_b{i-1}" if i > 16 else ".Lsdivrem_bit15"
        asm.append(f".Lsdivrem_acc24_b{i}:")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T1}, .+4")
        asm.append(f"        .word   {const_from_pool(threshold)}, {ADDR_T3}, .Lsdivrem_acc24_r{i}")
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl}")
        asm.append(f".Lsdivrem_acc24_r{i}:")
        asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_T3}, .+4")
        if i == 16:  # last bit: explicit jump to exit
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl}")
    
    # --- Chain 32-bit: accum bits 31→24 (8 bits), exit → full_bit23 ---
    # Bit 31 needs special sign-check extraction (threshold = 2^31 can't be used directly)
    asm.append(f".Lsdivrem_acc32_b31:")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")          # clean Z from dispatch
    asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T1}, .+4")         # T1 *= 2 (= 0), Z = 0
    # Bit 31 extraction: sign-check on T3_biased
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")         # Z = -T3_biased
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_Z}, .Lsdivrem_a31_le0")
    # Z > 0: T3_biased < 0 → bit 31 IS set
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_a31_set")
    asm.append(f".Lsdivrem_a31_le0:")
    # Z <= 0: T3_biased >= 0. Z = 0 → T3_biased = 0 → bit set. Z < 0 → not set.
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_Z}, .Lsdivrem_a31_not")  # Z+=1; <=0 → was <0 → not set
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_a31_set")          # Z was 0 → bit set
    asm.append(f".Lsdivrem_a31_not:")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_acc32_b30")        # Z clean, next bit
    asm.append(f".Lsdivrem_a31_set:")
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_T3}, .+4")  # clear bit 31
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .+4")               # T1 += 1
    # fall through to bit 30 (Z clean from Z,Z,_set jump)
    
    # Bits 30→24: standard restoring subtraction, no comparison
    for i in range(30, 23, -1):
        threshold = 1 << i
        next_lbl = f".Lsdivrem_acc32_b{i-1}" if i > 24 else ".Lsdivrem_bit23"
        asm.append(f".Lsdivrem_acc32_b{i}:")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T1}, .+4")
        asm.append(f"        .word   {const_from_pool(threshold)}, {ADDR_T3}, .Lsdivrem_acc32_r{i}")
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl}")
        asm.append(f".Lsdivrem_acc32_r{i}:")
        asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_T3}, .+4")
        if i == 24:  # last bit: explicit jump to exit
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl}")
    
    # === MAIN DIVISION LOOP (DIV-F: Fused Restoring Comparison) ===
    # T4 = R22-1 (precomputed, read-only during loop)
    # T2 = -(R22-1) = 1-R22 (precomputed, read-only during loop)
    # Per-bit comparison: subleq(T4, T1, no_sub) tests T1 >= R22 in 1 op.
    # If T1-(R22-1) > 0 → T1 >= R22 → subtract (complete with -1).
    # If T1-(R22-1) <= 0 → T1 < R22 → restore with subleq(T2, T1).
    for i in range(31, -1, -1):
        threshold = 1 << i
        next_bit_label = f".Lsdivrem_bit{i-1}" if i > 0 else ".Lsdivrem_div_done"
        
        asm.append(f".Lsdivrem_bit{i}:")
        
        # Step 1: DIV-A: Double remainder (2 insn, Z-clean entry)
            # Z is clean: all paths arrive via Z,Z,.Lsdivrem_bit31 from div_chk_32
        asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T1}, .+4")
        
        # Step 2: Extract bit[i] from T3
        if i == 31:
            # Bit 31: sign-check (can't use restoring subtraction)
            # NOTE: Must not clobber T2 or T4 (hold fused-cmp constants).
            # Use Z as scratch instead of T2.
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
            asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")      # Z = -T3_biased
            asm.append(f"        .word   {ADDR_ZERO}, {ADDR_Z}, .Lsdivrem_{i}_le0")
            # Z = -T3_biased: if Z <= 0, T3_biased >= 0 (need further check)
            # Z > 0: T3_biased < 0, meaning original < -1, so bit 31 IS set
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_{i}_bit_set")
            
            asm.append(f".Lsdivrem_{i}_le0:")
            # Z = -T3_biased <= 0, so T3_biased >= 0, original = T3_biased-1 >= -1.
            # Need to disambiguate: original >= 0 (bit 31 not set) vs original = -1 (0xFFFFFFFF, bit 31 set)
            # original = T3_biased - 1. If T3_biased = 0, original = -1 → bit 31 set.
            # If T3_biased >= 1, original >= 0 → bit 31 not set.
            # Test: subleq(neg1, Z) where Z = -T3_biased: Z += 1 = -T3_biased+1 = -(T3_biased-1)
            # If Z <= 0: T3_biased-1 >= 0 → original >= 0 → bit NOT set
            # If Z > 0: T3_biased-1 < 0 → T3_biased = 0 → original = -1 → bit IS set... no wait
            # T3_biased is always >= 1 (since original value biased by +1, and smallest value is 0 giving T3_biased=1)
            # Actually T3_biased = original + 1. If original = INT_MIN, T3_biased = INT_MIN + 1 < 0.
            # So T3_biased < 0 means original < -1 means bit 31 IS set (already handled above with Z > 0).
            # Here Z <= 0 means T3_biased >= 0. original = T3_biased - 1 >= -1.
            # original = -1: T3_biased = 0, Z = 0. Test Z: if Z = 0, need special case.
            # original >= 0: T3_biased >= 1, Z = -T3_biased <= -1 < 0.
            # So Z = 0 → original = -1 (bit 31 set). Z < 0 → original >= 0 (bit 31 not set).
            # OPTIMIZED: combined restore+branch
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_Z}, .Lsdivrem_{i}_z_neg")  # Z += 1; if <= 0 → Z was < 0 → bit NOT set
            # Z was 0 (now 1): original = -1, bit IS set. Clean Z and go to bit_set.
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_{i}_bit_set")
            
            asm.append(f".Lsdivrem_{i}_z_neg:")
            # Z was < 0 (now Z+1, still <= 0): bit NOT set. Clean Z.
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsdivrem_{i}_cmp")
            
            asm.append(f".Lsdivrem_{i}_bit_set:")
            # Bit 31 IS set. Clear bit 31 from T3_biased, add 1 to remainder.
            asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_T3}, .+4")
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .+4")
            # fall through to _cmp (Z is clean from Z,Z above)
        else:
            # DIV-B: Bits 30-0 — restoring subtraction
            asm.append(f"        .word   {const_from_pool(threshold)}, {ADDR_T3}, .Lsdivrem_{i}_restore")
            # Bit IS set: T1 += 1, fall through to _cmp
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .+4")
            # fall through to _cmp (Z dirty from doubling, but fused cmp doesn't need Z clean)
        
        # Step 3+4: DIV-F: Fused restoring comparison + conditional subtract
        # subleq(T4, T1): T1 -= (R22-1). If T1 <= 0 → T1 < R22 → no subtract.
        # If T1 > 0 → T1 >= R22 → complete subtraction with -1.
        asm.append(f".Lsdivrem_{i}_cmp:")
        asm.append(f"        .word   {ADDR_T4}, {ADDR_T1}, .Lsdivrem_{i}_no_sub")
        # T1 > 0: T1 >= R22. Complete subtraction: T1 -= 1 → T1 = old_T1 - R22.
        asm.append(f"        .word   {ADDR_ONE}, {ADDR_T1}, .+4")
        asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_T0}, .+4")  # quotient bit
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_bit_label}")     # clean Z
        
        asm.append(f".Lsdivrem_{i}_no_sub:")
        # T1 <= 0: T1 < R22. Restore: T1 -= T2 = T1 - (1-R22) = T1 + R22 - 1.
        asm.append(f"        .word   {ADDR_T2}, {ADDR_T1}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_bit_label}")     # clean Z
        
        if i < 31:
            # Bit not set: restore T3 and jump to _cmp
            asm.append(f".Lsdivrem_{i}_restore:")
            asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_T3}, .+4")
            asm.append(f"        .word   {ADDR_ZERO}, {ADDR_ZERO}, .Lsdivrem_{i}_cmp")  # unconditional jump (doesn't dirty Z)
    
    # === Division done, apply signs ===
    asm.append(".Lsdivrem_div_done:")
    
    # Copy T0 → R21 (quotient). Z state unknown.
    asm.append(f"        .word   {ADDR_R21}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R21}, .Lsdivrem_cpy_r")
    
    # Copy T1 → R22 (remainder)
    asm.append(".Lsdivrem_cpy_r:")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R22}, .Lsdivrem_chk_q_sign")
    
    # Check quotient sign (T5)
    asm.append(".Lsdivrem_chk_q_sign:")
    # Non-destructive sign test: ZERO,T5 does T5 -= 0 = T5 (unchanged)
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T5}, .Lsdivrem_chk_r_sign")
    # T5 > 0: negate quotient
    
    asm.append(".Lsdivrem_neg_q:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R21}, .Lsdivrem_chk_r_sign")
    
    # Check remainder sign (T6)
    asm.append(".Lsdivrem_chk_r_sign:")
    # Non-destructive sign test: ZERO,T6 does T6 -= 0 = T6 (unchanged)
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .Lsdivrem_pop")
    # T6 > 0: negate remainder
    
    asm.append(".Lsdivrem_neg_rem:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R22}, .Lsdivrem_pop")
    
    # Return sequence
    asm.extend(emit_return_sequence("sdivrem"))
    

    
    asm.append("")
    asm.append("        .size   __subleq_sdivrem, . - __subleq_sdivrem")
    
    return asm


if __name__ == "__main__":
    for line in emit_sdivrem_o32():
        print(line)
