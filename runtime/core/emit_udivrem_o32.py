#!/usr/bin/env python3
"""
Optimized O(32) unsigned division with remainder for Subleq.

OPTIMIZATIONS:
1. Small operand fast paths (8-bit, 16-bit)
2. DIV-A: Z-clean doubling (2 insn instead of 3)
3. DIV-B: Restoring subtraction for bit extraction (+1 bias on T3)
4. DIV-D: Pre-check R22 sign once, dispatch to separate loops
5. DIV-H: Z-clean init copy (Z clean at entry)
6. SPLIT LOOP: R22>0 and R22-big have entirely separate unrolled loops,
   eliminating the 2-op per-bit T5 dispatch on the hot path.

Algorithm (binary long division):
    quotient = 0
    remainder = 0
    for i from 31 down to 0:
        remainder = remainder * 2 + bit[i] of dividend
        if remainder >= divisor:  (UNSIGNED comparison)
            remainder -= divisor
            quotient |= (1 << i)
    return (quotient, remainder)

Register interface:
- Input: R21 = dividend, R22 = divisor (both unsigned)
- Output: R21 = quotient, R22 = remainder (both unsigned)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_runtime import emit_return_sequence, ADDR_Z, ADDR_SP, ADDR_RA, ADDR_ZERO, ADDR_R20, ADDR_R21, ADDR_R22, ADDR_T0, ADDR_T1, ADDR_T2, ADDR_T3, ADDR_T4, ADDR_T5, const_from_pool, ADDR_ONE, ADDR_MINUS_ONE


def _emit_bit31_extract(asm, next_cmp_label):
    """Emit bit 31 extraction (sign-check based, shared by both loops)."""
    i = 31
    threshold = 1 << i
    
    # Step 1: DIV-A: Double remainder (Z clean at entry)
    asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")   # Z = -T1
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T1}, .+4")   # T1 = 2*T1
    
    # Step 2: Extract bit 31 from T3 (sign check)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")      # Z = -T3_biased
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_Z}, .Ludivrem_{i}_le0")
    # Z > 0: T3_biased < 0, bit 31 IS set
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_{i}_bit_set")
    
    asm.append(f".Ludivrem_{i}_le0:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_Z}, .Ludivrem_{i}_z_neg")
    # Z was 0 (now 1): bit IS set
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_{i}_bit_set")
    
    asm.append(f".Ludivrem_{i}_z_neg:")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_cmp_label}")
    
    asm.append(f".Ludivrem_{i}_bit_set:")
    asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_T3}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .+4")  # T1 += 1
    # fall through to comparison


def _emit_r22pos_cmp(asm, i, next_label):
    """Emit the R22>0 fused restoring comparison for bit i."""
    threshold = 1 << i
    
    # Check T1 sign first (non-destructive)
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T1}, .Ludivrem_pos_{i}_t1le0")
    # T1 > 0, R22 > 0: fused comparison
    asm.append(f"        .word   {ADDR_T4}, {ADDR_T1}, .Ludivrem_pos_{i}_no_sub")
    # T1 > 0: complete subtraction
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
    
    asm.append(f".Ludivrem_pos_{i}_no_sub:")
    asm.append(f"        .word   {ADDR_T2}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
    
    asm.append(f".Ludivrem_pos_{i}_t1le0:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .Ludivrem_pos_{i}_t1neg")
    # T1 was 0 (now 1): restore and don't subtract
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
    
    asm.append(f".Ludivrem_pos_{i}_t1neg:")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")


def _emit_r22big_cmp(asm, i, next_label):
    """Emit the R22-big comparison for bit i (R22 has bit 31 set)."""
    threshold = 1 << i
    
    # Z may be dirty from restore-fallthrough path (doubling leaves Z = -T1).
    # Clean Z before using it to copy T1 → T2.
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T2}, .+4")     # T2 = T1
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T2}, .Ludivrem_big_{i}_both_big")
    # T1 > 0: T1 < R22 unsigned. Don't subtract.
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
    
    asm.append(f".Ludivrem_big_{i}_both_big:")
    asm.append(f"        .word   {ADDR_T4}, {ADDR_T4}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T4}, .+4")     # T4 = T1
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T4}, .Ludivrem_big_{i}_signed_cmp")
    # T1 = 0: don't subtract
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
    
    asm.append(f".Ludivrem_big_{i}_signed_cmp:")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T2}, .+4")     # T2 = T1
    asm.append(f"        .word   {ADDR_R22}, {ADDR_T2}, .+4")   # T2 = T1 - R22
    asm.append(f"        .word   {ADDR_T4}, {ADDR_T4}, .+4")
    asm.append(f"        .word   {ADDR_T2}, {ADDR_T4}, .Ludivrem_big_{i}_sub")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
    
    asm.append(f".Ludivrem_big_{i}_sub:")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")


def emit_udivrem_o32():
    """Generate __subleq_udivrem: R21 = R21 / R22, R22 = R21 % R22 (unsigned).
    
    Register usage:
    - R21 = dividend (input), then quotient (output)
    - R22 = divisor (input), then remainder (output)
    - T0 (40) = quotient accumulator
    - T1 (41) = remainder accumulator
    - T2 (42) = scratch / -(R22-1) precomputed for R22>0 path
    - T3 (43) = dividend copy for bit extraction (BIASED +1)
    - T4 (44) = scratch / (R22-1) precomputed for R22>0 path
    - T5 (45) = unused (was R22-sign flag, now eliminated by split loop)
    """
    asm = []
    asm.append("")
    asm.append("        .globl  __subleq_udivrem")
    asm.append("        .type   __subleq_udivrem,@function")
    asm.append("")
    asm.append("# __subleq_udivrem: R21/R22 = quotient/remainder (unsigned)")
    asm.append("# OPTIMIZED: Split R22-pos/R22-big loops (no per-bit dispatch)")
    asm.append("__subleq_udivrem:")
    
    # Initialize: T0 (quotient) = 0, T1 (remainder) = 0
    # DIV-H: Z-clean copy of R21 → T3 (Z is clean at function entry)
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_T3}, .+4")
    # DIV-H: Z is clean at entry, use 3-insn copy
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")     # Z = -R21
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T3}, .+4")      # T3 = R21
    # DIV-B: Bias T3 by +1 for restoring subtraction
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T3}, .+4")  # T3 = R21 + 1
    
    # === ONE-TIME R22 SIGN DISPATCH ===
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Ludivrem_r22big_setup")
    # R22 > 0: precompute fused comparison constants, then enter R22-pos loop
    
    # === Precompute fused comparison constants (R22 > 0 only) ===
    asm.append(f"        .word   {ADDR_T4}, {ADDR_T4}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")           # Z dirty from R21 copy
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T4}, .+4")          # T4 = R22
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T4}, .+4")     # T4 = R22 - 1
    asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")
    asm.append(f"        .word   {ADDR_T4}, {ADDR_T2}, .+4")         # T2 = -(R22-1) = 1-R22
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_chk_small_pos")
    
    asm.append(".Ludivrem_r22big_setup:")
    # R22 <= 0 → R22 has bit 31 set (large unsigned divisor)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_chk_small_big")
    
    # ============================================================
    # SMALL OPERAND FAST PATHS (separate for pos and big)
    # ============================================================
    
    # --- R22-pos small checks ---
    asm.append(".Ludivrem_chk_small_pos:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T3}, .Ludivrem_pos_div_chk_32")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {const_from_pool(-257)}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .Ludivrem_chk_16bit_pos")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_pos_bit7")
    
    asm.append(".Ludivrem_chk_16bit_pos:")
    asm.append(f"        .word   {const_from_pool(-65280)}, {ADDR_Z}, .Ludivrem_chk_24bit_pos")
    # Dividend 16-bit: check divisor >= 256
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {const_from_pool(-256)}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .Ludivrem_pacc16_b15")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_pos_bit15")
    
    asm.append(".Ludivrem_chk_24bit_pos:")
    asm.append(f"        .word   {const_from_pool(-16711680)}, {ADDR_Z}, .Ludivrem_pos_div_chk_32")
    # Dividend 24-bit: check divisor >= 256
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {const_from_pool(-256)}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .Ludivrem_pacc24_b23")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_pos_bit23")
    
    # Dividend 32-bit: check divisor >= 256
    asm.append(".Ludivrem_pos_div_chk_32:")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {const_from_pool(-256)}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .Ludivrem_pacc32_b31")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_pos_bit31")
    
    # --- R22-big small checks (R22 >= 2^31, so ALWAYS >= 256 → always accum) ---
    asm.append(".Ludivrem_chk_small_big:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T3}, .Ludivrem_bacc32_b31")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {const_from_pool(-257)}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .Ludivrem_chk_16bit_big")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_big_bit7")
    
    asm.append(".Ludivrem_chk_16bit_big:")
    asm.append(f"        .word   {const_from_pool(-65280)}, {ADDR_Z}, .Ludivrem_chk_24bit_big")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_bacc16_b15")  # always accum
    
    asm.append(".Ludivrem_chk_24bit_big:")
    asm.append(f"        .word   {const_from_pool(-16711680)}, {ADDR_Z}, .Ludivrem_bacc32_b31")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_bacc24_b23")  # always accum
    
    # === ACCUMULATE-ONLY CHAINS ===
    # When divisor >= 256, first 8 bits of accumulation cannot trigger comparison.
    # Z cleanup needed at every bit (subleq(Z,T1) does NOT modify Z).
    
    # Helper: emit one accum chain
    def _emit_accum_chain(prefix, exit_label, bit_hi, bit_lo, z_clean_entry=False):
        for i in range(bit_hi, bit_lo - 1, -1):
            threshold = 1 << i
            next_lbl = f".Ludivrem_{prefix}_b{i-1}" if i > bit_lo else exit_label
            asm.append(f".Ludivrem_{prefix}_b{i}:")
            if i == 31:
                # Bit 31: sign-check extraction
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_T1}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_ZERO}, {ADDR_Z}, .Ludivrem_{prefix}_31_le0")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_{prefix}_31_set")
                asm.append(f".Ludivrem_{prefix}_31_le0:")
                asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_Z}, .Ludivrem_{prefix}_31_not")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_{prefix}_31_set")
                asm.append(f".Ludivrem_{prefix}_31_not:")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_{prefix}_b30")
                asm.append(f".Ludivrem_{prefix}_31_set:")
                asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_T3}, .+4")
                asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .+4")
            else:
                if not (i == bit_hi and z_clean_entry):
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_T1}, .+4")
                asm.append(f"        .word   {const_from_pool(threshold)}, {ADDR_T3}, .Ludivrem_{prefix}_r{i}")
                asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl}")
                asm.append(f".Ludivrem_{prefix}_r{i}:")
                asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_T3}, .+4")
                if i == bit_lo:  # last bit: explicit exit
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl}")
    
    # Pos-path accum chains
    _emit_accum_chain("pacc16", ".Ludivrem_pos_bit7", 15, 8)
    _emit_accum_chain("pacc24", ".Ludivrem_pos_bit15", 23, 16)
    _emit_accum_chain("pacc32", ".Ludivrem_pos_bit23", 31, 24)
    
    # Big-path accum chains
    _emit_accum_chain("bacc16", ".Ludivrem_big_bit7", 15, 8, z_clean_entry=True)
    _emit_accum_chain("bacc24", ".Ludivrem_big_bit15", 23, 16, z_clean_entry=True)
    _emit_accum_chain("bacc32", ".Ludivrem_big_bit23", 31, 24)
    
    # ============================================================
    # R22-POS LOOP: R22 > 0, uses fused restoring comparison
    # No per-bit T5 dispatch — saves 2 ops/bit = 64 ops total
    # ============================================================
    for i in range(31, -1, -1):
        threshold = 1 << i
        next_label = f".Ludivrem_pos_bit{i-1}" if i > 0 else ".Ludivrem_done"
        
        asm.append(f".Ludivrem_pos_bit{i}:")
        
        if i == 31:
            _emit_bit31_extract(asm, f".Ludivrem_pos_{i}_cmp")
        else:
            # DIV-A: 2-insn doubling (Z clean from previous bit's exit)
            asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_T1}, .+4")
            
            # DIV-B Restoring subtraction for bit extraction
            asm.append(f"        .word   {const_from_pool(threshold)}, {ADDR_T3}, .Ludivrem_pos_{i}_restore")
            # Bit IS set: increment remainder, jump over restore to comparison
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_pos_{i}_cmp")
            
            # Restore block: bit NOT set, restore T3, fall through to comparison
            asm.append(f".Ludivrem_pos_{i}_restore:")
            asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_T3}, .+4")
        
        # Comparison: reached by both bit-set (jump) and bit-not-set (fallthrough) paths
        asm.append(f".Ludivrem_pos_{i}_cmp:")
        _emit_r22pos_cmp(asm, i, next_label)
    
    # ============================================================
    # R22-BIG LOOP: R22 has bit 31 set (rare path)
    # Also no per-bit T5 dispatch
    # ============================================================
    for i in range(31, -1, -1):
        threshold = 1 << i
        next_label = f".Ludivrem_big_bit{i-1}" if i > 0 else ".Ludivrem_done"
        
        asm.append(f".Ludivrem_big_bit{i}:")
        
        if i == 31:
            _emit_bit31_extract_big(asm, f".Ludivrem_big_{i}_cmp")
        else:
            asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_T1}, .+4")
            
            asm.append(f"        .word   {const_from_pool(threshold)}, {ADDR_T3}, .Ludivrem_big_{i}_restore")
            # Bit IS set: increment remainder, jump over restore to comparison
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_big_{i}_cmp")
            
            # Restore block: bit NOT set, restore T3, fall through to comparison
            asm.append(f".Ludivrem_big_{i}_restore:")
            asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_T3}, .+4")
        
        # Comparison: reached by both paths
        asm.append(f".Ludivrem_big_{i}_cmp:")
        _emit_r22big_cmp(asm, i, next_label)
    
    # === DIVISION DONE (shared) ===
    asm.append(".Ludivrem_done:")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R22}, .Ludivrem_pop")
    
    # Return
    asm.extend(emit_return_sequence("udivrem"))
    
    # Constants
    asm.append("")
    asm.append("        .size   __subleq_udivrem, . - __subleq_udivrem")
    
    return asm


def _emit_bit31_extract_big(asm, next_cmp_label):
    """Emit bit 31 extraction for the R22-big loop (separate labels)."""
    i = 31
    threshold = 1 << i
    
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T1}, .+4")
    
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_Z}, .Ludivrem_big_{i}_le0")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_big_{i}_bit_set")
    
    asm.append(f".Ludivrem_big_{i}_le0:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_Z}, .Ludivrem_big_{i}_z_neg")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Ludivrem_big_{i}_bit_set")
    
    asm.append(f".Ludivrem_big_{i}_z_neg:")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_cmp_label}")
    
    asm.append(f".Ludivrem_big_{i}_bit_set:")
    asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_T3}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T1}, .+4")


if __name__ == "__main__":
    for line in emit_udivrem_o32():
        print(line)
