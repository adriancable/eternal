#!/usr/bin/env python3
"""
Optimized O(64) signed 64-bit division with remainder for Subleq.
REWRITTEN V3: Mirrors emit_sdivrem_o32.py structure exactly, extended for 64 bits.

Algorithm:
1. Determine signs of dividend and divisor (check hi word bit 31)
2. Take absolute values of both operands
3. Perform INLINE O(64) binary long division (does NOT call udivrem64)
4. Apply signs to results:
   - Quotient sign: XOR of operand signs (negative if signs differ)
   - Remainder sign: Same as dividend sign

Register interface:
- Input: R21:R22 = dividend (lo:hi), R23:R24 = divisor (lo:hi)
- Output: R21:R22 = quotient (lo:hi), R23:R24 = remainder (lo:hi)

Internal State:
- T0:T1 = quotient accumulator (lo:hi)
- T2:T3 = remainder accumulator (lo:hi)
- T4:T5 = dividend copy (lo:hi) - for bit extraction
- T6, T7, T8 = scratch
- T9 = quotient sign flag (0 = positive, 1 = negative)
- T10 = dividend sign flag (for remainder sign)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_runtime import emit_return_sequence, ADDR_Z, ADDR_SP, ADDR_RA, ADDR_ZERO, ADDR_R20, ADDR_R21, ADDR_R22, ADDR_R23, ADDR_R24, ADDR_T0, ADDR_T1, ADDR_T2, ADDR_T3, ADDR_T4, ADDR_T5, ADDR_T6, ADDR_T7, ADDR_T8, ADDR_T9, ADDR_T10, const_from_pool, ADDR_ONE, ADDR_MINUS_ONE

def emit_sdivrem_o64():
    """Generate __subleq_sdivrem64: 64-bit signed division with remainder.
    
    This does the division INLINE (like emit_sdivrem_o32.py), not by calling udivrem64.
    
    Register usage:
    - R21:R22 = dividend (input), then quotient (output)
    - R23:R24 = divisor (input), then remainder (output)
    - T0:T1 = quotient accumulator (lo:hi)
    - T2:T3 = remainder accumulator (lo:hi)
    - T4:T5 = dividend copy for bit extraction (lo:hi)
    - T6, T7, T8 = scratch
    - T9 = quotient sign flag
    - T10 = dividend sign flag (for remainder sign)
    """
    asm = []
    asm.append("")
    asm.append("        .globl  __subleq_sdivrem64")
    asm.append("        .type   __subleq_sdivrem64,@function")
    asm.append("")
    asm.append("# __subleq_sdivrem64: 64-bit signed divrem (inline algorithm)")
    asm.append("# Input: R21:R22 = dividend (lo:hi), R23:R24 = divisor (lo:hi)")
    asm.append("# Output: R21:R22 = quotient (lo:hi), R23:R24 = remainder (lo:hi)")
    asm.append("__subleq_sdivrem64:")
    
    # === Initialize sign flags ===
    # T9 = quotient sign (0 = positive), T10 = dividend sign (for remainder)
    asm.append(f"        .word   {ADDR_T9}, {ADDR_T9}, .Lsd64v_init1")
    asm.append(".Lsd64v_init1:")
    asm.append(f"        .word   {ADDR_T10}, {ADDR_T10}, .Lsd64v_chk_div")
    
    # === Check if dividend (R21:R22) is negative (check R22 hi word bit 31) ===
    asm.append(".Lsd64v_chk_div:")
    # OPTIMIZED: combined restore+branch on R22. R22+1<=0 -> negative (neg_dividend)
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lsd64v_div_le0")
    # R22 > 0, dividend is positive
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsd64v_chk_dsr")
    asm.append(".Lsd64v_div_le0:")
    # R22 <= 0: R22+1<=0 -> negative; else R22 was 0 -> positive
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .Lsd64v_div_neg_restore")  # R22+=1; if<=0 -> neg
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .Lsd64v_chk_dsr")  # restore+branch
    asm.append(".Lsd64v_div_neg_restore:")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .+4")  # restore+branch
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsd64v_neg_dividend")
    asm.append(".Lsd64v_neg_dividend:")
    # Set quotient sign flag = 1 (will be XOR'd with divisor sign)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T9}, .Lsd64v_nd1")  # T9 = 1
    asm.append(".Lsd64v_nd1:")
    # Set remainder sign flag = 1
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T10}, .+4")  # T10 = 1
    
    # Negate 64-bit dividend: R21:R22 = -(R21:R22)
    # -X = (~X + 1) = (0 - X_lo, 0 - X_hi - borrow)
    # T6 = -R21
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_T6}, .+4")  # T6 = -R21
    # T7 = -R22
    asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_T7}, .+4")  # T7 = -R22
    # Check if R21 was 0 (no borrow needed) - need 3-step check for robustness
    # Step 1: T8 = R21, check if <= 0
    asm.append(f"        .word   {ADDR_T8}, {ADDR_T8}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T8}, .+4")  # T8 = R21
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T8}, .Lsd64v_nd_step2")  # if R21 <= 0, go to step 2
    # R21 > 0, need borrow: T7 -= 1
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T7}, .Lsd64v_nd_noborrow")
    # Unconditional jump in case T7 > 0 after subtraction (subleq didn't branch)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsd64v_nd_noborrow")
    
    # Step 2: Check if -R21 <= 0
    asm.append(".Lsd64v_nd_step2:")
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word   {ADDR_T8}, {ADDR_T5}, .+4")  # T5 = -T8 = -R21
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T5}, .Lsd64v_nd_step3")  # if -R21 <= 0, go to step 3
    # -R21 > 0, so R21 < 0, need borrow
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T7}, .Lsd64v_nd_noborrow")
    # Unconditional jump in case T7 > 0 after subtraction
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsd64v_nd_noborrow")
    
    # Step 3: R21 is 0 or 0x80000000
    asm.append(".Lsd64v_nd_step3:")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T8}, .+4")  # T8 = R21 - 1
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T8}, .Lsd64v_nd_noborrow")  # if R21-1 <= 0, R21 = 0, no borrow
    # R21 = 0x80000000, need borrow
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T7}, .Lsd64v_nd_noborrow")
    
    asm.append(".Lsd64v_nd_noborrow:")
    # R21 = T6, R22 = T7
    asm.append(f"        .word   {ADDR_R21}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T6}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T7}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R22}, .Lsd64v_chk_dsr")
    
    # === Check if divisor (R23:R24) is negative (check R24 hi word bit 31) ===
    asm.append(".Lsd64v_chk_dsr:")
    # OPTIMIZED: combined restore+branch on R24. R24+1<=0 -> negative (neg_divisor)
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R24}, .Lsd64v_dsr_le0")
    # R24 > 0, divisor is positive
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsd64v_do_div")
    asm.append(".Lsd64v_dsr_le0:")
    # R24 <= 0: R24+1<=0 -> negative; else R24 was 0 -> positive
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R24}, .Lsd64v_dsr_neg_restore")  # R24+=1; if<=0 -> neg
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R24}, .Lsd64v_do_div")  # restore+branch
    asm.append(".Lsd64v_dsr_neg_restore:")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R24}, .+4")  # restore+branch
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsd64v_neg_divisor")
    asm.append(".Lsd64v_neg_divisor:")
    # Toggle T9: T9 = 1 - T9 (XOR effect)
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T9}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")  # T6 = T9
    asm.append(f"        .word   {ADDR_T9}, {ADDR_T9}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T9}, .+4")  # T9 = 1
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T9}, .Lsd64v_neg_dsr")  # T9 = 1 - old_T9
    
    asm.append(".Lsd64v_neg_dsr:")
    # Negate 64-bit divisor: R23:R24 = -(R23:R24)
    # T6 = -R23
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .Lsd64v_nsr1")
    asm.append(".Lsd64v_nsr1:")
    asm.append(f"        .word   {ADDR_R23}, {ADDR_T6}, .+4")  # T6 = -R23
    # T7 = -R24
    asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
    asm.append(f"        .word   {ADDR_R24}, {ADDR_T7}, .+4")  # T7 = -R24
    # Check borrow - need 3-step check for R23 != 0
    # Step 1: T8 = R23, check if <= 0
    asm.append(f"        .word   {ADDR_T8}, {ADDR_T8}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R23}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T8}, .+4")  # T8 = R23
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T8}, .Lsd64v_nsr_step2")  # if R23 <= 0, go to step 2
    # R23 > 0, need borrow
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T7}, .Lsd64v_nsr_noborrow")
    # Unconditional jump in case T7 > 0 after subtraction
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsd64v_nsr_noborrow")
    
    # Step 2: Check if -R23 <= 0
    asm.append(".Lsd64v_nsr_step2:")
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word   {ADDR_T8}, {ADDR_T5}, .+4")  # T5 = -T8 = -R23
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T5}, .Lsd64v_nsr_step3")  # if -R23 <= 0, go to step 3
    # -R23 > 0, so R23 < 0, need borrow
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T7}, .Lsd64v_nsr_noborrow")
    # Unconditional jump in case T7 > 0 after subtraction
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsd64v_nsr_noborrow")
    
    # Step 3: R23 is 0 or 0x80000000
    asm.append(".Lsd64v_nsr_step3:")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T8}, .+4")  # T8 = R23 - 1
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T8}, .Lsd64v_nsr_noborrow")  # if R23-1 <= 0, R23 = 0, no borrow
    # R23 = 0x80000000, need borrow
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T7}, .Lsd64v_nsr_noborrow")
    
    asm.append(".Lsd64v_nsr_noborrow:")
    asm.append(f"        .word   {ADDR_R23}, {ADDR_R23}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T6}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R23}, .+4")
    asm.append(f"        .word   {ADDR_R24}, {ADDR_R24}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T7}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R24}, .Lsd64v_do_div")
    
    # === O(64) division (V4: DIV-A/B/D optimized) ===
    # After sign handling, both dividend and divisor are positive (absolute values).
    # Hi words (R24, T3) always in [0, 0x7FFFFFFF] → simple signed compare.
    # Lo words (R23, T2) can have bit 31 set → need DIV-D for lo-word compare.
    p = "Lsd64v"
    
    asm.append(f".{p}_do_div:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_T1}, .+4")
    asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_T3}, .+4")
    # Copy R21 → T4 (MUST clean Z first — nsr_noborrow exit may leave Z dirty)
    asm.append(f"        .word   {ADDR_T4}, {ADDR_T4}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T4}, .+4")      # T4 = R21
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T4}, .+4")  # T4 = R21 + 1 (biased)
    # Copy R22 → T5, bias +1
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T5}, .+4")      # T5 = R22
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T5}, .+4")  # T5 = R22 + 1 (biased)
    
    # === DIV-C: Check for LLONG_MIN divisor (R24 = 0x80000000 after abs) ===
    # After abs, R24 > 0 is normal. R24 = 0 means divisor fits in 32 bits (normal).
    # R24 = 0x80000000 means divisor was LLONG_MIN (abs overflow). Handle specially.
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R24}, .{p}_r24_le0")
    # R24 > 0: normal path. Clean Z.
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_precheck")
    
    asm.append(f".{p}_r24_le0:")
    # R24 <= 0: combined restore+branch. R24+1<=0 -> R24=INT_MIN (LLONG_MIN divisor)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R24}, .{p}_r24_neg_restore")  # R24+=1; if<=0 -> INT_MIN
    # R24 was 0: restore, normal path
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R24}, .{p}_precheck")  # restore+branch
    asm.append(f".{p}_r24_neg_restore:")
    # R24 was negative (= INT_MIN): restore R24
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R24}, .+4")  # restore+branch, T6 now unused
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_intmin_dsr")


    # === LLONG_MIN divisor handler ===
    # Divisor = LLONG_MIN. abs(dividend) <= LLONG_MAX < LLONG_MIN unsigned.
    # So quotient = 0, remainder = abs(dividend) UNLESS dividend was also LLONG_MIN.
    # If dividend was LLONG_MIN: abs(dividend) overflows too, R22 = 0x80000000, R21 = 0.
    asm.append(f".{p}_intmin_dsr:")
    # Check R22 > 0 → dividend < LLONG_MIN → quot=0, rem=R21:R22
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")      # T6 = R22
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_intmin_r22_le0")
    # R22 > 0 → quotient = 0, remainder = R21:R22 (already in T2:T3 = 0, copy)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_intmin_q0")
    
    asm.append(f".{p}_intmin_r22_le0:")
    # R22 <= 0. Check if R22 = 0 (normal small dividend) or R22 = INT_MIN (LLONG_MIN).
    asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T7}, .+4")     # T7 = -R22
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T7}, .{p}_intmin_r22_ambig")
    # -R22 > 0: R22 < 0 → R22 = INT_MIN → dividend was LLONG_MIN → quot=1, rem=0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_intmin_eq")
    asm.append(f".{p}_intmin_r22_ambig:")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T7}, .+4")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T7}, .{p}_intmin_q0")  # R22 = 0
    # R22 = INT_MIN → dividend = LLONG_MIN
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_intmin_eq")
    
    asm.append(f".{p}_intmin_q0:")
    # Quotient = 0 (T0:T1 already 0), Remainder = abs(dividend) = R21:R22
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T2}, .+4")      # T2 = R21
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T3}, .+4")           # T3 = R22 (may be > 0)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_div_done")
    
    asm.append(f".{p}_intmin_eq:")
    # Both LLONG_MIN. Quotient = 1, Remainder = 0 (already).
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T0}, .+4")  # T0 = 1
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_div_done")
    
    # === DIV-D: Pre-check R23 sign flag → T8 ===
    asm.append(f".{p}_precheck:")
    # After abs-value, R24 is always positive, so no T8 needed for R24.
    # R23 (lo divisor) can have bit 31 set.
    asm.append(f"        .word   {ADDR_T8}, {ADDR_T8}, .+4")
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R23}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")      # T6 = R23
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_r23_le0")
    # R23 > 0: T8 = 0 (already). Check fast path.
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_chk_small")
    asm.append(f".{p}_r23_le0:")
    # R23 <= 0: combined restore+branch on R23 directly. R23+1<=0 -> big (bit 31 set)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R23}, .{p}_r23_neg_restore")  # R23+=1; if<=0 -> big
    # R23 was 0: restore, T8 stays 0
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R23}, .{p}_chk_small")  # restore+branch
    asm.append(f".{p}_r23_neg_restore:")
    # R23 was < 0 (including INT_MIN): restore
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R23}, .+4")  # restore+branch
    asm.append(f".{p}_r23_big:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T8}, .+4")  # T8 = 1
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_chk_small")
    
    # === SMALL OPERAND FAST PATH ===
    asm.append(f".{p}_chk_small:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T5}, .{p}_bit63")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T5}, .{p}_hi_zero")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T5}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_bit63")
    asm.append(f".{p}_hi_zero:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T5}, .+4")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T4}, .{p}_div_chk_32")
    # Cascade 8→16→24
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word   {const_from_pool(-257)}, {ADDR_T6}, .+4")
    asm.append(f"        .word   {ADDR_T4}, {ADDR_T6}, .{p}_chk_16bit")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_bit7")
    asm.append(f".{p}_chk_16bit:")
    asm.append(f"        .word   {const_from_pool(-65280)}, {ADDR_T6}, .{p}_chk_24bit")
    # Dividend 16-bit: check divisor lo >= 256
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
    
    # === ACCUMULATE-ONLY CHAINS (64-bit signed, small-operand path) ===
    # T3 = 0 in small-operand path, only T2 needs doubling. Extract from T4.
    def _emit_accum64s(prefix, exit_label, bit_hi, bit_lo):
        for i in range(bit_hi, bit_lo - 1, -1):
            threshold = 1 << i
            next_lbl = f".{p}_{prefix}_b{i-1}" if i > bit_lo else exit_label
            asm.append(f".{p}_{prefix}_b{i}:")
            if i == 31:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_T2}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {ADDR_T4}, {ADDR_Z}, .+4")
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
                asm.append(f"        .word   {ADDR_Z}, {ADDR_T2}, .+4")
                asm.append(f"        .word   {const_from_pool(threshold)}, {ADDR_T4}, .{p}_{prefix}_r{i}")
                asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T2}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl}")
                asm.append(f".{p}_{prefix}_r{i}:")
                asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_T4}, .+4")
                if i == bit_lo:
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl}")
    
    _emit_accum64s("acc16", f".{p}_bit7", 15, 8)
    _emit_accum64s("acc24", f".{p}_bit15", 23, 16)
    _emit_accum64s("acc32", f".{p}_bit23", 31, 24)
    
    # === MAIN DIVISION LOOP ===
    for i in range(63, -1, -1):
        next_label = f".{p}_bit{i-1}" if i > 0 else f".{p}_div_done"
        
        asm.append(f".{p}_bit{i}:")
        
        # === Step 1: Double 64-bit remainder T2:T3 (DIV-A) ===
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T2}, .{p}_{i}_t2_le0")
        # T2 > 0: no carry. Double T2 (Z-clean): T2,Z; Z,T2
        asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T2}, .+4")
        # Z dirty, clean and double T3
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T3}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_ex")
        
        asm.append(f".{p}_{i}_t2_le0:")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_T2}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_t2_ambig")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_dbl_carry")
        asm.append(f".{p}_{i}_t2_ambig:")
        asm.append(f"        .word   {ADDR_ONE}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_dbl_nocarry")
        
        asm.append(f".{p}_{i}_dbl_carry:")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T2}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T3}, .+4")
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T3}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_ex")
        
        asm.append(f".{p}_{i}_dbl_nocarry:")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T3}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_ex")
        
        # === Step 2: Extract bit[i] from dividend ===
        asm.append(f".{p}_{i}_ex:")
        if i >= 32:
            target_reg = ADDR_T5
            bit_idx = i - 32
        else:
            target_reg = ADDR_T4
            bit_idx = i
        
        if bit_idx == 31:
            # Bit 31: sign-check on biased value
            asm.append(f"        .word   {target_reg}, {ADDR_Z}, .+4")
            asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")
            asm.append(f"        .word   {ADDR_ONE}, {ADDR_T6}, .+4")
            asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_b31_le0")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_cmp")
            asm.append(f".{p}_{i}_b31_le0:")
            # T6 <= 0: combined restore+branch. T6+1<=0 -> T6 was negative -> bit 31 set
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T6}, .{p}_{i}_b31_neg_restore")  # T6+=1; if<=0 -> neg
            # T6 was 0: restore T6, bit NOT set -> cmp
            asm.append(f"        .word   {ADDR_ONE}, {ADDR_T6}, .{p}_{i}_cmp")  # restore+branch
            asm.append(f".{p}_{i}_b31_neg_restore:")
            # T6 was < 0 (including INT_MIN): restore T6
            asm.append(f"        .word   {ADDR_ONE}, {ADDR_T6}, .+4")  # restore+branch
            # Fall through to b31_set
            asm.append(f".{p}_{i}_b31_set:")
            threshold = 1 << 31
            asm.append(f"        .word   {const_from_pool(-2147483648)}, {target_reg}, .+4")
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T2}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_cmp")
        else:
            threshold = 1 << bit_idx
            asm.append(f"        .word   {const_from_pool(threshold)}, {target_reg}, .{p}_{i}_restore")
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T2}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_cmp")
            asm.append(f".{p}_{i}_restore:")
            asm.append(f"        .word   {const_from_pool(-threshold)}, {target_reg}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_cmp")
        
        # === Step 3: Compare T2:T3 >= R23:R24 ===
        # Hi words (T3, R24) are both positive after abs — simple signed compare.
        asm.append(f".{p}_{i}_cmp:")
        # Z-clear needed only for bit_idx==31 paths (bits 63,31) which have
        # a conditional predecessor subleq(ZERO,T7,_cmp) that doesn't clear Z.
        # All other bits arrive only via subleq(Z,Z,target) jumps (Z already clean).
        if bit_idx == 31:
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")      # T6 = T3
        asm.append(f"        .word   {ADDR_R24}, {ADDR_T6}, .+4")    # T6 = T3 - R24
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T7}, .{p}_{i}_hi_ge")  # T7<=0 → T6>=0 → T3>=R24
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")  # T3 < R24 → FALSE
        
        asm.append(f".{p}_{i}_hi_ge:")
        # T6 = T3-R24 (>=0). Check if equal (lo_cmp) or greater (sub).
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T6}, .+4")     # T6 = -T7 = T3-R24
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_lo_cmp")  # T6=0 → equal
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_sub")  # T3 > R24 → sub
        
        # === Lo-word compare (T2 vs R23, unsigned) with DIV-D ===
        asm.append(f".{p}_{i}_lo_cmp:")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T8}, .{p}_{i}_r23pos")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_r23big")
        
        asm.append(f".{p}_{i}_r23pos:")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")      # T6 = T2
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_t2le0")
        # T2 > 0, R23 > 0: signed compare
        asm.append(f"        .word   {ADDR_R23}, {ADDR_T6}, .+4")    # T6 = T2 - R23
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T7}, .{p}_{i}_sub")  # T7<=0 → T2>=R23 → sub
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
        
        asm.append(f".{p}_{i}_t2le0:")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T7}, .+4")      # T7 = T2
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T7}, .{p}_{i}_sub")  # T2<0 → large → sub
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R23}, .{p}_{i}_sub")  # R23=0 → 0>=0 → sub
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
        
        asm.append(f".{p}_{i}_r23big:")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")      # T6 = T2
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_lo_both_big")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")  # T2 small < R23 large
        
        asm.append(f".{p}_{i}_lo_both_big:")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T7}, .+4")      # T7 = T2
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T7}, .{p}_{i}_lo_signed")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")  # T2=0 < R23 large
        
        asm.append(f".{p}_{i}_lo_signed:")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_R23}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T7}, .{p}_{i}_sub")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
        
        # === Step 4: Subtract divisor, detect borrow, set quotient bit ===
        asm.append(f".{p}_{i}_sub:")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")      # T6 = old_T2
        asm.append(f"        .word   {ADDR_R23}, {ADDR_T2}, .+4")    # T2 -= R23
        asm.append(f"        .word   {ADDR_R24}, {ADDR_T3}, .+4")    # T3 -= R24
        
        # Borrow: old_T2 < R23 unsigned? Use DIV-D with T8.
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T8}, .{p}_{i}_br_r23pos")
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_br_both_big")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_do_borrow")
        
        asm.append(f".{p}_{i}_br_both_big:")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T7}, .{p}_{i}_br_signed")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_do_borrow")  # T6=0 < R23 large
        
        asm.append(f".{p}_{i}_br_signed:")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_R23}, {ADDR_T7}, .+4")    # T7 = T6 - R23
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T7}, .{p}_{i}_br_s_le0")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_setq")
        asm.append(f".{p}_{i}_br_s_le0:")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_setq")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_do_borrow")
        
        asm.append(f".{p}_{i}_br_r23pos:")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T7}, .+4")      # T7 = T6
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T7}, .{p}_{i}_br_t6le0")
        asm.append(f"        .word   {ADDR_R23}, {ADDR_T7}, .+4")    # T7 = T6 - R23
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T7}, .{p}_{i}_br_chk_strict")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_setq")
        
        asm.append(f".{p}_{i}_br_chk_strict:")
        asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T6}, .+4")
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .{p}_{i}_setq")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_do_borrow")
        
        asm.append(f".{p}_{i}_br_t6le0:")
        asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T7}, .+4")
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T7}, .{p}_{i}_setq")
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R23}, .{p}_{i}_setq")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .{p}_{i}_do_borrow")
        
        asm.append(f".{p}_{i}_do_borrow:")
        asm.append(f"        .word   {ADDR_ONE}, {ADDR_T3}, .+4")
        
        asm.append(f".{p}_{i}_setq:")
        if i >= 32:
            q_reg = ADDR_T1
            q_bit = i - 32
        else:
            q_reg = ADDR_T0
            q_bit = i
        val = 1 << q_bit
        asm.append(f"        .word   {const_from_pool(-val)}, {q_reg}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_label}")
    
    # === Division done, copy results and apply signs ===
    asm.append(".Lsd64v_div_done:")
    
    # Copy quotient (T0:T1) to R21:R22
    asm.append(f"        .word   {ADDR_R21}, {ADDR_R21}, .Lsd64v_r1")
    asm.append(".Lsd64v_r1:")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R21}, .+4")  # R21 = T0
    asm.append(f"        .word   {ADDR_R22}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T1}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R22}, .+4")  # R22 = T1
    
    # Copy remainder (T2:T3) to R23:R24
    asm.append(f"        .word   {ADDR_R23}, {ADDR_R23}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T2}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R23}, .+4")  # R23 = T2
    asm.append(f"        .word   {ADDR_R24}, {ADDR_R24}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R24}, .Lsd64v_chk_q_sign")  # R24 = T3
    
    # === Check if we need to negate quotient (T9 != 0) ===
    asm.append(".Lsd64v_chk_q_sign:")
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T9}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")  # T6 = T9
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .Lsd64v_chk_r_sign")
    # T9 > 0, negate quotient (R21:R22)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsd64v_neg_q")
    
    asm.append(".Lsd64v_neg_q:")
    # Negate R21:R22 (64-bit)
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .Lsd64v_nq1")
    asm.append(".Lsd64v_nq1:")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_T6}, .+4")  # T6 = -R21
    asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_T7}, .+4")  # T7 = -R22
    # Check borrow - need 3-step check for R21 != 0
    # Step 1: T8 = R21, check if <= 0
    asm.append(f"        .word   {ADDR_T8}, {ADDR_T8}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T8}, .+4")  # T8 = R21
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T8}, .Lsd64v_nq_step2")  # if R21 <= 0, go to step 2
    # R21 > 0, need borrow
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T7}, .Lsd64v_nq_noborrow")
    # Unconditional jump in case T7 > 0 after subtraction
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsd64v_nq_noborrow")
    
    # Step 2: Check if -R21 <= 0
    asm.append(".Lsd64v_nq_step2:")
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word   {ADDR_T8}, {ADDR_T5}, .+4")  # T5 = -T8 = -R21
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T5}, .Lsd64v_nq_step3")  # if -R21 <= 0, go to step 3
    # -R21 > 0, so R21 < 0, need borrow
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T7}, .Lsd64v_nq_noborrow")
    # Unconditional jump in case T7 > 0 after subtraction
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsd64v_nq_noborrow")
    
    # Step 3: R21 is 0 or 0x80000000
    asm.append(".Lsd64v_nq_step3:")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T8}, .+4")  # T8 = R21 - 1
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T8}, .Lsd64v_nq_noborrow")  # if R21-1 <= 0, R21 = 0, no borrow
    # R21 = 0x80000000, need borrow
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T7}, .Lsd64v_nq_noborrow")
    
    asm.append(".Lsd64v_nq_noborrow:")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T6}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T7}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R22}, .Lsd64v_chk_r_sign")
    
    # === Check if we need to negate remainder (T10 != 0) ===
    asm.append(".Lsd64v_chk_r_sign:")
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T10}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T6}, .+4")  # T6 = T10
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T6}, .Lsd64v_clean")
    # T10 > 0, negate remainder (R23:R24)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsd64v_neg_r")
    
    asm.append(".Lsd64v_neg_r:")
    # Negate R23:R24 (64-bit)
    asm.append(f"        .word   {ADDR_T6}, {ADDR_T6}, .Lsd64v_nr1")
    asm.append(".Lsd64v_nr1:")
    asm.append(f"        .word   {ADDR_R23}, {ADDR_T6}, .+4")  # T6 = -R23
    asm.append(f"        .word   {ADDR_T7}, {ADDR_T7}, .+4")
    asm.append(f"        .word   {ADDR_R24}, {ADDR_T7}, .+4")  # T7 = -R24
    # Check borrow - need 3-step check for R23 != 0
    # Step 1: T8 = R23, check if <= 0
    asm.append(f"        .word   {ADDR_T8}, {ADDR_T8}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R23}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T8}, .+4")  # T8 = R23
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T8}, .Lsd64v_nr_step2")  # if R23 <= 0, go to step 2
    # R23 > 0, need borrow
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T7}, .Lsd64v_nr_noborrow")
    # Unconditional jump in case T7 > 0 after subtraction
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsd64v_nr_noborrow")
    
    # Step 2: Check if -R23 <= 0
    asm.append(".Lsd64v_nr_step2:")
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word   {ADDR_T8}, {ADDR_T5}, .+4")  # T5 = -T8 = -R23
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T5}, .Lsd64v_nr_step3")  # if -R23 <= 0, go to step 3
    # -R23 > 0, so R23 < 0, need borrow
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T7}, .Lsd64v_nr_noborrow")
    # Unconditional jump in case T7 > 0 after subtraction
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsd64v_nr_noborrow")
    
    # Step 3: R23 is 0 or 0x80000000
    asm.append(".Lsd64v_nr_step3:")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T8}, .+4")  # T8 = R23 - 1
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T8}, .Lsd64v_nr_noborrow")  # if R23-1 <= 0, R23 = 0, no borrow
    # R23 = 0x80000000, need borrow
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T7}, .Lsd64v_nr_noborrow")
    
    asm.append(".Lsd64v_nr_noborrow:")
    asm.append(f"        .word   {ADDR_R23}, {ADDR_R23}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T6}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R23}, .+4")
    asm.append(f"        .word   {ADDR_R24}, {ADDR_R24}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T7}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R24}, .Lsd64v_clean")
    
    # No volatile register cleanup needed - caller saves volatile regs
    asm.append(".Lsd64v_clean:")
    
    # Return sequence
    asm.extend(emit_return_sequence("sd64v"))
    
    # Constants
    
    # Power of 2 constants for bit extraction (bits 0-30)
    # Negative power of 2 constants for quotient accumulation (bits 0-31)
    asm.append("")
    asm.append("        .size   __subleq_sdivrem64, . - __subleq_sdivrem64")
    
    return asm


if __name__ == "__main__":
    for line in emit_sdivrem_o64():
        print(line)
