#!/usr/bin/env python3
"""
Optimized O(64) unsigned 64-bit division with remainder for Subleq.
REWRITTEN V4: Matches emit_udivrem_o32.py structure exactly, extended for 64 bits.

OPTIMIZATIONS:
1. DIV-A: Z-clean doubling (2 insn per word instead of 3)
2. DIV-B: Restoring subtraction for bit extraction (+1 bias on T4)
3. DIV-D: Pre-check divisor hi sign once, simplified per-bit comparison
4. Clean borrow detection via pre-save

Algorithm (binary long division):
    quotient = 0
    remainder = 0
    for i from 63 down to 0:
        remainder = remainder * 2 + bit[i] of dividend
        if remainder >= divisor:  (UNSIGNED 64-bit comparison)
            remainder -= divisor
            quotient |= (1 << i)
    return (quotient, remainder)

Register interface:
- Input: R21:R22 = dividend (lo:hi), R23:R24 = divisor (lo:hi)
- Output: R21:R22 = quotient (lo:hi), R23:R24 = remainder (lo:hi)

Internal registers:
- T0:T1 = quotient accumulator (lo:hi)
- T2:T3 = remainder accumulator (lo:hi)
- T4:T5 = dividend copy (lo:hi) - T4 BIASED +1 for restoring sub
- T6 = scratch
- T7 = scratch
- T8 = R24-sign flag (0 = R24 > 0, 1 = R24 has bit 31 set)
- T9 = R23-sign flag (0 = R23 > 0, 1 = R23 has bit 31 set)
- T10 = scratch
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_runtime import emit_return_sequence, ADDR_Z, ADDR_SP, ADDR_RA, ADDR_ZERO, ADDR_R20, ADDR_R21, ADDR_R22, ADDR_R23, ADDR_R24, ADDR_T0, ADDR_T1, ADDR_T2, ADDR_T3, ADDR_T4, ADDR_T5, ADDR_T6, ADDR_T7, ADDR_T8, ADDR_T9, ADDR_T10, const_from_pool, ADDR_ONE, ADDR_MINUS_ONE


def emit_udivrem_o64():
    """Generate __subleq_udivrem64: 64-bit unsigned division with remainder.
    
    Matches emit_udivrem_o32.py per-bit structure:
    1. Double remainder (with carry from lo to hi)
    2. Extract bit from dividend (restoring subtraction)
    3. Compare remainder >= divisor (unsigned 64-bit)
    4. If true: subtract divisor, set quotient bit
    """
    p = "Lud64"  # label prefix
    asm = []
    asm.append("")
    asm.append("        .globl  __subleq_udivrem64")
    asm.append("        .type   __subleq_udivrem64,@function")
    asm.append("")
    asm.append("# __subleq_udivrem64: 64-bit unsigned divrem")
    asm.append("# OPTIMIZED V4: DIV-A/B/D applied, matching o32 structure")
    asm.append("__subleq_udivrem64:")
    
    # Initialize: T0:T1 (quotient) = 0, T2:T3 (remainder) = 0
    # Copy dividend R21:R22 to T4:T5 (Z-clean at entry)
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_T3}, .+4")
    # DIV-H: Z is clean at function entry, use 3-insn copy for T4
    asm.append(f"        .word   {ADDR_T4}, {ADDR_T4}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")     # Z = -R21
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T4}, .+4")      # T4 = R21
    # DIV-B: Bias T4 by +1 for restoring subtraction
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T4}, .+4")     # T4 = R21 + 1
    # Copy R22 to T5
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T5}, .+4")      # T5 = R22
    # DIV-B: Bias T5 by +1 for restoring subtraction (hi word)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T5}, .+4")     # T5 = R22 + 1
    
    # DIV-D: Pre-check R24 sign ONCE before the loop
    # Need proper 3-step check: R24=0 should be treated as "positive" (no bit 31 set)
    asm.append(f"        .word   {ADDR_T8}, {ADDR_T8}, .+4")     # T8 = 0
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R24}, .{p}_r24_le0")
    # R24 > 0: T8 = 0 (already). Clean Z.
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_precheck_r23")
    
    asm.append(f".{p}_r24_le0:")
    # OPTIMIZED: combined restore+branch on R24. R24+1<=0 -> truly big (including INT_MIN)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R24}, .{p}_r24_neg_restore")  # R24+=1; if<=0 -> big
    # R24 was 0: restore, T8 stays 0, proceed
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R24}, .{p}_precheck_r23")  # restore+branch
    asm.append(f".{p}_r24_neg_restore:")
    # R24 was < 0 (including INT_MIN): restore
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R24}, .+4")  # restore+branch
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T8}, .+4")     # T8 = 1
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_precheck_r23")
    
    # Pre-check R23 sign ONCE (same 3-step pattern)
    asm.append(f".{p}_precheck_r23:")
    asm.append(f"        .word   {ADDR_T9}, {ADDR_T9}, .+4")     # T9 = 0
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R23}, .{p}_r23_le0")
    # R23 > 0: T9 = 0.
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_chk_small")
    
    asm.append(f".{p}_r23_le0:")
    # OPTIMIZED: combined restore+branch on R23. R23+1<=0 -> truly big (including INT_MIN)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R23}, .{p}_r23_neg_restore")  # R23+=1; if<=0 -> big
    # R23 was 0: restore, T9 stays 0, proceed
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R23}, .{p}_chk_small")  # restore+branch
    asm.append(f".{p}_r23_neg_restore:")
    # R23 was < 0 (including INT_MIN): restore
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R23}, .+4")  # restore+branch
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T9}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_chk_small")
    
    # === SMALL OPERAND FAST PATH ===
    # Check if dividend hi (T5, biased) indicates hi = 0: T5_biased = R22 + 1
    # If R22 = 0, T5_biased = 1. T5_biased <= 0 means R22+1 <= 0 means R22 < 0 or R22 = INT_MAX -> full path
    # T5_biased > 0 and T5_biased <= 1 means R22 = 0 -> skip to bit 31
    asm.append(f".{p}_chk_small:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T5}, .{p}_bit63")  # T5 <= 0 → hi word nonzero or wrapped
    # T5 > 0. Check if T5 = 1 (meaning R22 = 0): T5 - 1 <= 0 → T5 <= 1
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T5}, .{p}_hi_zero")
    # T5 > 1, meaning R22 > 0. Restore T5, go to full path.
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T5}, .+4")     # T5 restored
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_bit63")
    
    asm.append(f".{p}_hi_zero:")
    # Dividend hi = 0. Restore T5 to 1 (biased 0).
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T5}, .+4")     # T5 = 1 again
    # T4_biased = R21 + 1. Check: T4 <= 0 → full path (32-bit dividend)
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T4}, .{p}_div_chk_32")
    # T4 > 0: cascade 8→16→24
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word   {const_from_pool(-257)}, {ADDR_T6}, .+4")      # T6 = 257
    asm.append(f"        .word   {ADDR_T4}, {ADDR_T6}, .{p}_chk_16bit")  # T4 >= 257 → check 16
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_bit7")
    
    asm.append(f".{p}_chk_16bit:")
    asm.append(f"        .word   {const_from_pool(-65280)}, {ADDR_T6}, .{p}_chk_24bit")
    # Dividend 16-bit: check divisor lo >= 256 (simple signed check, covers common cases)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {const_from_pool(-256)}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R23}, {ADDR_Z}, .{p}_acc16_b15")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_bit15")
    
    asm.append(f".{p}_chk_24bit:")
    asm.append(f"        .word   {const_from_pool(-16711680)}, {ADDR_T6}, .{p}_div_chk_32")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {const_from_pool(-256)}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R23}, {ADDR_Z}, .{p}_acc24_b23")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_bit23")
    
    # Dividend 32-bit: check divisor lo >= 256
    asm.append(f".{p}_div_chk_32:")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {const_from_pool(-256)}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R23}, {ADDR_Z}, .{p}_acc32_b31")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_bit31")
    
    # === ACCUMULATE-ONLY CHAINS (64-bit, small-operand path) ===
    # In the hi_zero path: T3 = 0, T5 = 1 (biased 0). Only T2 needs doubling.
    # Extract from T4 (lo word dividend). Z cleanup at every bit.
    def _emit_accum64(prefix, exit_label, bit_hi, bit_lo):
        for i in range(bit_hi, bit_lo - 1, -1):
            threshold = 1 << i
            next_lbl = f".{p}_{prefix}_b{i-1}" if i > bit_lo else exit_label
            asm.append(f".{p}_{prefix}_b{i}:")
            if i == 31:
                # Bit 31: sign-check extraction on T4 (biased)
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_T2}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_T4}, {ADDR_Z}, .+4")     # Z = -T4_biased
                asm.append(f"        .word   {ADDR_ZERO}, {ADDR_Z}, .{p}_{prefix}_31_le0")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{prefix}_31_set")
                asm.append(f".{p}_{prefix}_31_le0:")
                asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_Z}, .{p}_{prefix}_31_not")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{prefix}_31_set")
                asm.append(f".{p}_{prefix}_31_not:")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{prefix}_b30")
                asm.append(f".{p}_{prefix}_31_set:")
                asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_T4}, .+4")
                asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T2}, .+4")
            else:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_T2}, .+4")     # T2 *= 2
                asm.append(f"        .word   {const_from_pool(threshold)}, {ADDR_T4}, .{p}_{prefix}_r{i}")
                asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T2}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl}")
                asm.append(f".{p}_{prefix}_r{i}:")
                asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_T4}, .+4")
                if i == bit_lo:
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl}")
    
    _emit_accum64("acc16", f".{p}_bit7", 15, 8)
    _emit_accum64("acc24", f".{p}_bit15", 23, 16)
    _emit_accum64("acc32", f".{p}_bit23", 31, 24)
    
    # === MAIN DIVISION LOOP ===
    for i in range(63, -1, -1):
        next_label = f".{p}_bit{i-1}" if i > 0 else f".{p}_done"
        
        asm.append(f".{p}_bit{i}:")
        
        # === Step 1: Double 64-bit remainder T2:T3 ===
        # Check T2 sign for carry BEFORE doubling (using ZERO,T2 test)
        # Z must be clean on entry (guaranteed by loop structure)
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T2}, .{p}_{i}_t2_le0")
        # T2 > 0: no carry from bit 31
        # Double T2 (Z-clean): T2,Z; Z,T2
        asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T2}, .+4")
        # Double T3 (Z dirty, need clean): Z,Z; T3,Z; Z,T3
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T3}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_ex")
        
        asm.append(f".{p}_{i}_t2_le0:")
        # OPTIMIZED: combined restore+branch on T2. T2+1<=0 -> truly negative (carry, including INT_MIN)
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T2}, .{p}_{i}_t2_neg_restore")  # T2+=1; if<=0 -> carry
        # T2 was 0 (now 1): restore, no carry
        asm.append(f"        .word   {ADDR_ONE}, {ADDR_T2}, .{p}_{i}_dbl_nocarry")  # restore+branch
        asm.append(f".{p}_{i}_t2_neg_restore:")
        # T2 was < 0 (including INT_MIN): restore T2, has carry
        asm.append(f"        .word   {ADDR_ONE}, {ADDR_T2}, .+4")  # restore+branch
        # T2 < 0, carry:
        
        asm.append(f".{p}_{i}_dbl_carry:")
        # Double T2: Z,Z; T2,Z; Z,T2
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T2}, .+4")
        # Double T3: Z,Z; T3,Z; Z,T3
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T3}, .+4")
        # Add carry: T3 += 1
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T3}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_ex")
        
        asm.append(f".{p}_{i}_dbl_nocarry:")
        # T2 = 0. Doubling 0 is still 0. Just double T3.
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T3}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_ex")
        
        # === Step 2: Extract bit[i] from dividend ===
        asm.append(f".{p}_{i}_ex:")
        # Z is clean from the jump above
        
        # Bits 63-32 are in T5 (hi), bits 31-0 are in T4 (lo). Both biased +1.
        if i >= 32:
            target_reg = ADDR_T5
            bit_idx = i - 32
        else:
            target_reg = ADDR_T4
            bit_idx = i
        
        if bit_idx == 31:
            # Bit 31: Cannot use restoring subtraction (threshold = INT_MIN).
            # Use sign-check on original value (biased - 1).
            asm.append(f"        .word   {target_reg}, {ADDR_Z}, .+4")     # Z = -biased
            asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")       # T6 = biased
            asm.append(f"        .word   {ADDR_ONE}, {ADDR_T6}, .+4")       # T6 = biased - 1 = original
            asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_b31_le0")
            # original > 0: bit 31 not set
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_cmp")
            
            asm.append(f".{p}_{i}_b31_le0:")
            # original <= 0: check < 0 vs = 0
            asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
            asm.append(f"        .word   {ADDR_T6}, {ADDR_T7}, .+4")      # T7 = -original
            asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T7}, .{p}_{i}_b31_ambig")
            # -original > 0: original < 0, bit 31 IS set
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_b31_set")
            
            asm.append(f".{p}_{i}_b31_ambig:")
            asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
            asm.append(f"        .word   {ADDR_T6}, {ADDR_T7}, .+4")
            asm.append(f"        .word   {ADDR_ONE}, {ADDR_T7}, .+4")       # T7 = -original - 1
            asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T7}, .{p}_{i}_cmp")  # <= 0: original = 0
            # original = INT_MIN, bit 31 IS set
            
            asm.append(f".{p}_{i}_b31_set:")
            threshold = 1 << 31
            asm.append(f"        .word   {const_from_pool(-2147483648)}, {target_reg}, .+4")  # Clear bit 31
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T2}, .+4")     # T2 += 1 (add to remainder)
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_cmp")
        else:
            # DIV-B: Bits 30-0 — restoring subtraction (biased target_reg)
            threshold = 1 << bit_idx
            asm.append(f"        .word   {const_from_pool(threshold)}, {target_reg}, .{p}_{i}_restore")
            # Fell through: biased > 0 after sub, bit IS set. Already decremented.
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T2}, .+4")     # T2 += 1 (add to remainder)
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_cmp")
            
            asm.append(f".{p}_{i}_restore:")
            # Bit NOT set. Restore target_reg.
            asm.append(f"        .word   {const_from_pool(-threshold)}, {target_reg}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_cmp")
        
        # === Step 3: Compare remainder (T2:T3) >= divisor (R23:R24) unsigned ===
        asm.append(f".{p}_{i}_cmp:")
        # Z-clear needed only for bit_idx==31 paths (bits 63,31) which have
        # a conditional predecessor subleq(ZERO,T7,_cmp) that doesn't clear Z.
        # All other bits arrive only via subleq(Z,Z,target) jumps (Z already clean).
        if bit_idx == 31:
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        
        # Compare high words first: T3 vs R24 (unsigned)
        # Branch on pre-computed R24 sign flag
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T8}, .{p}_{i}_r24pos")
        # T8 > 0: R24 has bit 31 set (large unsigned)
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_r24big")
        
        # === R24 > 0 path (common) ===
        asm.append(f".{p}_{i}_r24pos:")
        # Copy T3 → T6 for comparison
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")      # Z = -T3
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")      # T6 = T3
        # Check T3 sign
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_t3le0")
        # T3 > 0, R24 > 0: both positive, signed compare
        asm.append(f"        .word   {ADDR_R24}, {ADDR_T6}, .+4")    # T6 = T3 - R24
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T7}, .{p}_{i}_hi_gt")  # T7=-T6; <=0 → T6>=0 → T3>=R24
        # T6 < 0: T3 < R24. FALSE.
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
        
        asm.append(f".{p}_{i}_hi_gt:")
        # T3 >= R24 (unsigned). Check if T3 > R24 or T3 == R24.
        # T6 = T3 - R24. If T6 > 0: T3 > R24, definitely TRUE → sub
        # If T6 = 0: T3 == R24, need to compare low words
        # T7 = -T6 was computed. T7 <= 0 means T6 >= 0.
        # Check T7: if T7 < 0 → T6 > 0. If T7 = 0 → T6 = 0.
        # Actually T7 = -T6. T7 < 0 iff T6 > 0 iff T3 > R24.
        # But T7 <= 0 from the branch. So T7 < 0 → T3 > R24 → sub.
        # T7 = 0 → T3 = R24 → lo_cmp.
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T6}, .+4")     # T6 = -T7 = T3-R24
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_lo_cmp")  # <= 0 → T3-R24=0 → equal
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_sub")  # T3-R24 > 0 → T3 > R24 → sub
        
        asm.append(f".{p}_{i}_t3le0:")
        # T3 <= 0, R24 >= 0 (no bit 31). Z = -T3 from copy.
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T7}, .+4")      # T7 = -Z = T3
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T7}, .{p}_{i}_sub")  # T7=T3+1; <=0 → T3<0 → large → sub
        # T3 = 0. Check if R24 is also 0 (equal → lo_cmp) or R24 > 0 (FALSE).
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R24}, .{p}_{i}_lo_cmp")  # R24 <= 0 → R24=0 (T8=0) → equal
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")  # R24 > 0 → FALSE
        
        # === R24 has bit 31 set (rare) ===
        asm.append(f".{p}_{i}_r24big:")
        # Z is clean. Copy T3 → T6.
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")      # T6 = T3
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_both_big")
        # T3 > 0: T3 (small) < R24 (large unsigned). FALSE.
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
        
        asm.append(f".{p}_{i}_both_big:")
        # T3 <= 0, R24 <= 0. Check T3 = 0 vs T3 < 0.
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T7}, .+4")      # T7 = T3
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T7}, .{p}_{i}_hi_signed")  # T7=T3+1; <=0 → T3<0
        # T3 = 0: 0 < R24 (large). FALSE.
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
        
        asm.append(f".{p}_{i}_hi_signed:")
        # Both T3 and R24 have bit 31 set. Signed compare works.
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")      # T6 = T3
        asm.append(f"        .word   {ADDR_R24}, {ADDR_T6}, .+4")    # T6 = T3 - R24
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T7}, .{p}_{i}_hi_gt_s")  # T7=-T6; <=0 → T6>=0
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
        
        asm.append(f".{p}_{i}_hi_gt_s:")
        # T3 >= R24 (signed, both negative = both large unsigned). Check equal.
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T6}, .+4")     # T6 = -T7 = T3-R24
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_lo_cmp")  # <= 0 → equal
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_sub")  # T3 > R24 → sub
        
        # === Low word comparison (T2 vs R23, unsigned) ===
        # Hi words are equal. Compare using same DIV-D pattern with T9.
        asm.append(f".{p}_{i}_lo_cmp:")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        # Branch on R23 sign flag
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T9}, .{p}_{i}_r23pos")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_r23big")
        
        # R23 > 0
        asm.append(f".{p}_{i}_r23pos:")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")      # T6 = T2
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_t2le0")
        # T2 > 0, R23 > 0: signed compare T2 - R23
        asm.append(f"        .word   {ADDR_R23}, {ADDR_T6}, .+4")    # T6 = T2 - R23
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T7}, .{p}_{i}_sub")  # <=0 → T6>=0 → sub
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
        
        asm.append(f".{p}_{i}_t2le0:")
        # T2 <= 0, R23 >= 0 (no bit 31). Z = -T2.
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T7}, .+4")      # T7 = T2
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T7}, .{p}_{i}_sub")  # T7=T2+1; <=0 → T2<0 → large → sub
        # T2 = 0. Check if R23 is also 0 (equal → sub) or R23 > 0 (FALSE).
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R23}, .{p}_{i}_sub")  # R23 <= 0 → R23=0 → equal → sub
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")  # R23 > 0 → FALSE
        
        # R23 has bit 31 set (rare)
        asm.append(f".{p}_{i}_r23big:")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")      # T6 = T2
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_lo_both_big")
        # T2 > 0: T2 (small) < R23 (large). FALSE.
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
        
        asm.append(f".{p}_{i}_lo_both_big:")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T7}, .+4")      # T7 = T2
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T7}, .{p}_{i}_lo_signed")  # T7=T2+1; <=0 → T2<0
        # T2 = 0: 0 < R23 (large). FALSE.
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
        
        asm.append(f".{p}_{i}_lo_signed:")
        # Both have bit 31 set. Signed compare.
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_R23}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T7}, .{p}_{i}_sub")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
        
        # === Step 4: Subtract divisor from remainder, handle borrow, set quotient bit ===
        asm.append(f".{p}_{i}_sub:")
        # 64-bit subtraction: T2:T3 -= R23:R24
        # Save T2 before subtraction for borrow detection
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")      # T6 = T2 (saved)
        # T2 -= R23
        asm.append(f"        .word   {ADDR_R23}, {ADDR_T2}, .+4")
        # T3 -= R24
        asm.append(f"        .word   {ADDR_R24}, {ADDR_T3}, .+4")
        
        # Borrow detection: did T2 - R23 underflow?
        # T6 = old_T2. We need: was old_T2 < R23 (unsigned)?
        # Use DIV-D style unsigned comparison with T9 (R23 sign flag)
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T9}, .{p}_{i}_br_r23pos")
        # R23 has bit 31 set. Check T6 (old T2).
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_br_both_big")
        # T6 > 0: old_T2 small, R23 large. Borrow.
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_do_borrow")
        
        asm.append(f".{p}_{i}_br_both_big:")
        # T6 <= 0, R23 <= 0. Check T6 = 0 vs T6 < 0.
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T7}, .+4")      # T7 = T6
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T7}, .{p}_{i}_br_signed")  # T7=T6+1; <=0 → T6<0
        # T6 = 0: 0 < R23 (large). Borrow.
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_do_borrow")
        
        asm.append(f".{p}_{i}_br_signed:")
        # Both T6 and R23 have bit 31 set. Signed compare gives correct unsigned order.
        # T7 = T6-R23. T7>0 → T6>R23 → no borrow. T7=0 → equal → no borrow. T7<0 → borrow.
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T7}, .+4")      # T7 = T6
        asm.append(f"        .word   {ADDR_R23}, {ADDR_T7}, .+4")    # T7 = T6 - R23
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T7}, .{p}_{i}_br_s_le0")  # T7 <= 0
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_setq")  # T7 > 0 → no borrow
        asm.append(f".{p}_{i}_br_s_le0:")
        # T7 <= 0. T7=0 → equal → no borrow. T7<0 → borrow.
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T6}, .+4")     # T6 = -T7
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_setq")  # -T7 <= 0 → T7>=0 → T7=0 → no borrow
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_do_borrow")
        
        asm.append(f".{p}_{i}_br_r23pos:")
        # R23 > 0. Check T6 (old T2).
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T7}, .+4")      # T7 = T6
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T7}, .{p}_{i}_br_t6le0")
        # T6 > 0, R23 > 0: signed compare. T6 - R23 < 0 → borrow
        asm.append(f"        .word   {ADDR_R23}, {ADDR_T7}, .+4")    # T7 = T6 - R23
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T7}, .{p}_{i}_br_chk_strict")
        # T7 > 0: T6 > R23. No borrow.
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_setq")
        
        asm.append(f".{p}_{i}_br_chk_strict:")
        # T7 <= 0: T6 <= R23. T6 < R23 → borrow. T6 = R23 → no borrow.
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T6}, .+4")     # T6 = -T7
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_setq")  # -T7 <= 0 → T7 >= 0 → no borrow (equal)
        # T7 < 0 → T6 < R23. Borrow.
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_do_borrow")
        
        asm.append(f".{p}_{i}_br_t6le0:")
        # T6 <= 0, R23 >= 0. Check if T6 < 0 (large unsigned, no borrow) or T6 = 0.
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T7}, .+4")      # T7 = T6 (Z had -T6)
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T7}, .{p}_{i}_setq")  # T7=T6+1; <=0 → T6<0 → large → no borrow
        # T6 = 0. Check if R23 is also 0 (no borrow) or R23 > 0 (borrow).
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R23}, .{p}_{i}_setq")  # R23 <= 0 → R23=0 → equal → no borrow
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_do_borrow")  # R23 > 0 → borrow
        
        asm.append(f".{p}_{i}_do_borrow:")
        asm.append(f"        .word   {ADDR_ONE}, {ADDR_T3}, .+4")      # T3 -= 1 (borrow)
        
        # Set quotient bit
        asm.append(f".{p}_{i}_setq:")
        if i >= 32:
            q_reg = ADDR_T1
            q_bit = i - 32
        else:
            q_reg = ADDR_T0
            q_bit = i
        val = 1 << q_bit
        # Clean Z for next iteration's doubling
        asm.append(f"        .word   {const_from_pool(-val)}, {q_reg}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
    
    # === Division complete, copy results ===
    asm.append(f".{p}_done:")
    # Copy quotient T0:T1 → R21:R22
    asm.append(f"        .word   {ADDR_R21}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R21}, .+4")     # R21 = T0
    asm.append(f"        .word   {ADDR_R22}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R22}, .+4")     # R22 = T1
    # Copy remainder T2:T3 → R23:R24
    asm.append(f"        .word   {ADDR_R23}, {ADDR_R23}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R23}, .+4")     # R23 = T2
    asm.append(f"        .word   {ADDR_R24}, {ADDR_R24}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R24}, .{p}_pop")  # R24 = T3
    
    # Return sequence
    asm.extend(emit_return_sequence("ud64"))
    
    
    
    
    asm.append("")
    asm.append("        .size   __subleq_udivrem64, . - __subleq_udivrem64")
    
    return asm


if __name__ == "__main__":
    for line in emit_udivrem_o64():
        print(line)
