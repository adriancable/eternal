#!/usr/bin/env python3
"""
Subleq runtime functions: memcpy, memset, memmove

Calling convention (C ABI):
- memcpy(dest, src, n):  R21=dest, R22=src, R23=n, returns dest in R20
- memset(dest, c, n):    R21=dest, R22=c, R23=n, returns dest in R20
- memmove(dest, src, n): R21=dest, R22=src, R23=n, returns dest in R20

memcpy is an alias for memmove since memmove handles non-overlapping correctly.
memset uses 3-phase algorithm: head (byte->align), body (word), tail (byte).
memmove chooses forward/backward copy based on dest vs src.
"""

from gen_runtime import (ADDR_Z, ADDR_SP, ADDR_RA, ADDR_ZERO, ADDR_R20, ADDR_R21, ADDR_R22, ADDR_R23, ADDR_T0, ADDR_T1, ADDR_T2, ADDR_T3, ADDR_T4, ADDR_T5, ADDR_T6, ADDR_T7, ADDR_T8, ADDR_T9, ADDR_T10, ADDR_T11, ADDR_T12, INDIRECT_FLAG, emit_return_sequence, emit_call_sequence, emit_call_sequence_naked, emit_push_ra, emit_pop_ra, const_from_pool, ADDR_ONE, ADDR_MINUS_ONE)


def emit_copy_z_dirty(asm, dest, src):
    """Emit register copy when Z state is unknown/dirty.
    
    4 instructions: Z=0, dest=0, Z=-src, dest=src
    Z is left dirty after this operation (contains -src).
    """
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")  # Z = 0
    asm.append(f"        .word {dest}, {dest}, .+4")      # dest = 0
    asm.append(f"        .word {src}, {ADDR_Z}, .+4")     # Z = -src
    asm.append(f"        .word {ADDR_Z}, {dest}, .+4")    # dest = -Z = src
    # Z is dirty (contains -src) - caller knows this


def emit_copy_z_clean(asm, dest, src):
    """Emit register copy when Z is known to be 0.
    
    3 instructions: dest=0, Z=-src, dest=src
    Z is left dirty after this operation.
    """
    asm.append(f"        .word {dest}, {dest}, .+4")      # dest = 0
    asm.append(f"        .word {src}, {ADDR_Z}, .+4")     # Z = -src
    asm.append(f"        .word {ADDR_Z}, {dest}, .+4")    # dest = -Z = src
    # Z is dirty


def emit_clear_z(asm):
    """Clear Z register. Only call when Z is needed clean for next op."""
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")


def emit_lattice_mod(asm, src_reg, result_reg, tmp_reg, prefix, constants_prefix):
    """Generate single-operand non-restoring lattice for computing src_reg & 3.
    
    This is an optimized replacement for the restoring loop pattern.
    Result is stored in result_reg.
    tmp_reg is used as an accumulator during the lattice (must be different from src_reg).
    
    The lattice uses constants with the given constants_prefix (e.g. ".Lmemmove_" for ".Lmemmove_pow1073741824").
    """
    # Sign Bit (clear if set)
    asm.append(f"{prefix}_sign:")
    asm.append(f"        .word {ADDR_ZERO}, {src_reg}, {prefix}_sign_neg")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_bias")
    
    asm.append(f"{prefix}_sign_neg:")
    # src <= 0: OPTIMIZED combined restore+branch on src_reg directly.
    # subleq(n1, src): src += 1; if src+1 <= 0 -> src was negative (including INT_MIN)
    asm.append(f"        .word {ADDR_MINUS_ONE}, {src_reg}, {prefix}_sign_neg_restore")  # src+=1; if<=0 -> negative
    # src was 0 (now 1): restore and skip to bias (no bit-31 set)
    asm.append(f"        .word {ADDR_ONE}, {src_reg}, {prefix}_bias")  # restore+branch
    
    asm.append(f"{prefix}_sign_neg_restore:")
    # src was < 0 (truly negative OR INT_MIN): restore src
    asm.append(f"        .word {ADDR_ONE}, {src_reg}, .+4")  # restore+branch
    # Clear bit 31 (works for both truly negative and INT_MIN)
    asm.append(f"        .word {const_from_pool(-2147483648)}, {src_reg}, .+4")
    
    # Bias
    asm.append(f"{prefix}_bias:")
    asm.append(f"        .word {tmp_reg}, {tmp_reg}, .+4")   # tmp = 0 (result accumulator)
    asm.append(f"        .word {ADDR_MINUS_ONE}, {src_reg}, .+4")   # src += 1 (bias)
    
    # Linearized single-operand lattice for src & 3
    # P→P fallthroughs for non-accumulating bits 30-2
    
    # === LINEAR P CHAIN: bits 30 down to 2 ===
    # Branch directly to N-state targets (no trampolines!)
    for bit in range(30, 2, -1):
        power = 1 << bit
        pow_label = f"{const_from_pool(power)}"
        next_N = f"{prefix}_b{bit-1}_N"
        asm.append(f"{prefix}_b{bit}_P:")
        asm.append(f"        .word {pow_label}, {src_reg}, {next_N}")
    
    asm.append(f"{prefix}_b2_P:")
    asm.append(f"        .word {const_from_pool(4)}, {src_reg}, {prefix}_b1_N")
    
    # === ACCUMULATING BITS 1-0 ===
    for bit in range(1, -1, -1):
        power = 1 << bit
        pow_label = f"{const_from_pool(power)}"
        npow_label = f"{const_from_pool(-power)}"
        
        if bit == 0:
            next_P = f"{prefix}_done"
            next_N = f"{prefix}_done"
        else:
            next_P = f"{prefix}_b{bit-1}_P"
            next_N = f"{prefix}_b{bit-1}_N"
        
        asm.append(f"{prefix}_b{bit}_P:")
        asm.append(f"        .word {pow_label}, {src_reg}, {next_N}")
        asm.append(f"        .word {pow_label}, {tmp_reg}, {next_P}")
        
        asm.append(f"{prefix}_b{bit}_N:")
        asm.append(f"        .word {npow_label}, {src_reg}, {next_N}")
        asm.append(f"        .word {pow_label}, {tmp_reg}, {next_P}")
    
    # === N STATES for bits 30-2 (P→N trampolines eliminated) ===
    for bit in range(30, 1, -1):
        power = 1 << bit
        npow_label = f"{const_from_pool(-power)}"
        
        if bit == 2:
            next_P = f"{prefix}_b1_P"
            next_N = f"{prefix}_b1_N"
        else:
            next_P = f"{prefix}_b{bit-1}_P"
            next_N = f"{prefix}_b{bit-1}_N"
        
        asm.append(f"{prefix}_b{bit}_N:")
        asm.append(f"        .word {npow_label}, {src_reg}, {next_N}")
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {next_P}")
    
    # Done: tmp holds negative result. Negate to result_reg.
    asm.append(f"{prefix}_done:")
    asm.append(f"        .word {result_reg}, {result_reg}, .+4")
    asm.append(f"        .word {tmp_reg}, {result_reg}, .+4")  # result = -tmp


def emit_inline_shl(asm, src_reg, dest_reg, shift_amount, prefix, z_clean=False):
    """Emit inline shift left by a fixed amount using doubling.
    
    x << shift_amount is achieved by doubling x shift_amount times.
    Each doubling: x = x - (-x) = 2x takes 4 subleq ops (need unconditional flow).
    
    Total: 4 * shift_amount ops
    - For shift=8: 32 ops
    - For shift=16: 64 ops
    - For shift=24: 96 ops
    
    This is MUCH faster than calling __subleq_shl (~400+ ops).
    z_clean: if True, Z is known to be 0 on entry (saves 1 op per copy).
    """
    copy_fn = emit_copy_z_clean if z_clean else emit_copy_z_dirty
    if shift_amount == 0:
        # Just copy
        copy_fn(asm, dest_reg, src_reg)
        return
    
    # Copy src to dest first if different
    if src_reg != dest_reg:
        copy_fn(asm, dest_reg, src_reg)
    
    # Double shift_amount times
    for i in range(shift_amount):
        asm.append(f"{prefix}_dbl{i}:")
        # dest = dest - (-dest) = 2*dest
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")          # Z = 0
        asm.append(f"        .word {dest_reg}, {ADDR_Z}, .+4")        # Z = -dest
        asm.append(f"        .word {ADDR_Z}, {dest_reg}, .+4")        # dest = dest + dest = 2*dest
        # Z is dirty after this, but next iteration clears it, and
        # the branch target (.+4) is always the fallthrough anyway.
    
    asm.append(f"{prefix}_done:")



def emit_inline_srl(asm, src_reg, dest_reg, shift_amount, prefix, constants_prefix, z_clean=False):
    """Emit inline logical shift right by a fixed amount.
    
    x >> shift_amount extracts bits [shift_amount, 31] and puts them in bits [0, 31-shift_amount].
    
    Algorithm: Use lattice extraction with special handling for bits 31 and 30 to avoid overflow.
    
    For srl 8:  Keep bits 8-31 (24 bits), store in bits 0-23 of result
    For srl 16: Keep bits 16-31 (16 bits), store in bits 0-15 of result
    For srl 24: Keep bits 24-31 (8 bits), store in bits 0-7 of result
    
    Uses T3 as working register, T4 as temp.
    z_clean: if True, Z is known to be 0 on entry (saves 1 op per copy).
    """
    # Copy src to T3 for extraction
    copy_fn = emit_copy_z_clean if z_clean else emit_copy_z_dirty
    copy_fn(asm, ADDR_T3, src_reg)
    
    # Initialize dest to 0
    asm.append(f"        .word {dest_reg}, {dest_reg}, .+4")
    
    # === Handle bit 31 specially (sign bit) ===
    # EDGE CASE: T3 = INT_MIN (-2147483648)
    #   -INT_MIN overflows to INT_MIN, so the naive "-T3 <= 0" check fails.
    #   Use T3 <= 0 && T3+1 <= 0 pattern (matches memset and SubleqAsmPrinter)
    asm.append(f"{prefix}_b31:")
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T3}, {prefix}_b31_check_neg")  # if T3 <= 0, check further
    # T3 > 0: bit 31 not set, skip to bit 30
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_b30_check")
    
    asm.append(f"{prefix}_b31_check_neg:")
    # T3 <= 0: Could be 0 or negative (including INT_MIN)
    # Check: T3 + 1 <= 0 means T3 <= -1, so T3 < 0 (bit 31 IS set)
    # Copy T3 to T4, add 1, check
    asm.append(f"        .word {ADDR_T4}, {ADDR_T4}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T3}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T4}, .+4")  # T4 = T3
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T4}, {prefix}_b31_set")  # T4 = T3 + 1; if <= 0, T3 < 0
    # T3 + 1 > 0: T3 = 0, bit 31 not set
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_b30_check")
    
    asm.append(f"{prefix}_b31_set:")
    # T3 < 0, bit 31 IS set
    if 31 >= shift_amount:
        result_bit = 31 - shift_amount
        result_power = 1 << result_bit
        asm.append(f"        .word {const_from_pool(-result_power)}, {dest_reg}, .+4")
    # Clear bit 31: T3 = T3 + 2^31
    asm.append(f"        .word {const_from_pool(-2147483648)}, {ADDR_T3}, .+4")
    
    # === Handle bit 30 specially (to avoid overflow when T3 = 0x7FFFFFFF) ===
    asm.append(f"{prefix}_b30_check:")
    # Check if T3 >= 2^30: compute T4 = 2^30 - T3 and check if <= 0
    asm.append(f"        .word {ADDR_T4}, {ADDR_T4}, .+4")
    asm.append(f"        .word {ADDR_T3}, {ADDR_T4}, .+4")  # T4 = -T3
    asm.append(f"        .word {const_from_pool(-1073741824)}, {ADDR_T4}, {prefix}_b30_set")  # T4 = -T3 + 2^30; if <= 0, T3 >= 2^30
    # T3 < 2^30, bit 30 NOT set
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_lattice_start")
    
    asm.append(f"{prefix}_b30_set:")
    # Bit 30 IS set
    if 30 >= shift_amount:
        result_bit = 30 - shift_amount
        result_power = 1 << result_bit
        asm.append(f"        .word {const_from_pool(-result_power)}, {dest_reg}, .+4")
    # Clear bit 30: T3 = T3 - 2^30
    asm.append(f"        .word {const_from_pool(1073741824)}, {ADDR_T3}, .+4")
    
    # === Now T3 is in range [0, 2^30 - 1], safe to apply bias ===
    asm.append(f"{prefix}_lattice_start:")
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T3}, .+4")  # Apply bias: T3 += 1
    
    # Lattice for bits 29 down to shift_amount
    for bit in range(29, shift_amount - 1, -1):
        power = 1 << bit
        result_bit = bit - shift_amount
        result_power = 1 << result_bit
        pow_label = f"{const_from_pool(power)}"
        npow_label = f"{const_from_pool(-power)}"
        
        if bit == shift_amount:
            next_P = f"{prefix}_done"
            next_N = f"{prefix}_done"
        else:
            next_P = f"{prefix}_b{bit-1}_P"
            next_N = f"{prefix}_b{bit-1}_N"
        
        if bit == shift_amount:
            # Last bit: next_N is _done; callers expect Z clean on exit, so keep trampoline
            asm.append(f"{prefix}_b{bit}_P:")
            asm.append(f"        .word {pow_label}, {ADDR_T3}, {prefix}_b{bit}_P_to_N")
            asm.append(f"        .word {const_from_pool(-result_power)}, {dest_reg}, .+4")
            asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {next_P}")
            asm.append(f"{prefix}_b{bit}_P_to_N:")
            asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {next_N}")
            asm.append(f"{prefix}_b{bit}_N:")
            asm.append(f"        .word {npow_label}, {ADDR_T3}, {prefix}_b{bit}_N_to_N")
            asm.append(f"        .word {const_from_pool(-result_power)}, {dest_reg}, .+4")
            asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {next_P}")
            asm.append(f"{prefix}_b{bit}_N_to_N:")
            asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {next_N}")
        else:
            # Non-last bit: interleaved P/N
            asm.append(f"{prefix}_b{bit}_P:")
            asm.append(f"        .word {pow_label}, {ADDR_T3}, {next_N}")
            asm.append(f"        .word {const_from_pool(-result_power)}, {dest_reg}, .+4")
            # INLINE next P's test+accumulate (replaces Z,Z,next_P)
            nb = bit - 1
            nb_power = 1 << nb
            nb_result_bit = nb - shift_amount
            nb_result_power = 1 << nb_result_bit
            if nb == shift_amount:
                # Next is last bit (trampoline pattern) — use its trampoline label
                asm.append(f"        .word {const_from_pool(nb_power)}, {ADDR_T3}, {prefix}_b{nb}_P_to_N")
            else:
                nb_next_N = f"{prefix}_b{nb-1}_N"
                asm.append(f"        .word {const_from_pool(nb_power)}, {ADDR_T3}, {nb_next_N}")
            asm.append(f"        .word {const_from_pool(-nb_result_power)}, {dest_reg}, .+4")
            if nb == shift_amount:
                asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_done")
            elif nb == shift_amount + 1:
                asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_b{nb-1}_P")
            else:
                nb_next_P = f"{prefix}_b{nb-1}_P"
                asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {nb_next_P}")
            
            asm.append(f"{prefix}_b{bit}_N:")
            asm.append(f"        .word {npow_label}, {ADDR_T3}, {next_N}")
            asm.append(f"        .word {const_from_pool(-result_power)}, {dest_reg}, .+4")
            # N falls through to next P — no Z,Z needed
            # (next label emitted is P_{bit-1})


    
    # After lattice, dest already contains the correct result (accumulated positive values)
    # No negation needed - the lattice accumulates: dest = dest - (-2^bit) = dest + 2^bit
    asm.append(f"{prefix}_done:")
    # Z may be dirty but callers handle it


def emit_fused_combine(asm, word0_reg, word1_reg, dest_reg, shift_amount, prefix, constants_prefix):
    """Fused combine: dest = (word0 >> shift) | (word1 << (32-shift))
    
    Single unified lattice approach: directly extracts all 32 result bits
    from their source positions in word0 and word1.
    
    - Result bits [0 .. 31-shift]: from word0 bits [shift .. 31]
    - Result bits [32-shift .. 31]: from word1 bits [0 .. shift-1]
    
    Works for shift_amount = 8, 16, or 24.
    Uses T3 as working register, T4 as temp, dest_reg for result accumulation.
    """
    inv_shift = 32 - shift_amount
    
    # Initialize dest to 0
    asm.append(f"        .word {dest_reg}, {dest_reg}, .+4")
    
    # === Word0 identity skip: if 0 < word0 < 2^shift, bits [shift..31] = 0 → skip Part 1 ===
    threshold_w0 = 1 << shift_amount  # e.g. shift=8: 256
    # Sign check: if word0 <= 0, bit 31 may be set → must do Part 1
    asm.append(f"        .word {ADDR_ZERO}, {word0_reg}, {prefix}_w0_do")  # if word0 <= 0, do Part 1
    # word0 > 0: safe to do magnitude check
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {word0_reg}, {ADDR_Z}, .+4")  # Z = -word0
    asm.append(f"        .word {const_from_pool(-threshold_w0)}, {ADDR_Z}, {prefix}_w0_do")  # if word0 >= threshold, do Part 1
    # word0 < threshold and word0 > 0: no contribution to result. Skip to Part 2.
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_word1_start")
    asm.append(f"{prefix}_w0_do:")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")  # clear Z
    
    # ============== PART 1: Extract word0 bits [shift..31] → result bits [0..inv_shift-1] ==============
    # Copy word0 to T3 for extraction (Z is clean from clear above)
    emit_copy_z_clean(asm, ADDR_T3, word0_reg)
    
    # Handle bit 31 of word0 → result bit (31 - shift_amount)
    # EDGE CASE: T3 = INT_MIN: -INT_MIN overflows. Use T3+1 <= 0 pattern.
    result_bit_31 = 31 - shift_amount
    result_power_31 = 1 << result_bit_31
    asm.append(f"{prefix}_w0_b31:")
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T3}, {prefix}_w0_b31_check_neg")  # if T3 <= 0
    # T3 > 0: bit 31 not set, skip to bit 30
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_w0_b30_check")
    
    asm.append(f"{prefix}_w0_b31_check_neg:")
    asm.append(f"        .word {ADDR_T4}, {ADDR_T4}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T3}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T4}, .+4")  # T4 = T3
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T4}, {prefix}_w0_b31_set")  # T4 = T3+1; if <= 0, T3 < 0
    # T3 = 0, bit 31 not set
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_w0_b30_check")
    
    asm.append(f"{prefix}_w0_b31_set:")
    # Bit 31 is set, accumulate 2^(31-shift) to result
    asm.append(f"        .word {const_from_pool(-result_power_31)}, {dest_reg}, .+4")
    # Clear bit 31: T3 += 2^31
    asm.append(f"        .word {const_from_pool(-2147483648)}, {ADDR_T3}, .+4")
    
    # Handle bit 30 of word0 → result bit (30 - shift_amount)
    result_bit_30 = 30 - shift_amount
    result_power_30 = 1 << result_bit_30
    asm.append(f"{prefix}_w0_b30_check:")
    asm.append(f"        .word {ADDR_T4}, {ADDR_T4}, .+4")
    asm.append(f"        .word {ADDR_T3}, {ADDR_T4}, .+4")  # T4 = -T3
    asm.append(f"        .word {const_from_pool(-1073741824)}, {ADDR_T4}, {prefix}_w0_b30_set")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_w0_lattice_start")
    
    asm.append(f"{prefix}_w0_b30_set:")
    asm.append(f"        .word {const_from_pool(-result_power_30)}, {dest_reg}, .+4")
    asm.append(f"        .word {const_from_pool(1073741824)}, {ADDR_T3}, .+4")  # Clear bit 30
    
    # Now T3 is in range [0, 2^30 - 1], safe to apply bias
    asm.append(f"{prefix}_w0_lattice_start:")
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T3}, .+4")  # Apply bias
    
    # Lattice for word0 bits 29 down to shift_amount → result bits (29-shift) down to 0
    for bit in range(29, shift_amount - 1, -1):
        power = 1 << bit
        result_bit = bit - shift_amount
        result_power = 1 << result_bit
        pow_label = f"{const_from_pool(power)}"
        npow_label = f"{const_from_pool(-power)}"
        result_npow_label = f"{const_from_pool(-result_power)}"
        
        next_P = f"{prefix}_w0_b{bit-1}_P" if bit > shift_amount else f"{prefix}_word1_start"
        next_N = f"{prefix}_w0_b{bit-1}_N" if bit > shift_amount else f"{prefix}_word1_start"
        
        if bit == shift_amount:
            # Last w0 bit: next_N is word1_start which calls emit_copy_z_clean — keep trampolines
            asm.append(f"{prefix}_w0_b{bit}_P:")
            asm.append(f"        .word {pow_label}, {ADDR_T3}, {prefix}_w0_b{bit}_P_to_N")
            asm.append(f"        .word {result_npow_label}, {dest_reg}, .+4")
            asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {next_P}")
            asm.append(f"{prefix}_w0_b{bit}_P_to_N:")
            asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {next_N}")
            asm.append(f"{prefix}_w0_b{bit}_N:")
            asm.append(f"        .word {npow_label}, {ADDR_T3}, {prefix}_w0_b{bit}_N_to_N")
            asm.append(f"        .word {result_npow_label}, {dest_reg}, .+4")
            asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {next_P}")
            asm.append(f"{prefix}_w0_b{bit}_N_to_N:")
            asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {next_N}")
        else:
            # Non-last w0 bit: interleaved P/N
            asm.append(f"{prefix}_w0_b{bit}_P:")
            asm.append(f"        .word {pow_label}, {ADDR_T3}, {next_N}")
            asm.append(f"        .word {result_npow_label}, {dest_reg}, .+4")
            # INLINE next P's test+accumulate
            nb = bit - 1
            nb_power = 1 << nb
            nb_result_bit = nb - shift_amount
            nb_result_power = 1 << nb_result_bit
            if nb == shift_amount:
                asm.append(f"        .word {const_from_pool(nb_power)}, {ADDR_T3}, {prefix}_w0_b{nb}_P_to_N")
            else:
                asm.append(f"        .word {const_from_pool(nb_power)}, {ADDR_T3}, {prefix}_w0_b{nb-1}_N")
            asm.append(f"        .word {const_from_pool(-nb_result_power)}, {dest_reg}, .+4")
            if nb == shift_amount:
                asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_word1_start")
            elif nb == shift_amount + 1:
                asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_w0_b{nb-1}_P")
            else:
                asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_w0_b{nb-1}_P")
            
            asm.append(f"{prefix}_w0_b{bit}_N:")
            asm.append(f"        .word {npow_label}, {ADDR_T3}, {next_N}")
            asm.append(f"        .word {result_npow_label}, {dest_reg}, .+4")
            # N falls through to next P
    
    # ============== PART 2: Extract word1 bits [0..shift-1] → result bits [inv_shift..31] ==============
    asm.append(f"{prefix}_word1_start:")
    # Z is clean (all paths arrive via Z,Z,<label> lattice exits)
    emit_copy_z_clean(asm, ADDR_T3, word1_reg)
    
    # Handle sign bit (bit 31) of word1 - just clear it, don't accumulate
    # EDGE CASE: T3 = INT_MIN: -INT_MIN overflows. Use T3+1 <= 0 pattern.
    asm.append(f"{prefix}_w1_b31:")
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T3}, {prefix}_w1_b31_check_neg")  # if T3 <= 0
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_w1_b30_check")
    
    asm.append(f"{prefix}_w1_b31_check_neg:")
    asm.append(f"        .word {ADDR_T4}, {ADDR_T4}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T3}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T4}, .+4")  # T4 = T3
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T4}, {prefix}_w1_b31_set")  # T4 = T3+1; if <= 0, T3 < 0
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_w1_b30_check")
    
    asm.append(f"{prefix}_w1_b31_set:")
    asm.append(f"        .word {const_from_pool(-2147483648)}, {ADDR_T3}, .+4")  # Clear bit 31
    
    # Handle bit 30 - just clear it, don't accumulate
    asm.append(f"{prefix}_w1_b30_check:")
    asm.append(f"        .word {ADDR_T4}, {ADDR_T4}, .+4")
    asm.append(f"        .word {ADDR_T3}, {ADDR_T4}, .+4")
    asm.append(f"        .word {const_from_pool(-1073741824)}, {ADDR_T4}, {prefix}_w1_b30_clear")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_w1_lattice_start")
    
    asm.append(f"{prefix}_w1_b30_clear:")
    asm.append(f"        .word {const_from_pool(1073741824)}, {ADDR_T3}, .+4")
    
    # Apply bias ONCE, then process ALL remaining bits (29-0) in one lattice
    asm.append(f"{prefix}_w1_lattice_start:")
    
    # === Magnitude skip: if T3 < 2^shift, skip non-accum P-chain ===
    threshold = 1 << shift_amount  # e.g. shift=8: 256
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")  # clear Z (may be dirty)
    asm.append(f"        .word {ADDR_T3}, {ADDR_Z}, .+4")  # Z = -T3
    asm.append(f"        .word {const_from_pool(-threshold)}, {ADDR_Z}, {prefix}_w1_full")  # if T3 >= threshold, full
    # T3 < threshold: bias + skip to first accum bit
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T3}, .+4")  # bias T3 += 1
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_w1_b{shift_amount-1}_P")  # clear Z + jump
    
    asm.append(f"{prefix}_w1_full:")
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T3}, .+4")  # bias T3 += 1
    
    # Single unified lattice for bits 29 down to 0  — LINEARIZED
    # - Bits 29 down to shift_amount: just navigate (don't accumulate) → LINEAR P CHAIN
    # - Bits (shift_amount-1) down to 0: extract and accumulate
    
    # === LINEAR P CHAIN: non-accumulating bits 29 down to shift_amount ===
    # Branch directly to N-state targets (no trampolines!)
    for bit in range(29, shift_amount - 1, -1):
        power = 1 << bit
        pow_label = f"{const_from_pool(power)}"
        if bit == shift_amount:
            next_N = f"{prefix}_w1_b{shift_amount-1}_N"
        else:
            next_N = f"{prefix}_w1_b{bit-1}_N"
        asm.append(f"{prefix}_w1_b{bit}_P:")
        asm.append(f"        .word {pow_label}, {ADDR_T3}, {next_N}")
    
    # === ACCUMULATING BITS (shift_amount-1) down to 0: interleaved P/N ===
    for bit in range(shift_amount - 1, -1, -1):
        power = 1 << bit
        pow_label = f"{const_from_pool(power)}"
        npow_label = f"{const_from_pool(-power)}"
        
        result_bit = bit + inv_shift
        result_power = 1 << result_bit
        if result_bit == 31:
            result_npow_label = const_from_pool(-2147483648)
        else:
            result_npow_label = f"{const_from_pool(-result_power)}"
        
        next_P = f"{prefix}_w1_b{bit-1}_P" if bit > 0 else f"{prefix}_done"
        next_N = f"{prefix}_w1_b{bit-1}_N" if bit > 0 else f"{prefix}_done"
        
        # Direct branch safe: _done has Z,Z,.+4 so Z-dirty there is fine
        asm.append(f"{prefix}_w1_b{bit}_P:")
        asm.append(f"        .word {pow_label}, {ADDR_T3}, {next_N}")
        asm.append(f"        .word {result_npow_label}, {dest_reg}, .+4")
        if bit > 0:
            # INLINE next P's test+accumulate
            nb = bit - 1
            nb_power = 1 << nb
            nb_result_bit = nb + inv_shift
            nb_result_power = 1 << nb_result_bit
            if nb_result_bit == 31:
                nb_result_npow = const_from_pool(-2147483648)
            else:
                nb_result_npow = f"{const_from_pool(-nb_result_power)}"
            nb_next_N = f"{prefix}_w1_b{nb-1}_N" if nb > 0 else f"{prefix}_done"
            nb_next_P = f"{prefix}_w1_b{nb-1}_P" if nb > 0 else f"{prefix}_done"
            asm.append(f"        .word {const_from_pool(nb_power)}, {ADDR_T3}, {nb_next_N}")
            asm.append(f"        .word {nb_result_npow}, {dest_reg}, .+4")
            asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {nb_next_P}")
        else:
            asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {next_P}")
        asm.append(f"{prefix}_w1_b{bit}_N:")
        asm.append(f"        .word {npow_label}, {ADDR_T3}, {next_N}")
        asm.append(f"        .word {result_npow_label}, {dest_reg}, .+4")
        # N falls through to next P (or _done for bit==0)
        if bit == 0:
            # Last N — need explicit jump to _done
            asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {next_P}")
    
    # === N STATES AND TRAMPOLINES for navigation bits 29 down to shift_amount ===
    for bit in range(29, shift_amount - 1, -1):
        power = 1 << bit
        npow_label = f"{const_from_pool(-power)}"
        
        if bit == shift_amount:
            next_P = f"{prefix}_w1_b{shift_amount-1}_P"
            next_N = f"{prefix}_w1_b{shift_amount-1}_N"
        else:
            next_P = f"{prefix}_w1_b{bit-1}_P"
            next_N = f"{prefix}_w1_b{bit-1}_N"
        
        # Navigation N state: direct branch safe (next_N is another lattice state, not _done)
        asm.append(f"{prefix}_w1_b{bit}_N:")
        asm.append(f"        .word {npow_label}, {ADDR_T3}, {next_N}")
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {next_P}")
    
    asm.append(f"{prefix}_done:")
    # Z already clean: all lattice exits arrive via subleq(Z,Z,target) jumps


def _emit_fwd_body_half(asm, shift_amount, prefix, constants_prefix,
                         word0_reg, load_reg, next_body_label, tail_label):
    """Emit one half of a 2x-unrolled forward body loop iteration.
    
    word0_reg: register holding the carry word from previous iteration
    load_reg: register to load the new word into
    next_body_label: label to jump to for the other half-iteration
    tail_label: label for n<4 exit
    """
    inv_shift = 32 - shift_amount
    
    asm.append(f"{prefix}_body:")
    # Check if n >= 4: destructive subtract 3, branch if R23 <= 0 (n < 4)
    # Saves 4 ops vs copy-to-T5 approach. Restore at tail trampoline.
    asm.append(f"        .word {const_from_pool(3)}, {ADDR_R23}, {tail_label}")
    
    # Load new word: load_reg = mem[aligned_src]
    asm.append(f"        .word {load_reg}, {load_reg}, .+4")
    asm.append(f"        .word {ADDR_T6 | INDIRECT_FLAG}, {load_reg}, .+4")
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {load_reg}, {ADDR_T5}, .+4")
    asm.append(f"        .word {load_reg}, {load_reg}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T5}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {load_reg}, .+4")  # load_reg = word (Z dirty)
    
    # ============================================================
    # ZERO FAST PATH: If both word0 and word1 are zero, the combined
    # result (word0 >> shift) | (word1 << inv_shift) is always zero
    # regardless of shift amount. Skip the 150-300 op combine entirely.
    # Cost: 1 op on hot path (word0 > 0 → fall through to combine)
    # ============================================================
    # Check word0_reg: if > 0, definitely non-zero → go to combine
    asm.append(f"        .word {ADDR_ZERO}, {word0_reg}, {prefix}_zchk_w0")
    
    if shift_amount == 8:
        # OPTIMIZED: For shift=8, fused combine handles dirty Z internally.
        # Hot path (word0 > 0) falls through directly to combine — saves 1 dead Z,Z jump.
        
        asm.append(f"{prefix}_combine:")
        emit_fused_combine(asm, word0_reg, load_reg, ADDR_T2, 8, f"{prefix}_fuse", constants_prefix)
        
        # Store combined to dst
        asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
        asm.append(f"        .word {ADDR_T2}, {ADDR_T5}, .+4")  # T5 = -combined
        asm.append(f"        .word {ADDR_T5}, {ADDR_R21 | INDIRECT_FLAG}, .+4")  # mem[dst] = combined
        
        # Advance: dst += 4, aligned_src += 4, n -= 4 (NO word copy needed!)
        asm.append(f"{prefix}_advance:")
        asm.append(f"        .word {const_from_pool(-4)}, {ADDR_T6}, .+4")
        asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R21}, .+4")
        asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .+4")  # R23 -= 1 (3 already subtracted at top)
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {next_body_label}")
        
        # --- COLD PATH: zero checks (relocated after advance for hot-path fall-through) ---
        asm.append(f"{prefix}_zchk_w0:")
        # word0 <= 0 (from prior check). Test word0+1 <= 0 → word0 < 0 (not zero).
        asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word {word0_reg}, {ADDR_Z}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")         # T5 = word0
        asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T5}, {prefix}_combine")  # T5 = word0+1; if <= 0 → not zero
        # word0+1 > 0 → word0 = 0
        asm.append(f"{prefix}_zchk_w1:")
        # word0 == 0. Now check load_reg (word1).
        asm.append(f"        .word {ADDR_ZERO}, {load_reg}, {prefix}_zchk_w1b")
        # word1 > 0: not zero
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_combine")
        asm.append(f"{prefix}_zchk_w1b:")
        # word1 <= 0. Test word1+1 <= 0 → word1 < 0 (not zero).
        asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word {load_reg}, {ADDR_Z}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")         # T5 = word1
        asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T5}, {prefix}_combine")  # T5 = word1+1; if <= 0 → not zero
        # word1+1 > 0 → word1 = 0
        asm.append(f"{prefix}_zero_store:")
        # Both words are zero! Just clear dest word and advance.
        asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_advance")
    else:
        # shift != 8: SRL needs Z clean, keep original layout
        # word0 > 0: not zero, go to normal combine
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_combine")
        asm.append(f"{prefix}_zchk_w0:")
        # word0 <= 0 (from prior check). Test word0+1 <= 0 → word0 < 0 (not zero).
        asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word {word0_reg}, {ADDR_Z}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")         # T5 = word0
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")           # Clean Z (needed: SRL uses z_clean=True)
        asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T5}, {prefix}_combine")  # T5 = word0+1; if <= 0 → not zero
        # word0+1 > 0 → word0 = 0
        asm.append(f"{prefix}_zchk_w1:")
        # word0 == 0. Now check load_reg (word1).
        asm.append(f"        .word {ADDR_ZERO}, {load_reg}, {prefix}_zchk_w1b")
        # word1 > 0: not zero
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_combine")
        asm.append(f"{prefix}_zchk_w1b:")
        # word1 <= 0. Test word1+1 <= 0 → word1 < 0 (not zero).
        asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word {load_reg}, {ADDR_Z}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")         # T5 = word1
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")           # Clean Z
        asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T5}, {prefix}_combine")  # T5 = word1+1; if <= 0 → not zero
        # word1+1 > 0 → word1 = 0
        asm.append(f"{prefix}_zero_store:")
        # Both words are zero! Just clear dest word and advance.
        asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_advance")
        
        asm.append(f"{prefix}_combine:")
        # Z clean at _combine: all predecessors arrive via subleq(Z,Z,target) jumps
        emit_inline_srl(asm, word0_reg, ADDR_T5, shift_amount, f"{prefix}_srl", constants_prefix, z_clean=True)
        emit_inline_shl(asm, load_reg, ADDR_T2, inv_shift, f"{prefix}_shl", z_clean=True)
        # Combine: T2 = T2 + T5 (disjoint bits)
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word {ADDR_T5}, {ADDR_Z}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_T2}, .+4")
        
        # Store combined to dst
        asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
        asm.append(f"        .word {ADDR_T2}, {ADDR_T5}, .+4")  # T5 = -combined
        asm.append(f"        .word {ADDR_T5}, {ADDR_R21 | INDIRECT_FLAG}, .+4")  # mem[dst] = combined
        
        # Advance: dst += 4, aligned_src += 4, n -= 4 (NO word copy needed!)
        asm.append(f"{prefix}_advance:")
        asm.append(f"        .word {const_from_pool(-4)}, {ADDR_T6}, .+4")
        asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R21}, .+4")
        asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .+4")  # R23 -= 1 (3 already subtracted at top)
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {next_body_label}")


def emit_unaligned_body_loop(asm, shift_amount, prefix, constants_prefix):
    """Generate a 2x-unrolled forward unaligned body loop for fixed shift amount.
    
    Uses register renaming: even iterations have word0 in T0 and load T1,
    odd iterations have word0 in T1 and load T0. This eliminates the
    4-op word0←word1 copy that was needed in the non-unrolled version.
    
    Registers used:
    - T0/T1: alternating word0/word1 roles
    - T6: aligned_src pointer
    - R21: dest pointer
    - R23: n (remaining bytes)
    
    shift_amount: 8, 16, or 24 (for src & 3 = 1, 2, or 3)
    """
    # Tail trampoline: restore R23 after destructive count check, then enter tail
    tail_restore = f"{prefix}_tail_restore"
    tail = ".Lmemmove_fwd_slow_loop"
    # Even half: word0=T0, load into T1, then jump to odd
    _emit_fwd_body_half(asm, shift_amount, f"{prefix}_e", constants_prefix,
                        ADDR_T0, ADDR_T1, f"{prefix}_o_body", tail_restore)
    # Odd half: word0=T1, load into T0, then jump back to even
    _emit_fwd_body_half(asm, shift_amount, f"{prefix}_o", constants_prefix,
                        ADDR_T1, ADDR_T0, f"{prefix}_e_body", tail_restore)
    # Restore trampoline: R23 had 3 subtracted by last count check, restore before tail
    asm.append(f"{tail_restore}:")
    asm.append(f"        .word {const_from_pool(-3)}, {ADDR_R23}, .+4")  # R23 += 3
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {tail}")


def _emit_bwd_body_half(asm, shift_amount, prefix, constants_prefix,
                         word0_reg, load_reg, next_body_label, tail_label):
    """Emit one half of a 2x-unrolled backward body loop iteration.
    
    word0_reg: register holding WordHigh (carry from previous iteration)
    load_reg: register to load WordLow into
    next_body_label: label for the other half-iteration
    tail_label: label for n<4 exit
    
    Backward combine: (WordLow >> shift) | (WordHigh << inv_shift)
    So load_reg (WordLow) goes to SRL, word0_reg (WordHigh) goes to SHL.
    """
    inv_shift = 32 - shift_amount
    
    asm.append(f"{prefix}_body:")
    # Check if n >= 4: destructive subtract 3, branch if R23 <= 0 (n < 4)
    # Saves 4 ops vs copy-to-T5 approach. Restore at tail trampoline.
    asm.append(f"        .word {const_from_pool(3)}, {ADDR_R23}, {tail_label}")
    
    # Load WordLow: load_reg = mem[T6] (T6 points to current position)
    asm.append(f"        .word {load_reg}, {load_reg}, .+4")
    asm.append(f"        .word {ADDR_T6 | INDIRECT_FLAG}, {load_reg}, .+4")
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {load_reg}, {ADDR_T5}, .+4")
    asm.append(f"        .word {load_reg}, {load_reg}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T5}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {load_reg}, .+4")  # load_reg = WordLow (Z dirty)
    
    # ============================================================
    # ZERO FAST PATH: If both WordHigh and WordLow are zero, the combined
    # result (WordLow >> shift) | (WordHigh << inv_shift) is always zero
    # regardless of shift amount. Skip the 150-300 op combine entirely.
    # Cost: 1 op on hot path (word0 > 0 → fall through to combine)
    # ============================================================
    # Check word0_reg (WordHigh): if > 0, definitely non-zero → go to combine
    asm.append(f"        .word {ADDR_ZERO}, {word0_reg}, {prefix}_zchk_w0")
    
    if shift_amount == 8:
        # OPTIMIZED: For shift=8, fused combine handles dirty Z internally.
        # Hot path (word0 > 0) falls through directly to combine.
        
        asm.append(f"{prefix}_combine:")
        emit_fused_combine(asm, load_reg, word0_reg, ADDR_T5, 8, f"{prefix}_fuse", constants_prefix)
        
        # Store word to dest
        asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        asm.append(f"        .word {ADDR_T2}, {ADDR_T2}, .+4")
        asm.append(f"        .word {ADDR_T5}, {ADDR_T2}, .+4")  # T2 = -combined
        asm.append(f"        .word {ADDR_T2}, {ADDR_R21 | INDIRECT_FLAG}, .+4")  # mem[dest] = combined
        
        # Advance: T6 -= 4, R21 -= 4, R23 -= 4
        asm.append(f"{prefix}_advance:")
        asm.append(f"        .word {const_from_pool(4)}, {ADDR_T6}, .+4")
        asm.append(f"        .word {const_from_pool(4)}, {ADDR_R21}, .+4")
        asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .+4")  # R23 -= 1 (3 already subtracted at top)
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {next_body_label}")
        
        # --- COLD PATH: zero checks (relocated after advance) ---
        asm.append(f"{prefix}_zchk_w0:")
        asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word {word0_reg}, {ADDR_Z}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")         # T5 = word0
        asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T5}, {prefix}_combine")
        asm.append(f"{prefix}_zchk_w1:")
        asm.append(f"        .word {ADDR_ZERO}, {load_reg}, {prefix}_zchk_w1b")
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_combine")
        asm.append(f"{prefix}_zchk_w1b:")
        asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word {load_reg}, {ADDR_Z}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")         # T5 = word1
        asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T5}, {prefix}_combine")
        asm.append(f"{prefix}_zero_store:")
        asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_advance")
    else:
        # shift != 8: keep original layout
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_combine")
        asm.append(f"{prefix}_zchk_w0:")
        asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word {word0_reg}, {ADDR_Z}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")         # T5 = word0
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")           # Clean Z
        asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T5}, {prefix}_combine")
        asm.append(f"{prefix}_zchk_w1:")
        asm.append(f"        .word {ADDR_ZERO}, {load_reg}, {prefix}_zchk_w1b")
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_combine")
        asm.append(f"{prefix}_zchk_w1b:")
        asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word {load_reg}, {ADDR_Z}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")         # T5 = word1
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")           # Clean Z
        asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T5}, {prefix}_combine")
        asm.append(f"{prefix}_zero_store:")
        asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {prefix}_advance")
        
        asm.append(f"{prefix}_combine:")
        if shift_amount == 32:
            emit_copy_z_clean(asm, ADDR_T5, word0_reg)
        else:
            # Z clean at _combine: all predecessors arrive via subleq(Z,Z,target) jumps
            emit_inline_shl(asm, word0_reg, ADDR_T7, inv_shift, f"{prefix}_shl", z_clean=True)
            emit_inline_srl(asm, load_reg, ADDR_T5, shift_amount, f"{prefix}_srl", constants_prefix)
            # Combine: T5 = T5 + T7 (disjoint bits)
            asm.append(f"        .word {ADDR_T7}, {ADDR_Z}, .+4")
            asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")
        
        # Store word to dest
        asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        asm.append(f"        .word {ADDR_T2}, {ADDR_T2}, .+4")
        asm.append(f"        .word {ADDR_T5}, {ADDR_T2}, .+4")  # T2 = -combined
        asm.append(f"        .word {ADDR_T2}, {ADDR_R21 | INDIRECT_FLAG}, .+4")  # mem[dest] = combined
        
        # Advance: T6 -= 4, R21 -= 4, R23 -= 4
        asm.append(f"{prefix}_advance:")
        asm.append(f"        .word {const_from_pool(4)}, {ADDR_T6}, .+4")
        asm.append(f"        .word {const_from_pool(4)}, {ADDR_R21}, .+4")
        asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .+4")  # R23 -= 1 (3 already subtracted at top)
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {next_body_label}")


def emit_backward_unaligned_body_loop(asm, shift_amount, prefix, constants_prefix):
    """Generate a 2x-unrolled backward unaligned body loop for fixed shift amount.
    
    Uses register renaming: even iterations have WordHigh in T0 and load T1,
    odd iterations have WordHigh in T1 and load T0. This eliminates the
    4-op word0←word1 copy.
    
    Registers used:
    - T0/T1: alternating WordHigh/WordLow roles
    - T6: aligned_src pointer (decrements)
    - R21: dest pointer (decrements)
    - R23: n (remaining bytes)
    
    shift_amount: 8, 16, or 24 (for (src & 3) + 1 = 1, 2, or 3)
    """
    # Tail trampoline: restore R23 after destructive count check, then enter tail
    tail_restore = f"{prefix}_tail_restore"
    tail = ".Lmemmove_bwd_tail"
    # Even half: WordHigh=T0, load WordLow=T1
    _emit_bwd_body_half(asm, shift_amount, f"{prefix}_e", constants_prefix,
                        ADDR_T0, ADDR_T1, f"{prefix}_o_body", tail_restore)
    # Odd half: WordHigh=T1, load WordLow=T0
    _emit_bwd_body_half(asm, shift_amount, f"{prefix}_o", constants_prefix,
                        ADDR_T1, ADDR_T0, f"{prefix}_e_body", tail_restore)
    # Restore trampoline: R23 had 3 subtracted by last count check, restore before tail
    asm.append(f"{tail_restore}:")
    asm.append(f"        .word {const_from_pool(-3)}, {ADDR_R23}, .+4")  # R23 += 3
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {tail}")


def emit_memcpy():
    """Generate __subleq_memcpy as a jump to __subleq_memmove."""
    asm = []
    asm.append("")
    asm.append("        .globl  __subleq_memcpy")  
    asm.append("        .type   __subleq_memcpy,@function")
    asm.append("# __subleq_memcpy(dest=R21, src=R22, n=R23) returns R20=dest")
    asm.append("# Implemented as alias to __subleq_memmove")
    asm.append("__subleq_memcpy:")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, __subleq_memmove")
    asm.append("")
    asm.append("        .size __subleq_memcpy, . - __subleq_memcpy")
    return asm


def emit_memset():
    """Generate optimized memset using 3-phase algorithm.
    
    void *memset(void *dest, int c, size_t n)
    Input: R21=dest, R22=c, R23=n
    Output: R20=dest
    
    Algorithm:
    1. Head: Set unaligned bytes until dest is word-aligned (0-3 bytes, slow)
    2. Body: Set aligned words using direct Subleq (n/4 words, fast)
    3. Tail: Set remaining bytes (0-3 bytes, slow)
    
    OPTIMIZATIONS APPLIED:
    1. Inline byte masking (c & 0xFF) - saves ~300 ops vs __subleq_and call
    2. Inline alignment check (dest & 3) - saves ~300 ops per head iteration
    3. Uses combined subtract-and-test for bit clearing
    """
    asm = []
    asm.append("")
    asm.append("        .globl  __subleq_memset")
    asm.append("        .type   __subleq_memset,@function")
    asm.append("# __subleq_memset(dest=R21, c=R22, n=R23) returns R20=dest")
    asm.append("# OPTIMIZED: Inline byte masking and alignment checks")
    asm.append("__subleq_memset:")
    emit_push_ra(asm)
    
    # Save dest to R20 for return value and T10 (survives all calls)
    # MEM-E: Reuse Z = -R21 from R20 copy to set T10 in 2 insn instead of 6
    emit_copy_z_dirty(asm, ADDR_R20, ADDR_R21)  # R20 = dest (4 insn), Z = -R21
    asm.append(f"        .word {ADDR_T10}, {ADDR_T10}, .+4")    # T10 = 0
    asm.append(f"        .word {ADDR_Z}, {ADDR_T10}, .+4")      # T10 -= Z = R21
    # Z is dirty here but will be cleared before next use
    
    # Check if n <= 0, done immediately (Z dead — next use overwrites)
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lmemset_done")
    
    # ============================================================
    # FAST ZERO PATH: If c == 0, skip masking and pattern computation
    # This is the most common case (clear_page, BSS init, etc.)
    # Check: c <= 0 AND -c <= 0 means c == 0
    # ============================================================
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R22}, .Lmemset_check_zero")
    # c > 0: fall through to normal path
    # OPTIMIZED: Fuse T5 clear into jump
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .Lmemset_normal_path_start")
    asm.append(".Lmemset_check_zero:")
    # c <= 0: check if c == 0 by testing -c <= 0
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {ADDR_R22}, {ADDR_T5}, .Lmemset_fast_zero_head")  # T5 = -c
    # -c > 0 means c < 0, so c != 0, use normal path
    # OPTIMIZED: Fuse T5 clear into jump
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .Lmemset_normal_path_start")
    
    asm.append(".Lmemset_normal_path_start:")
    # NOTE: Callers now jump here with T5 already cleared via fused clear
    # ============================================================
    # INLINE byte masking: R22 = R22 & 0xFF
    # OPTIMIZED: O(24) inline instead of __subleq_and call (~300 ops)
    # Uses combined subtract-and-test pattern
    # ============================================================
    # Handle sign bit first
    # EDGE CASE: R22 = INT_MIN (-2147483648)
    #   The naive pattern: T5 = -R22, branch if T5 <= 0
    #   Fails because -INT_MIN = INT_MIN (overflow), so T5 <= 0, incorrectly skipping!
    # FIX: Use R22+1 <= 0 pattern (like SubleqAsmPrinter.cpp):
    #   1. Check R22 <= 0 first. If R22 > 0, skip (bit 31 not set)
    #   2. If R22 <= 0, check R22 + 1 <= 0:
    #      - R22 + 1 <= 0 means R22 <= -1, so R22 < 0 (negative, clear bit 31)
    #      - R22 + 1 > 0 means R22 > -1, combined with R22 <= 0, so R22 = 0 (skip)
    # T5 is already cleared by all callers (fused T5,T5,<label> jumps)
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R22}, .Lmemset_mask_chk31")  # branch if R22 <= 0
    # R22 > 0: bit 31 not set, skip to bit 30
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemset_mask_b30")
    asm.append(f".Lmemset_mask_chk31:")
    # R22 <= 0: disambiguate R22 = 0 from R22 < 0 using R22 + 1
    # Copy R22 to T5, add 1, check if <= 0
    # MEM-A: Removed wasted T5 -= R22 (result immediately clobbered by T5 self-clear)
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")          # T5 = 0
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")            # Z = 0
    asm.append(f"        .word {ADDR_R22}, {ADDR_Z}, .+4")          # Z = -R22
    asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")           # T5 = R22
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T5}, .+4")      # T5 = R22 + 1
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T5}, .Lmemset_mask_clr31")  # branch if R22 + 1 <= 0 (R22 < 0)
    # R22 + 1 > 0: R22 = 0, skip to bit 30
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemset_mask_b30")
    asm.append(f".Lmemset_mask_clr31:")
    # R22 < 0: clear bit 31 by subtracting INT_MIN
    asm.append(f"        .word {const_from_pool(-2147483648)}, {ADDR_R22}, .Lmemset_mask_b30")
    
    # Clear bits 30 down to 8 using combined subtract-and-test
    for bit in range(30, 7, -1):
        threshold = 1 << bit
        next_label = f".Lmemset_mask_b{bit-1}" if bit > 8 else ".Lmemset_mask_done"
        asm.append(f".Lmemset_mask_b{bit}:")
        asm.append(f"        .word {const_from_pool(threshold)}, {ADDR_R22}, .Lmemset_mask_chk{bit}")
        # R22 > 0: bit was set (already cleared), continue
        asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, {next_label}")
        asm.append(f".Lmemset_mask_chk{bit}:")
        # R22 <= 0: disambiguate R22=0 (exactly set) vs R22<0 (not set)
        asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
        asm.append(f"        .word {ADDR_R22}, {ADDR_T5}, {next_label}")  # T5 = -R22
        # R22 < 0: restore
        asm.append(f"        .word {const_from_pool(-threshold)}, {ADDR_R22}, {next_label}")
    
    asm.append(".Lmemset_mask_done:")
    # R22 now contains c & 0xFF
    # ============================================================
    # PHASE 1: HEAD - Set bytes until dest is word-aligned
    # OPTIMIZED: Unrolled split-entry sb_bN. Computes dest & 3 once,
    # then dispatches to sb_b1→sb_b2→sb_b3 with fallthrough.
    # Saves ~79 ops per head byte vs old loop (no per-iteration
    # lattice_mod, no internal modulo in sb).
    # ============================================================
    asm.append(".Lmemset_head:")
    # Check if n <= 0
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lmemset_done")
    
    # INLINE alignment check: compute dest & 3
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")  # T5 = dest
    
    # Compute dest & 3 using optimized lattice
    emit_lattice_mod(asm, ADDR_T5, ADDR_T5, ADDR_T6, ".Lmemset_align", ".Lmemset_")
    # T5 = dest & 3; if T5 <= 0 (== 0), dest already aligned → body
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T5}, .Lmemset_body_setup")
    
    # T5 = offset ∈ {1, 2, 3}. Compute word-aligned base:
    # T8 = R21 - T5 (word-aligned base address for sb_bN calls)
    emit_copy_z_dirty(asm, ADDR_T8, ADDR_R21)
    asm.append(f"        .word {ADDR_T5}, {ADDR_T8}, .+4")  # T8 = dest - offset = word base
    
    # Save c for restoration between calls
    emit_copy_z_dirty(asm, ADDR_T9, ADDR_R22)  # T9 = c
    
    # Dispatch on T5: 1→head_b1, 2→head_b2, 3→head_b3
    # Use scratch T6 to test T5 without clobbering it
    asm.append(f"        .word {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T5}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T6}, .+4")  # T6 = T5
    asm.append(f"        .word {const_from_pool(2)}, {ADDR_T6}, .Lmemset_head_chk12")
    # T5 > 2: T5 = 3 → need 1 byte (b3 only)
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemset_head_b3")
    
    asm.append(".Lmemset_head_chk12:")
    # T6 = T5 - 2. If T5=1, T6=-1; if T5=2, T6=0
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T6}, .Lmemset_head_b1")  # T6+=1; if <=0, T5 was 1
    # T5 = 2 → need 2 bytes (b2, b3)
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemset_head_b2")
    
    # --- Byte at offset 1: sb_b1(word_base, c) ---
    asm.append(".Lmemset_head_b1:")
    # R21 = word base (T8), R22 = c (already set or restored)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    emit_call_sequence(asm, ".Lmemset_head_sb1_ret", "__subleq_sb_b1")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_T9)  # restore c
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemset_done")  # n--; if n==0, all done
    
    # --- Byte at offset 2: sb_b2(word_base, c) ---
    asm.append(".Lmemset_head_b2:")
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    emit_call_sequence(asm, ".Lmemset_head_sb2_ret", "__subleq_sb_b2")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_T9)  # restore c
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemset_done")  # n--; if n==0, all done
    
    # --- Byte at offset 3: sb_b3(word_base, c) ---
    asm.append(".Lmemset_head_b3:")
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    emit_call_sequence(asm, ".Lmemset_head_sb3_ret", "__subleq_sb_b3")
    
    # Head complete: dest is now word-aligned.
    # R21 = T8 + 4 = next word-aligned address
    asm.append(".Lmemset_head_done:")
    emit_copy_z_clean(asm, ADDR_R21, ADDR_T8)
    asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R21}, .+4")  # R21 = word_base + 4
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T9)  # restore c
    # Subtract bytes we wrote from n: we wrote (4 - offset) bytes,
    # but we already decremented n by 1 for each sb_b1/sb_b2 above.
    # The last sb_b3 didn't decrement, so decrement now.
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .+4")
    
    # ============================================================
    # PHASE 2: BODY - Set aligned words directly (very fast)
    # Now dest is word-aligned. Copy words while n >= 4.
    # ============================================================
    asm.append(".Lmemset_body_setup:")
    
    # ============================================================
    # First, calculate T7 = n >> 2 (divide by 4) = word count
    # INLINE SRL: n >> 2 using lattice extraction
    # SRL only uses T3/T4 internally, R21/R22/R23 are NOT modified
    # ============================================================
    emit_inline_srl(asm, ADDR_R23, ADDR_T7, 2, ".Lmemset_srl", ".Lmemset_")
    # T7 = word count directly (no intermediate copy needed)
    
    # ============================================================
    # INLINE byte broadcast: T1 = c * 0x01010101
    # c is in R22 (already masked to 8 bits)
    # Algorithm: T1 = c, T2 = c<<8, T1 += T2, T2 = T1<<16, T1 += T2
    # ~38 ops inline vs ~300+ ops for __subleq_mul call
    # ============================================================
    # Step 1: T1 = c (from R22) — Z is clean from srl_done
    emit_copy_z_clean(asm, ADDR_T1, ADDR_R22)  # T1 = c (3 ops)
    # Step 2: T2 = c << 8 (copy R22->T2 then 8 doublings)
    emit_inline_shl(asm, ADDR_R22, ADDR_T2, 8, ".Lmemset_pat_shl8")  # T2 = c<<8 (12 ops)
    # Step 3: T1 += T2 → T1 = c | (c<<8)
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T2}, {ADDR_Z}, .+4")   # Z = -T2
    asm.append(f"        .word {ADDR_Z}, {ADDR_T1}, .+4")   # T1 += T2
    # Step 4: T2 = T1 << 16 (copy T1->T2 then 16 doublings)
    emit_inline_shl(asm, ADDR_T1, ADDR_T2, 16, ".Lmemset_pat_shl16")  # T2 = T1<<16 (20 ops)
    # Step 5: T1 += T2 → T1 = c | (c<<8) | (c<<16) | (c<<24)
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T2}, {ADDR_Z}, .+4")   # Z = -T2
    asm.append(f"        .word {ADDR_Z}, {ADDR_T1}, .+4")   # T1 = full pattern
    # T0 = -pattern (precomputed for body loop store)
    asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word {ADDR_T1}, {ADDR_T0}, .+4")  # T0 = -pattern
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemset_body_loop")
    
    # Body loop: OPTIMIZED speculative T7 -= 16
    asm.append(".Lmemset_body_loop:")
    asm.append(f"        .word {const_from_pool(16)}, {ADDR_T7}, .Lmemset_body_fixup")
    
    # T7 >= 1: safe to store 16 words
    for _ in range(16):
        # Mem[R21] = pattern
        asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        asm.append(f"        .word {ADDR_T0}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R21}, .+4") # R21 += 4
        
    # n -= 64
    asm.append(f"        .word {const_from_pool(64)}, {ADDR_R23}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemset_body_loop")
    
    # Fixup: T7 went <= 0, add 16 back
    asm.append(".Lmemset_body_fixup:")
    asm.append(f"        .word {const_from_pool(-16)}, {ADDR_T7}, .+4")
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T7}, .Lmemset_tail_setup")

    asm.append(".Lmemset_body_single:")
    # One word store
    asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
    asm.append(f"        .word {ADDR_T0}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
    asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R21}, .+4")
    asm.append(f"        .word {const_from_pool(4)}, {ADDR_R23}, .+4")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_T7}, .Lmemset_tail_setup")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemset_body_single")
    
    # ============================================================
    # PHASE 3: TAIL - Set remaining bytes (0-3)
    # Two-entry-point loop: first entry sets RA, loop-back skips RA setup
    # ============================================================
    asm.append(".Lmemset_tail_setup:")
    # OPTIMIZED: After body, dest is word-aligned. Remaining bytes
    # are at offsets 0, 1, 2. Unroll with split-entry sb_bN.
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lmemset_done")
    
    # --- Byte 0: sb_b0(dest, c) ---
    emit_copy_z_dirty(asm, ADDR_T8, ADDR_R21)  # T8 = dest (word-aligned)
    emit_copy_z_dirty(asm, ADDR_T9, ADDR_R22)  # T9 = c
    emit_call_sequence(asm, ".Lmemset_tail_sb0_ret", "__subleq_sb_b0")
    emit_copy_z_clean(asm, ADDR_R21, ADDR_T8)
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T9)
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemset_done")
    
    # --- Byte 1: sb_b1(dest, c) ---
    emit_copy_z_dirty(asm, ADDR_T9, ADDR_R22)
    emit_call_sequence(asm, ".Lmemset_tail_sb1_ret", "__subleq_sb_b1")
    emit_copy_z_clean(asm, ADDR_R21, ADDR_T8)
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T9)
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemset_done")
    
    # --- Byte 2: sb_b2(dest, c) ---
    emit_copy_z_dirty(asm, ADDR_T9, ADDR_R22)
    emit_call_sequence(asm, ".Lmemset_tail_sb2_ret", "__subleq_sb_b2")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemset_done")
    
    # ============================================================
    # FAST ZERO PATH: c == 0, skip masking and pattern computation
    # This is ~600+ ops faster than normal path for memset(x, 0, n)
    # ============================================================
    asm.append(".Lmemset_fast_zero_head:")
    # OPTIMIZED: Unrolled split-entry sb_bN (same as normal head).
    # c == 0, so no need to save/restore R22.
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lmemset_done")
    
    # INLINE alignment check: compute dest & 3
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")  # T5 = dest
    
    # Compute dest & 3 using optimized lattice
    emit_lattice_mod(asm, ADDR_T5, ADDR_T5, ADDR_T6, ".Lmemset_fz_align", ".Lmemset_")
    # T5 = dest & 3; if T5 <= 0 (== 0), dest already aligned → body
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T5}, .Lmemset_fz_body_setup")
    
    # T5 = offset ∈ {1, 2, 3}. Compute word-aligned base:
    # T8 = R21 - T5 (word-aligned base address for sb_bN calls)
    emit_copy_z_dirty(asm, ADDR_T8, ADDR_R21)
    asm.append(f"        .word {ADDR_T5}, {ADDR_T8}, .+4")  # T8 = dest - offset = word base
    
    # Dispatch on T5: 1→head_b1, 2→head_b2, 3→head_b3
    asm.append(f"        .word {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T5}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T6}, .+4")  # T6 = T5
    asm.append(f"        .word {const_from_pool(2)}, {ADDR_T6}, .Lmemset_fz_head_chk12")
    # T5 > 2: T5 = 3 → need 1 byte (b3 only)
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemset_fz_head_b3")
    
    asm.append(".Lmemset_fz_head_chk12:")
    # T6 = T5 - 2. If T5=1, T6=-1; if T5=2, T6=0
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T6}, .Lmemset_fz_head_b1")  # T6+=1; if <=0, T5 was 1
    # T5 = 2 → need 2 bytes (b2, b3)
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemset_fz_head_b2")
    
    # --- Byte at offset 1: sb_b1(word_base, 0) ---
    asm.append(".Lmemset_fz_head_b1:")
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    asm.append(f"        .word {ADDR_R22}, {ADDR_R22}, .+4")  # R22 = 0
    emit_call_sequence(asm, ".Lmemset_fz_head_sb1_ret", "__subleq_sb_b1")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemset_done")  # n--; if n==0, all done
    
    # --- Byte at offset 2: sb_b2(word_base, 0) ---
    asm.append(".Lmemset_fz_head_b2:")
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    asm.append(f"        .word {ADDR_R22}, {ADDR_R22}, .+4")  # R22 = 0
    emit_call_sequence(asm, ".Lmemset_fz_head_sb2_ret", "__subleq_sb_b2")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemset_done")  # n--; if n==0, all done
    
    # --- Byte at offset 3: sb_b3(word_base, 0) ---
    asm.append(".Lmemset_fz_head_b3:")
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    asm.append(f"        .word {ADDR_R22}, {ADDR_R22}, .+4")  # R22 = 0
    emit_call_sequence(asm, ".Lmemset_fz_head_sb3_ret", "__subleq_sb_b3")
    
    # Head complete: dest is now word-aligned.
    # R21 = T8 + 4 = next word-aligned address
    asm.append(".Lmemset_fz_head_done:")
    emit_copy_z_clean(asm, ADDR_R21, ADDR_T8)
    asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R21}, .+4")  # R21 = word_base + 4
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .+4")  # n-- for last byte
    # R22 = 0 is set after SRL below (line 1149), omitted here to avoid dead store
    
    # ============================================================
    # FAST ZERO BODY: Set aligned words directly (no pattern needed)
    # Much faster than normal path - no __subleq_mul call!
    # ============================================================
    asm.append(".Lmemset_fz_body_setup:")
    # INLINE SRL: Calculate T7 = n >> 2 (word count)
    # SRL only uses T3/T4 internally, R21/R22/R23 are NOT modified
    emit_inline_srl(asm, ADDR_R23, ADDR_T7, 2, ".Lmemset_fz_srl", ".Lmemset_")
    # T7 = word count directly (no intermediate copy needed)

    asm.append(f"        .word {ADDR_R22}, {ADDR_R22}, .+4")  # R22 = 0
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemset_fz_body_loop")
    
    # FAST ZERO body loop: OPTIMIZED speculative T7 -= 16
    asm.append(".Lmemset_fz_body_loop:")
    asm.append(f"        .word {const_from_pool(16)}, {ADDR_T7}, .Lmemset_fz_body_fixup")
    
    # T7 >= 1: safe to clear 16 words
    for _ in range(16):
        # Mem[R21] = 0 (subleq R21|I, R21|I, next)
        asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R21}, .+4") # R21 += 4
        
    # n -= 64
    asm.append(f"        .word {const_from_pool(64)}, {ADDR_R23}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemset_fz_body_loop")
    
    # Fixup: T7 went <= 0, add 16 back
    asm.append(".Lmemset_fz_body_fixup:")
    asm.append(f"        .word {const_from_pool(-16)}, {ADDR_T7}, .+4")
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T7}, .Lmemset_fz_tail")

    asm.append(".Lmemset_fz_body_single:")
    # Clear word
    asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
    asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R21}, .+4")
    asm.append(f"        .word {const_from_pool(4)}, {ADDR_R23}, .+4")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_T7}, .Lmemset_fz_tail")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemset_fz_body_single")
    
    # ============================================================
    # FAST ZERO TAIL: Set remaining bytes (0-3)
    # Two-entry-point loop: first entry sets RA, loop-back skips RA setup
    # ============================================================
    asm.append(".Lmemset_fz_tail:")
    # OPTIMIZED: After body, dest is word-aligned. Remaining zero-bytes
    # at offsets 0, 1, 2. Unroll with split-entry sb_bN.
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lmemset_done")
    
    # --- Byte 0: sb_b0(dest, 0) ---
    emit_copy_z_dirty(asm, ADDR_T8, ADDR_R21)  # T8 = dest (word-aligned)
    asm.append(f"        .word {ADDR_R22}, {ADDR_R22}, .+4")  # R22 = 0
    emit_call_sequence(asm, ".Lmemset_fz_tail_sb0_ret", "__subleq_sb_b0")
    emit_copy_z_clean(asm, ADDR_R21, ADDR_T8)
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemset_done")
    
    # --- Byte 1: sb_b1(dest, 0) ---
    asm.append(f"        .word {ADDR_R22}, {ADDR_R22}, .+4")
    emit_call_sequence(asm, ".Lmemset_fz_tail_sb1_ret", "__subleq_sb_b1")
    emit_copy_z_clean(asm, ADDR_R21, ADDR_T8)
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemset_done")
    
    # --- Byte 2: sb_b2(dest, 0) ---
    asm.append(f"        .word {ADDR_R22}, {ADDR_R22}, .+4")
    emit_call_sequence(asm, ".Lmemset_fz_tail_sb2_ret", "__subleq_sb_b2")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemset_done")
    
    asm.append(".Lmemset_done:")
    # Restore return value: R20 = T10 (original dest)
    asm.append(f"        .word {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T10}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_R20}, .+4")
    emit_pop_ra(asm)
    asm.extend(emit_return_sequence("memset"))
    
    # Constants


    # Return address constants (positive for negated-RA calling convention)
    asm.append(".Lmemset_head_sb1_ret_neg:")
    asm.append("        .word -.Lmemset_head_sb1_ret")
    asm.append(".Lmemset_head_sb2_ret_neg:")
    asm.append("        .word -.Lmemset_head_sb2_ret")
    asm.append(".Lmemset_head_sb3_ret_neg:")
    asm.append("        .word -.Lmemset_head_sb3_ret")
    asm.append(".Lmemset_tail_sb0_ret_neg:")
    asm.append(f"        .word -.Lmemset_tail_sb0_ret")
    asm.append(".Lmemset_tail_sb1_ret_neg:")
    asm.append(f"        .word -.Lmemset_tail_sb1_ret")
    asm.append(".Lmemset_tail_sb2_ret_neg:")
    asm.append(f"        .word -.Lmemset_tail_sb2_ret")
    # Fast zero path return address constants
    asm.append(".Lmemset_fz_head_sb1_ret_neg:")
    asm.append("        .word -.Lmemset_fz_head_sb1_ret")
    asm.append(".Lmemset_fz_head_sb2_ret_neg:")
    asm.append("        .word -.Lmemset_fz_head_sb2_ret")
    asm.append(".Lmemset_fz_head_sb3_ret_neg:")
    asm.append("        .word -.Lmemset_fz_head_sb3_ret")
    asm.append(".Lmemset_fz_tail_sb0_ret_neg:")
    asm.append(f"        .word -.Lmemset_fz_tail_sb0_ret")
    asm.append(".Lmemset_fz_tail_sb1_ret_neg:")
    asm.append(f"        .word -.Lmemset_fz_tail_sb1_ret")
    asm.append(".Lmemset_fz_tail_sb2_ret_neg:")
    asm.append(f"        .word -.Lmemset_fz_tail_sb2_ret")
    asm.append("")
    asm.append("        .size __subleq_memset, . - __subleq_memset")
    
    return asm


def emit_memmove():
    """Generate optimized memmove using 3-phase algorithm when aligned.
    
    void *memmove(void *dest, const void *src, size_t n)
    Input: R21=dest, R22=src, R23=n
    Output: R20=dest
    
    Algorithm:
    - If dest <= src: copy forward
    - If dest > src: copy backward
    - If (src & 3) == (dst & 3): use 3-phase (head/body/tail) for ~4x speedup
    - Otherwise: use slow byte-by-byte copy
    
    Register allocation:
    - R21: dest pointer
    - R22: src pointer  
    - R23: n (remaining bytes)
    - R20: saved dest (return value)
    - T7: word count (safe from MUL/SRL clobbering)
    - T0, T1: scratch
    """
    asm = []
    asm.append("")
    asm.append("        .globl  __subleq_memmove")
    asm.append("        .type   __subleq_memmove,@function")
    asm.append("# __subleq_memmove(dest=R21, src=R22, n=R23) returns R20=dest")
    asm.append("# Optimized 3-phase when (src&3)==(dst&3), handles overlap")
    asm.append("__subleq_memmove:")
    emit_push_ra(asm)
    
    # Save dest to T10 (survives all internal calls, restored to R20 at exit)
    # Don't save to R20 here - it gets clobbered by lb/sb returns anyway
    # MEM-C: Z is clean at entry (caller convention)
    emit_copy_z_clean(asm, ADDR_T10, ADDR_R21)  # T10 = dest (3 insn vs 4)
    
    # Check if n <= 0, if so done immediately
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lmemmove_done")
    
    # ============================================================
    # INLINE: Direction + alignment using (dest - src)
    # OPTIMIZED: Direction first, then alignment per-path
    #   (dest-src) <= 0  ⟹ forward copy
    #   (dest-src) > 0   ⟹ backward copy
    #   (dest-src) & 3 == 0 ⟺ alignment compatible
    # Each path runs its own lattice_mod on T0 directly (no T3 copy needed)
    # ============================================================
    
    # Compute T0 = dest - src
    emit_copy_z_dirty(asm, ADDR_T0, ADDR_R21)  # T0 = dest
    asm.append(f"        .word {ADDR_R22}, {ADDR_T0}, .+4")  # T0 = dest - src
    
    # Direction check: if T0 <= 0 (dest <= src), forward copy
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T0}, .Lmemmove_forward_check")
    
    # ============================================================
    # BACKWARD COPY (dest > src)
    # T0 = dest - src > 0. Use T0 directly for alignment lattice_mod.
    # ============================================================
    emit_lattice_mod(asm, ADDR_T0, ADDR_T1, ADDR_T5, ".Lmemmove_bwd_align", ".Lmemmove_")
    # T1 = (dest-src) & 3. Always in [0,3], so T1 <= 0 ⟺ T1 == 0.
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T1}, .Lmemmove_bwd_fast_setup")
    # T1 > 0: not compatible, use slow path
    # OPTIMIZED: Fuse T0 clear into jump
    asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .Lmemmove_bwd_slow_start")
    
    # ============================================================
    # SLOW BACKWARD: Point to last byte, copy byte-by-byte
    # ============================================================
    # NOTE: Callers now jump to .Lmemmove_bwd_slow_start with T0 already cleared
    asm.append(".Lmemmove_bwd_slow_start:")
    
    # Point to last byte: src += n-1, dest += n-1
    # T0 = 1-n, then dest -= T0 => dest + n - 1
    # MEM-D: T0 already cleared by fused jump at line 1205, skip redundant clear
    asm.append(f"        .word {ADDR_R23}, {ADDR_T0}, .+4") # T0 = -n
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T0}, .+4") # T0 = -n + 1 = 1-n
    asm.append(f"        .word {ADDR_T0}, {ADDR_R21}, .+4") # dest += n-1
    asm.append(f"        .word {ADDR_T0}, {ADDR_R22}, .+4") # src += n-1
    
    # Phase 1: Align dest to word boundary (copy until (dest+1) & 3 == 0)
    # OPTIMIZED: Unrolled split-entry sb_bN for dest (known alignment from lattice).
    # Generic __subleq_lb for src (different alignment from dest).
    # Backward: byte offsets descend. T5 = (dest+1)&3, dest&3 = T5-1.
    asm.append(".Lmemmove_bwo_head:")
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lmemmove_done")
    
    # Check (dest+1) & 3
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")  # T5 = dest
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T5}, .+4") # T5 = dest+1
    # Compute (dest+1) & 3 using optimized lattice
    emit_lattice_mod(asm, ADDR_T5, ADDR_T5, ADDR_T6, ".Lmemmove_bh", ".Lmemmove_")
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T5}, .Lmemmove_bwd_setup") # aligned
    
    # T5 ∈ {1, 2, 3}. dest & 3 = T5 - 1.
    # Compute dest word base: dest_word = dest - (T5-1) = dest - T5 + 1
    emit_copy_z_dirty(asm, ADDR_T8, ADDR_R21)
    asm.append(f"        .word {ADDR_T5}, {ADDR_T8}, .+4")
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T8}, .+4")  # T8 = dest_word
    # Save src
    emit_copy_z_dirty(asm, ADDR_T9, ADDR_R22)
    
    # Dispatch on T5: 1→sb_b0, 2→sb_b1+sb_b0, 3→sb_b2+sb_b1+sb_b0
    asm.append(f"        .word {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T5}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T6}, .+4")  # T6 = T5
    asm.append(f"        .word {const_from_pool(2)}, {ADDR_T6}, .Lmemmove_bwo_chk12")
    # T5 > 2: T5 = 3 → bytes 2, 1, 0
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_bwo_sb2")
    
    asm.append(".Lmemmove_bwo_chk12:")
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T6}, .Lmemmove_bwo_sb0")  # T5=1 → byte 0 only
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_bwo_sb1")  # T5=2 → bytes 1, 0
    
    # --- Byte at dest offset 2: lb(src) → sb_b2(dest_word) ---
    asm.append(".Lmemmove_bwo_sb2:")
    emit_copy_z_clean(asm, ADDR_R21, ADDR_R22)  # R21 = src (for lb) — Z clean from dispatch
    emit_call_sequence(asm, ".Lmemmove_bwo_lb2_ret", "__subleq_lb")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)   # R22 = byte value
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)    # R21 = dest word base
    emit_call_sequence(asm, ".Lmemmove_bwo_sb2_ret", "__subleq_sb_b2")
    # src--, n--
    asm.append(f"        .word {ADDR_ONE}, {ADDR_T9}, .+4")
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T9)    # R22 = --src
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemmove_done")
    
    # --- Byte at dest offset 1: lb(src) → sb_b1(dest_word) ---
    asm.append(".Lmemmove_bwo_sb1:")
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_R22)
    emit_call_sequence(asm, ".Lmemmove_bwo_lb1_ret", "__subleq_lb")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    emit_call_sequence(asm, ".Lmemmove_bwo_sb1_ret", "__subleq_sb_b1")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_T9}, .+4")
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T9)
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemmove_done")
    
    # --- Byte at dest offset 0: lb(src) → sb_b0(dest_word) ---
    asm.append(".Lmemmove_bwo_sb0:")
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_R22)
    emit_call_sequence(asm, ".Lmemmove_bwo_lb0_ret", "__subleq_lb")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    emit_call_sequence(asm, ".Lmemmove_bwo_sb0_ret", "__subleq_sb_b0")
    
    # Head complete. dest_word - 1 = byte 3 of the PREVIOUS word.
    # bwd_setup subtracts 3: (dest_word-1) - 3 = dest_word - 4 = prev word start. ✓
    emit_copy_z_clean(asm, ADDR_R21, ADDR_T8)
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R21}, .+4")  # R21 = dest_word - 1
    asm.append(f"        .word {ADDR_ONE}, {ADDR_T9}, .+4")
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T9)    # R22 = --src
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .+4")  # n-- for last byte
    
    # Phase 2: Setup shift values
    asm.append(".Lmemmove_bwd_setup:")
    asm.append(f"        .word {const_from_pool(3)}, {ADDR_R21}, .+4") # dest points to word start
    # Check n >= 4
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_R23}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")
    asm.append(f"        .word {const_from_pool(3)}, {ADDR_T5}, .Lmemmove_bwd_tail_early")  # early exit: no body loop ran
    
    # shift = ((src & 3) + 1) * 8
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_R22}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")
    # Compute src & 3 using optimized lattice
    emit_lattice_mod(asm, ADDR_T5, ADDR_T5, ADDR_T6, ".Lmemmove_bs", ".Lmemmove_")
    # For backward: shift = ((src & 3) + 1) * 8
    # T5 currently has src & 3. Save it in T2 before modifying.
    emit_copy_z_dirty(asm, ADDR_T2, ADDR_T5)  # T2 = src & 3 (saved for aligned_src calc)
    emit_copy_z_dirty(asm, ADDR_T11, ADDR_T5)  # T11 = src & 3 (saved for R22 reconstruction at tail)
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T5}, .+4")  # T5 = (src & 3) + 1
    
    # ============================================================
    # OPTIMIZED: Branch to specialized backward handlers based on T5
    # T5 = 1 -> shift=8, T5 = 2 -> shift=16, T5 = 3 -> shift=24
    # Each handler uses inline srl/shl (no function calls)
    # ============================================================
    
    # aligned_src = src - (src & 3), using saved T2
    asm.append(f"        .word {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_R22}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T6}, .+4")  # T6 = src
    asm.append(f"        .word {ADDR_T2}, {ADDR_T6}, .+4") # T6 = src - (src & 3) = aligned_src
    
    # Load WordHigh from aligned_src
    asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word {ADDR_T6 | INDIRECT_FLAG}, {ADDR_T0}, .+4")
    asm.append(f"        .word {ADDR_T1}, {ADDR_T1}, .+4")
    asm.append(f"        .word {ADDR_T0}, {ADDR_T1}, .+4")
    asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T1}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T0}, .+4")  # T0 = WordHigh
    asm.append(f"        .word {const_from_pool(4)}, {ADDR_T6}, .+4")  # pre-decrement aligned_src
    
    # Branch based on T5: 1 -> bwd_ua8, 2 -> bwd_ua16, 3 -> bwd_ua24, 4 -> bwd_ua32
    # T5 = (src & 3) + 1, so T5 can be 1, 2, 3, or 4
    asm.append(f"        .word {ADDR_T1}, {ADDR_T1}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T5}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T1}, .+4")  # T1 = T5 (1, 2, 3, or 4)
    # T5 = 1 -> shift 8, T5 = 2 -> shift 16, T5 = 3 -> shift 24, T5 = 4 -> shift 32
    asm.append(f"        .word {const_from_pool(2)}, {ADDR_T1}, .Lmemmove_bwd_ua_chk12")  # if T1-2 <= 0 (T5 <= 2)
    # T5 > 2: check if 3 or 4
    asm.append(f"        .word {ADDR_ONE}, {ADDR_T1}, .Lmemmove_bwd_ua24_e_body")  # T1 was already -2, if T1-1 <= 0 then T5 = 3
    # T5 = 4: go to bwd_ua32
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_bwd_ua32_e_body")
    
    asm.append(".Lmemmove_bwd_ua_chk12:")
    # T1 has T5 - 2. If T5 = 1, T1 = -1 (< 0); if T5 = 2, T1 = 0
    # To distinguish: check if T1 + 1 <= 0 (T1 <= -1, i.e., T1 < 0)
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T1}, .Lmemmove_bwd_ua8_e_body")  # T1 += 1; if T1 <= 0 (orig T1 < 0)
    # T5 = 2 (orig T1 = 0, now T1 = 1 > 0): go to bwd_ua16
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_bwd_ua16_e_body")
    
    # ============================================================
    # Specialized backward handlers with inline srl/shl
    # shift = T5 * 8 where T5 = (src & 3) + 1
    # T5 = 1 -> shift 8, T5 = 2 -> shift 16, T5 = 3 -> shift 24, T5 = 4 -> shift 32
    # ============================================================
    emit_backward_unaligned_body_loop(asm, 8, ".Lmemmove_bwd_ua8", ".Lmemmove_")
    emit_backward_unaligned_body_loop(asm, 16, ".Lmemmove_bwd_ua16", ".Lmemmove_")
    emit_backward_unaligned_body_loop(asm, 24, ".Lmemmove_bwd_ua24", ".Lmemmove_")
    emit_backward_unaligned_body_loop(asm, 32, ".Lmemmove_bwd_ua32", ".Lmemmove_")
    
    # Phase 4: Tail (unaligned backward exit)
    # The unaligned path can't use the fast split-entry btail because
    # src & 3 != dest & 3. Use a generic byte-by-byte loop instead.
    asm.append(".Lmemmove_bwd_tail_early:")
    # Early exit: body loop never ran, R22 is still correct
    asm.append(f"        .word {const_from_pool(-3)}, {ADDR_R21}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_bwd_generic_tail")
    
    asm.append(".Lmemmove_bwd_tail:")
    # Reconstruct R22 (src) from T6 (aligned_src) and T11 (src & 3 offset)
    # R22 = T6 + T11 + 4 (T6 was pre-decremented by 4 at setup, both decrement by 4/iter)
    emit_copy_z_clean(asm, ADDR_R22, ADDR_T6)     # R22 = T6 (Z clean from restore trampoline)
    asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R22}, .+4")  # R22 = T6 + 4
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T11}, {ADDR_Z}, .+4")      # Z = -T11
    asm.append(f"        .word {ADDR_Z}, {ADDR_R22}, .+4")      # R22 = T6 + 4 + T11
    asm.append(f"        .word {const_from_pool(-3)}, {ADDR_R21}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_bwd_generic_tail")
    
    # Generic backward byte-loop for unaligned path exit
    asm.append(".Lmemmove_bwd_generic_tail:")
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lmemmove_done")
    # Load byte from src using __subleq_lb
    emit_copy_z_dirty(asm, ADDR_T8, ADDR_R21)
    emit_copy_z_dirty(asm, ADDR_T9, ADDR_R22)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_R22)  # R21 = src
    emit_call_sequence(asm, ".Lmemmove_bwd_gtail_lb_ret", "__subleq_lb")
    # sb_nomask: R22 = byte (R20), R21 = dest (T8)
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    emit_call_sequence(asm, ".Lmemmove_bwd_gtail_sb_ret", "__subleq_sb_nomask")
    emit_copy_z_clean(asm, ADDR_R21, ADDR_T8)
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T9)
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R22}, .+4")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R21}, .+4")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_bwd_generic_tail")
    
    # ============================================================
    # FAST BACKWARD: 3-Phase Algorithm
    # Phase 1 (Tail): Point to end, copy bytes until (src+1) & 3 == 0
    # Phase 2 (Body): Copy words backward
    # Phase 3 (Head): Copy remaining bytes
    # ============================================================
    asm.append(".Lmemmove_bwd_fast_setup:")
    # Point to last byte: src += n-1, dest += n-1
    asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_R23}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T0}, .+4")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_T0}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    
    asm.append(f"        .word {ADDR_T0}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_R22}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    
    asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word {ADDR_R23}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T0}, .+4")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_T0}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T0}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_R21}, .Lmemmove_bwd_fast_tail")
    
    # Phase 1 (Tail): Copy bytes until (src+1) & 3 == 0
    # OPTIMIZED: Unrolled split-entry lb_bN/sb_bN. Since src & 3 == dest & 3
    # (compatible alignment), both share the same byte offset.
    # Backward: byte offsets descend. T5 = (src+1)&3, src&3 = T5-1.
    # T5=1 → byte 0 only; T5=2 → bytes 1,0; T5=3 → bytes 2,1,0.
    asm.append(".Lmemmove_bwd_fast_tail:")
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lmemmove_done")
    
    # INLINE: Check (src + 1) & 3
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_R22}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")  # T5 = src
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T5}, .+4")  # T5 = src + 1
    
    # Compute (src+1) & 3 using optimized lattice
    emit_lattice_mod(asm, ADDR_T5, ADDR_T5, ADDR_T6, ".Lmemmove_btail", ".Lmemmove_")
    # T5 = (src + 1) & 3; if T5 <= 0 (== 0), aligned, go to body setup
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T5}, .Lmemmove_bwd_body_setup")
    
    # T5 ∈ {1, 2, 3}. src & 3 = T5 - 1.
    # Compute word-aligned bases: word_base = addr - (addr & 3)
    # src & 3 = T5 - 1, so src_word = src - (T5-1) = src - T5 + 1
    # dest & 3 = T5 - 1, so dest_word = dest - (T5-1) = dest - T5 + 1
    emit_copy_z_dirty(asm, ADDR_T8, ADDR_R21)
    asm.append(f"        .word {ADDR_T5}, {ADDR_T8}, .+4")
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T8}, .+4")  # T8 = dest - T5 + 1 = dest_word
    emit_copy_z_dirty(asm, ADDR_T9, ADDR_R22)
    asm.append(f"        .word {ADDR_T5}, {ADDR_T9}, .+4")
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T9}, .+4")  # T9 = src - T5 + 1 = src_word
    
    # Dispatch on T5: 1→b0 only, 2→b1 then b0, 3→b2 then b1 then b0
    asm.append(f"        .word {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T5}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T6}, .+4")  # T6 = T5
    asm.append(f"        .word {const_from_pool(2)}, {ADDR_T6}, .Lmemmove_btail_chk12")
    # T5 > 2: T5 = 3 → bytes 2,1,0
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_btail_b2")
    
    asm.append(".Lmemmove_btail_chk12:")
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T6}, .Lmemmove_btail_b0")  # T5 was 1 → byte 0 only
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_btail_b1")  # T5 was 2 → bytes 1,0
    
    # --- Byte at offset 2: lb_b2(src_word) → sb_b2(dest_word) ---
    asm.append(".Lmemmove_btail_b2:")
    emit_copy_z_clean(asm, ADDR_R21, ADDR_T9)  # R21 = src word base — Z clean from dispatch
    emit_call_sequence(asm, ".Lmemmove_btail_lb2_ret", "__subleq_lb_b2")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)   # R21 = dest word base
    emit_call_sequence(asm, ".Lmemmove_btail_sb2_ret", "__subleq_sb_b2")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemmove_done")  # n--; if n==0, all done
    
    # --- Byte at offset 1: lb_b1(src_word) → sb_b1(dest_word) ---
    asm.append(".Lmemmove_btail_b1:")
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T9)
    emit_call_sequence(asm, ".Lmemmove_btail_lb1_ret", "__subleq_lb_b1")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    emit_call_sequence(asm, ".Lmemmove_btail_sb1_ret", "__subleq_sb_b1")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemmove_done")  # n--; if n==0, all done
    
    # --- Byte at offset 0: lb_b0(src_word) → sb_b0(dest_word) ---
    asm.append(".Lmemmove_btail_b0:")
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T9)
    emit_call_sequence(asm, ".Lmemmove_btail_lb0_ret", "__subleq_lb_b0")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    emit_call_sequence(asm, ".Lmemmove_btail_sb0_ret", "__subleq_sb_b0")
    
    # Tail alignment complete. Adjust pointers for body.
    # src_word - 4 = previous word, dest_word - 4 = previous word
    # But body_setup expects src/dest pointing to last byte of aligned word.
    # src currently points to byte 0 of the word we just processed.
    # After alignment, src should point to byte 3 of the previous word = src_word - 1
    # dest same: dest_word - 1
    asm.append(".Lmemmove_btail_complete:")
    # Reconstruct R21/R22 for body_setup.
    # body_setup expects R21=dest, R22=src pointing at last byte of aligned word
    # (byte 3 of previous word). word_base - 1 = byte 3 of prev word.
    emit_copy_z_clean(asm, ADDR_R21, ADDR_T8)
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R21}, .+4")  # R21 = dest_word - 1
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T9)
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R22}, .+4")  # R22 = src_word - 1
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .+4")  # n-- for last byte
    
    # Phase 2 (Body): Copy words backward
    # src now points to last byte of a word, so (src - 3) is start of that word
    asm.append(".Lmemmove_bwd_body_setup:")
    # Adjust pointers: src -= 3, dest -= 3 (point to start of word)
    asm.append(f"        .word {const_from_pool(3)}, {ADDR_R22}, .+4")
    asm.append(f"        .word {const_from_pool(3)}, {ADDR_R21}, .+4")
    
    # T7 = n >> 2 (word count) - INLINE SRL
    # SRL only uses T3/T4 internally, R21/R22/R23 are NOT modified
    emit_inline_srl(asm, ADDR_R23, ADDR_T7, 2, ".Lmemmove_bwd_fast_srl", ".Lmemmove_")
    # T7 = word count directly (no intermediate copy needed)
    asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .Lmemmove_bwd_body_loop")  # clear T0 + jump
    
    asm.append(".Lmemmove_bwd_body_loop:")
    asm.append(f"        .word {const_from_pool(8)}, {ADDR_T7}, .Lmemmove_bwd_body_fixup")
    
    # T7 >= 1 (was >= 9): safe to copy 8 words
    for i in range(8):
        if i > 0:
            # Clear T0 (word 0 already has T0=0 from loop-entry/loop-back)
            asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .+4")
        # Load word from src: T0 -= [src] -> T0 = -mem[src]
        asm.append(f"        .word {ADDR_R22 | INDIRECT_FLAG}, {ADDR_T0}, .+4")
        # Store word to dest: mem[R21] = 0 - T0
        asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        asm.append(f"        .word {ADDR_T0}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        # src -= 4, dest -= 4
        asm.append(f"        .word {const_from_pool(4)}, {ADDR_R22}, .+4")
        asm.append(f"        .word {const_from_pool(4)}, {ADDR_R21}, .+4")
        
    # n -= 32
    asm.append(f"        .word {const_from_pool(32)}, {ADDR_R23}, .+4")
    # Loop back: T0 = 0 AND jump
    asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .Lmemmove_bwd_body_loop")
    
    # Fixup: T7 went <= 0, add 8 back
    asm.append(".Lmemmove_bwd_body_fixup:")
    asm.append(f"        .word {const_from_pool(-8)}, {ADDR_T7}, .+4")
    # If T7 == 0, go to head setup
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T7}, .Lmemmove_bwd_head_setup")

    asm.append(".Lmemmove_bwd_body_single:")
    # T0 is 0 (guaranteed from entry/loop-back T0-clear jump)
    # Load word from src: T0 -= [src] -> T0 = -mem[src]
    asm.append(f"        .word {ADDR_R22 | INDIRECT_FLAG}, {ADDR_T0}, .+4")
    # Store word to dest
    asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
    asm.append(f"        .word {ADDR_T0}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
    # src -= 4, dest -= 4, n -= 4, T7 -= 1
    asm.append(f"        .word {const_from_pool(4)}, {ADDR_R22}, .+4")
    asm.append(f"        .word {const_from_pool(4)}, {ADDR_R21}, .+4")
    asm.append(f"        .word {const_from_pool(4)}, {ADDR_R23}, .+4")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_T7}, .Lmemmove_bwd_head_setup")
    # Loop back: clear T0 for next word
    asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .Lmemmove_bwd_body_single")
    
    # Phase 3 (Head): Copy remaining bytes (0-3) after body
    # OPTIMIZED: Unrolled split-entry lb_bN/sb_bN.
    # After body, src/dest point to start of a word. Remaining n <= 3 bytes
    # are at offsets 3, 2, 1 of this word (going backward from the end).
    # Word base = R22 (src) = R21 (dest) — already word-aligned from body.
    asm.append(".Lmemmove_bwd_head_setup:")
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lmemmove_done")
    
    # R21/R22 are the word base (body left them word-aligned)
    # T8 = dest word base, T9 = src word base
    emit_copy_z_dirty(asm, ADDR_T8, ADDR_R21)
    emit_copy_z_dirty(asm, ADDR_T9, ADDR_R22)
    
    # --- Byte at offset 3: lb_b3(src_word) → sb_b3(dest_word) ---
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T9)  # R21 = src word base
    emit_call_sequence(asm, ".Lmemmove_bhead_lb3_ret", "__subleq_lb_b3")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)   # R21 = dest word base
    emit_call_sequence(asm, ".Lmemmove_bhead_sb3_ret", "__subleq_sb_b3")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemmove_done")  # n--; if n==0, done
    
    # --- Byte at offset 2: lb_b2(src_word) → sb_b2(dest_word) ---
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T9)
    emit_call_sequence(asm, ".Lmemmove_bhead_lb2_ret", "__subleq_lb_b2")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    emit_call_sequence(asm, ".Lmemmove_bhead_sb2_ret", "__subleq_sb_b2")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemmove_done")  # n--; if n==0, done
    
    # --- Byte at offset 1: lb_b1(src_word) → sb_b1(dest_word) ---
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T9)
    emit_call_sequence(asm, ".Lmemmove_bhead_lb1_ret", "__subleq_lb_b1")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    emit_call_sequence(asm, ".Lmemmove_bhead_sb1_ret", "__subleq_sb_b1")
    # n was at most 3, we copied 3 bytes. Done.
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_done")
    
    # ============================================================
    # FORWARD COPY (dest <= src)
    # T0 = dest - src <= 0. Use T0 directly for alignment lattice_mod.
    # ============================================================
    asm.append(".Lmemmove_forward_check:")
    emit_lattice_mod(asm, ADDR_T0, ADDR_T1, ADDR_T5, ".Lmemmove_fwd_align", ".Lmemmove_")
    # T1 = (dest-src) & 3. Always in [0,3], so T1 <= 0 ⟺ T1 == 0.
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T1}, .Lmemmove_fwd_fast_head")
    # T1 > 0: not compatible, use slow path
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_fwd_slow_start")
    
    # ============================================================
    # FAST FORWARD: 3-Phase Algorithm
    # Phase 1: Head - copy bytes until src is word-aligned
    # OPTIMIZED: Unrolled split-entry lb_bN/sb_bN. Since src & 3 == dest & 3
    # (compatible alignment), both share the same byte offset in their word.
    # Saves ~123 ops per head byte (no per-iteration lattice_mod, no internal
    # modulo in lb or sb).
    # ============================================================
    asm.append(".Lmemmove_fwd_fast_head:")
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lmemmove_done")
    
    # INLINE: Check src alignment (src & 3)
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_R22}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")  # T5 = src
    
    # Compute src & 3 using optimized lattice
    emit_lattice_mod(asm, ADDR_T5, ADDR_T5, ADDR_T6, ".Lmemmove_fhead", ".Lmemmove_")
    # T5 = src & 3; if T5 <= 0 (== 0), aligned, go to body setup
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T5}, .Lmemmove_fwd_body_setup")
    
    # T5 = offset ∈ {1, 2, 3}. Compute word-aligned bases:
    # T8 = dest - offset (word-aligned dest base)
    # T9 = src - offset  (word-aligned src base)
    emit_copy_z_dirty(asm, ADDR_T8, ADDR_R21)
    asm.append(f"        .word {ADDR_T5}, {ADDR_T8}, .+4")  # T8 = dest - offset
    emit_copy_z_dirty(asm, ADDR_T9, ADDR_R22)
    asm.append(f"        .word {ADDR_T5}, {ADDR_T9}, .+4")  # T9 = src - offset
    
    # Dispatch on T5: 1→b1, 2→b2, 3→b3
    asm.append(f"        .word {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T5}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T6}, .+4")  # T6 = T5
    asm.append(f"        .word {const_from_pool(2)}, {ADDR_T6}, .Lmemmove_fhead_chk12")
    # T5 > 2: T5 = 3 → need 1 byte (b3 only)
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_fhead_b3")
    
    asm.append(".Lmemmove_fhead_chk12:")
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T6}, .Lmemmove_fhead_b1")  # T5 was 1
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_fhead_b2")  # T5 was 2
    
    # --- Byte at offset 1: lb_b1(src_base) → sb_b1(dest_base) ---
    asm.append(".Lmemmove_fhead_b1:")
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T9)  # R21 = src word base (for lb_b1)
    emit_call_sequence(asm, ".Lmemmove_fhead_lb1_ret", "__subleq_lb_b1")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)  # R22 = byte value
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)   # R21 = dest word base (for sb_b1)
    emit_call_sequence(asm, ".Lmemmove_fhead_sb1_ret", "__subleq_sb_b1")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemmove_done")  # n--; if n==0, all done
    
    # --- Byte at offset 2: lb_b2(src_base) → sb_b2(dest_base) ---
    asm.append(".Lmemmove_fhead_b2:")
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T9)
    emit_call_sequence(asm, ".Lmemmove_fhead_lb2_ret", "__subleq_lb_b2")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    emit_call_sequence(asm, ".Lmemmove_fhead_sb2_ret", "__subleq_sb_b2")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemmove_done")  # n--; if n==0, all done
    
    # --- Byte at offset 3: lb_b3(src_base) → sb_b3(dest_base) ---
    asm.append(".Lmemmove_fhead_b3:")
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T9)
    emit_call_sequence(asm, ".Lmemmove_fhead_lb3_ret", "__subleq_lb_b3")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    emit_call_sequence(asm, ".Lmemmove_fhead_sb3_ret", "__subleq_sb_b3")
    
    # Head complete. Set R21 = dest_base + 4, R22 = src_base + 4 (both word-aligned)
    asm.append(".Lmemmove_fhead_complete:")
    emit_copy_z_clean(asm, ADDR_R21, ADDR_T8)
    asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R21}, .+4")  # R21 = dest_base + 4
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T9)
    asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R22}, .+4")  # R22 = src_base + 4
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .+4")  # n-- for last byte
    
    # ============================================================
    # Phase 2: Body - copy aligned words using indirect addressing
    # ============================================================
    asm.append(".Lmemmove_fwd_body_setup:")
    # T7 = n >> 2 (word count) - INLINE SRL
    # SRL only uses T3/T4 internally, R21/R22/R23 are NOT modified
    emit_inline_srl(asm, ADDR_R23, ADDR_T7, 2, ".Lmemmove_fwd_srl", ".Lmemmove_")
    # T7 = word count directly (no intermediate copy needed)
    asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .Lmemmove_fwd_body_loop")  # clear T0 + jump
    
    # Body loop: OPTIMIZED speculative T7 -= 8
    # Instead of {check T7>0 (1) + copy T7 (4) + check >=8 (1)} = 6 instructions,
    # we do T7 -= 8 (1 insn) speculatively. If T7 <= 0, we overshot and fixup.
    asm.append(".Lmemmove_fwd_body_loop:")
    asm.append(f"        .word {const_from_pool(8)}, {ADDR_T7}, .Lmemmove_fwd_body_fixup")
    
    # T7 >= 1 (was >= 9): safe to copy 8 words
    for i in range(8):
        if i > 0:
            # Clear T0 (word 0 already has T0=0 from loop-entry/loop-back)
            asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .+4")
        # Load: T0 -= [src] -> T0 = -mem[src]
        asm.append(f"        .word {ADDR_R22 | INDIRECT_FLAG}, {ADDR_T0}, .+4")
        # Store mem[dest] = 0 - T0 = mem[src]
        asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        asm.append(f"        .word {ADDR_T0}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        # Ptr increments
        asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R22}, .+4")
        asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R21}, .+4")
        
    # n -= 32
    asm.append(f"        .word {const_from_pool(32)}, {ADDR_R23}, .+4")
    # Loop back: T0 = 0 AND jump (saves 1 insn vs separate clear + jump)
    asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .Lmemmove_fwd_body_loop")
    
    # Fixup: T7 went <= 0, add 8 back to get remaining word count
    asm.append(".Lmemmove_fwd_body_fixup:")
    asm.append(f"        .word {const_from_pool(-8)}, {ADDR_T7}, .+4")
    # T7 now has 0-7 remaining words
    # If T7 == 0, go directly to tail
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T7}, .Lmemmove_fwd_tail")

    asm.append(".Lmemmove_fwd_body_single:")
    # T0 is 0 (guaranteed from entry/loop-back T0-clear jump)
    # Load word from src: T0 -= [src] -> T0 = -mem[src]
    asm.append(f"        .word {ADDR_R22 | INDIRECT_FLAG}, {ADDR_T0}, .+4")
    # Store word to dest
    asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
    asm.append(f"        .word {ADDR_T0}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
    # src += 4, dest += 4, n -= 4, T7 -= 1
    asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R22}, .+4")
    asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R21}, .+4")
    asm.append(f"        .word {const_from_pool(4)}, {ADDR_R23}, .+4")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_T7}, .Lmemmove_fwd_tail")
    # Loop back: clear T0 for next word
    asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .Lmemmove_fwd_body_single")
    
    # ============================================================
    # Phase 3: Tail - copy remaining bytes (0-3)
    # OPTIMIZED: After word body, src/dest are word-aligned.
    # Unroll to use split-entry lb_bN/sb_bN, skipping the ~35-op
    # modulo lattice in each lb/sb call.
    # n ∈ {1,2,3} at this point (n=0 caught by check above).
    # ============================================================
    asm.append(".Lmemmove_fwd_tail:")
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lmemmove_done")
    
    # --- Byte 0: lb_b0(src) → sb_b0(dest) ---
    # R21 = src (for lb_b0, R21 = word-aligned address)
    emit_copy_z_dirty(asm, ADDR_T8, ADDR_R21)   # save dest
    emit_copy_z_dirty(asm, ADDR_T9, ADDR_R22)   # save src
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_R22)   # R21 = src (word-aligned)
    emit_call_sequence(asm, ".Lmemmove_tail_lb0_ret", "__subleq_lb_b0")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)   # R22 = byte value
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)    # R21 = dest (word-aligned)
    emit_call_sequence(asm, ".Lmemmove_tail_sb0_ret", "__subleq_sb_b0")
    emit_copy_z_clean(asm, ADDR_R21, ADDR_T8)    # restore dest
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T9)    # restore src
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemmove_done")  # n--; if n==0, done
    
    # --- Byte 1: lb_b1(src) → sb_b1(dest) ---
    # R21 = src (still word-aligned, byte 1 is at src+1)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_R22)   # R21 = src
    emit_call_sequence(asm, ".Lmemmove_tail_lb1_ret", "__subleq_lb_b1")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)    # R21 = dest
    emit_call_sequence(asm, ".Lmemmove_tail_sb1_ret", "__subleq_sb_b1")
    emit_copy_z_clean(asm, ADDR_R21, ADDR_T8)
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T9)
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemmove_done")  # n--; if n==0, done
    
    # --- Byte 2: lb_b2(src) → sb_b2(dest) ---
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_R22)
    emit_call_sequence(asm, ".Lmemmove_tail_lb2_ret", "__subleq_lb_b2")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    emit_call_sequence(asm, ".Lmemmove_tail_sb2_ret", "__subleq_sb_b2")
    # n was at most 3, and we've copied 3 bytes. Done.
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_done")
    
    # ============================================================
    # ============================================================
    # OPTIMIZED FORWARD LOOP (misaligned case)
    # True word-at-a-time copy with shift-combine
    # ~4x faster than byte-by-byte by avoiding lb/sb calls
    # ============================================================
    asm.append(".Lmemmove_fwd_slow_start:")
    # DEBUG: Output '%' to indicate unaligned path
    
    # --------------------------------------------------------
    # Phase 1: Align destination to word boundary
    # Copy bytes until (dst & 3) == 0
    # --------------------------------------------------------
    asm.append(".Lmemmove_unaligned_head:")
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lmemmove_done")
    
    # Check dst & 3 - inline bit extraction
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")  # T5 = dst
    # Compute dst & 3 using optimized lattice
    emit_lattice_mod(asm, ADDR_T5, ADDR_T5, ADDR_T6, ".Lmemmove_uhead", ".Lmemmove_")
    # T5 = dst & 3; if T5 <= 0 (== 0), dst is aligned
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T5}, .Lmemmove_unaligned_setup")
    
    # T5 = dest offset ∈ {1, 2, 3}. Compute dest word base:
    # T8 = R21 - T5 (word-aligned dest base for sb_bN)
    emit_copy_z_dirty(asm, ADDR_T8, ADDR_R21)
    asm.append(f"        .word {ADDR_T5}, {ADDR_T8}, .+4")  # T8 = dest - offset = dest_word
    # Save src
    emit_copy_z_dirty(asm, ADDR_T9, ADDR_R22)
    
    # Dispatch on T5: 1→sb_b1, 2→sb_b2, 3→sb_b3
    asm.append(f"        .word {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T5}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T6}, .+4")  # T6 = T5
    asm.append(f"        .word {const_from_pool(2)}, {ADDR_T6}, .Lmemmove_uhead_chk12")
    # T5 > 2: dest offset = 3 → only sb_b3
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_uhead_sb3")
    
    asm.append(".Lmemmove_uhead_chk12:")
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T6}, .Lmemmove_uhead_sb1")  # T5 was 1
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_uhead_sb2")  # T5 was 2
    
    # --- Byte at dest offset 1: lb(src) → sb_b1(dest_word) ---
    asm.append(".Lmemmove_uhead_sb1:")
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_R22)  # R21 = src (for lb)
    emit_call_sequence(asm, ".Lmemmove_uhead_lb1_ret", "__subleq_lb")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)   # R22 = byte value
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)    # R21 = dest word base
    emit_call_sequence(asm, ".Lmemmove_uhead_sb1_ret", "__subleq_sb_b1")
    # src++, n--
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T9}, .+4")
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T9)    # R22 = ++src
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemmove_done")
    
    # --- Byte at dest offset 2: lb(src) → sb_b2(dest_word) ---
    asm.append(".Lmemmove_uhead_sb2:")
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_R22)
    emit_call_sequence(asm, ".Lmemmove_uhead_lb2_ret", "__subleq_lb")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    emit_call_sequence(asm, ".Lmemmove_uhead_sb2_ret", "__subleq_sb_b2")
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T9}, .+4")
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T9)
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemmove_done")
    
    # --- Byte at dest offset 3: lb(src) → sb_b3(dest_word) ---
    asm.append(".Lmemmove_uhead_sb3:")
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_R22)
    emit_call_sequence(asm, ".Lmemmove_uhead_lb3_ret", "__subleq_lb")
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    emit_call_sequence(asm, ".Lmemmove_uhead_sb3_ret", "__subleq_sb_b3")
    
    # Head complete. dest = dest_word + 4 (word-aligned), src = T9 + 1
    emit_copy_z_clean(asm, ADDR_R21, ADDR_T8)
    asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R21}, .+4")  # R21 = dest_word + 4
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_T9}, .+4")
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T9)    # R22 = ++src
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .+4")  # n-- for last byte
    
    # --------------------------------------------------------
    # Phase 2: Setup - calculate shift, load first word
    # T3 = shift = (src & 3) * 8
    # T4 = 32 - shift
    # T6 = aligned_src = src & ~3
    # T0 = word0 = mem[aligned_src]
    # --------------------------------------------------------
    asm.append(".Lmemmove_unaligned_setup:")
    # If n < 4, go directly to tail
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4") 
    asm.append(f"        .word {ADDR_R23}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")  # T5 = n
    asm.append(f"        .word {const_from_pool(3)}, {ADDR_T5}, .Lmemmove_fwd_slow_loop_early")
    
    # Get src & 3 into T5
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_R22}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")  # T5 = src
    # Compute src & 3 using optimized lattice
    emit_lattice_mod(asm, ADDR_T5, ADDR_T5, ADDR_T6, ".Lmemmove_setup", ".Lmemmove_")
    # T5 = src & 3 (0, 1, 2, or 3)
    
    # Save src & 3 to T2 for later aligned_src calculation
    emit_copy_z_dirty(asm, ADDR_T2, ADDR_T5)
    # Also save to T11 for R22 reconstruction at tail (body loop doesn't track R22)
    emit_copy_z_dirty(asm, ADDR_T11, ADDR_T5)
    
    # --------------------------------------------------------
    # OPTIMAL SHIFT SELECTION:
    # offset 1 → shift=24 (with aligned_src-4), saves 110 ops/word
    # offset 2 → shift=16 (unchanged)
    # offset 3 → shift=24 (unchanged)
    # offset 0 → aligned fast path
    # --------------------------------------------------------
    
    # T6 = aligned_src = src - (src & 3), using saved T2
    asm.append(f"        .word {ADDR_T6}, {ADDR_T6}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_R22}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T6}, .+4")  # T6 = src
    asm.append(f"        .word {ADDR_T2}, {ADDR_T6}, .+4")  # T6 = src - (src & 3) = aligned_src
    # Z dead after T6 calc — next use (T0,T0) overwrites
    
    # Load word0: T0 = mem[aligned_src]
    asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word {ADDR_T6 | INDIRECT_FLAG}, {ADDR_T0}, .+4")  # T0 = -mem[T6]
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {ADDR_T0}, {ADDR_T5}, .+4")  # T5 = -T0 = mem[T6]
    asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T5}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T0}, .+4")  # T0 = word0
    # Z dead after word0 copy — next use (Lmemmove_n4,T6) overwrites
    
    # Advance aligned_src
    asm.append(f"        .word {const_from_pool(-4)}, {ADDR_T6}, .+4")
    
    # Branch based on T2 (src & 3): 1 -> shift8, 2 -> shift16, 3 -> shift24
    # T2 - 2 <= 0? If yes, T2 is 1 or 2 (T2=0 is handled as aligned)
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T2}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")  # T5 = T2
    asm.append(f"        .word {const_from_pool(2)}, {ADDR_T5}, .Lmemmove_ua_chk12")  # if T5-2 <= 0 (T2 <= 2)
    # T2 = 3: go to shift24 handler
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_ua24_e_body")
    
    asm.append(f".Lmemmove_ua_chk12:")
    # Check if T2 = 0 (aligned src) - should not use srl handlers
    # Just check if T2 <= 0: if T2 <= 0, it's 0 (since T2 >= 0 by construction)
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T2}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")  # T5 = T2
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T5}, .Lmemmove_fwd_slow_loop_early")  # if T5 <= 0 (T2 = 0), slow path
    # Now T5 > 0, so T2 is 1 or 2
    # T5 - 1 <= 0? (i.e., T5 <= 1) -> T2 was 1
    asm.append(f"        .word {ADDR_ONE}, {ADDR_T5}, .Lmemmove_ua8_e_body")  # if T5-1 <= 0 (T2 = 1)
    # T2 = 2: go to shift16 handler
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_ua16_e_body")
    
    # --------------------------------------------------------
    # Handler for src & 3 = 1 (shift=8, inv_shift=24)
    # --------------------------------------------------------
    emit_unaligned_body_loop(asm, 8, ".Lmemmove_ua8", ".Lmemmove_")
    
    # --------------------------------------------------------
    # Handler for src & 3 = 2 (shift=16, inv_shift=16)
    # --------------------------------------------------------
    emit_unaligned_body_loop(asm, 16, ".Lmemmove_ua16", ".Lmemmove_")
    
    # --------------------------------------------------------
    # Handler for src & 3 = 3 (shift=24, inv_shift=8)
    # --------------------------------------------------------
    emit_unaligned_body_loop(asm, 24, ".Lmemmove_ua24", ".Lmemmove_")
    
    # --------------------------------------------------------
    # Phase 4: Tail - remaining 0-3 bytes
    # --------------------------------------------------------
    asm.append(".Lmemmove_fwd_slow_loop_early:")
    # Early exit: body loop never ran or src is aligned, R22 is still correct
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lmemmove_done")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_fwd_slow_loop_body")
    
    asm.append(".Lmemmove_fwd_slow_loop:")
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lmemmove_done")
    
    # Reconstruct R22 (src) from T6 (aligned_src) and T11 (src & 3 offset)
    # R22 = T6 + T11 - 4 = T6 - (4 - T11)
    # Body loop advanced T6 but not R22, so we reconstruct here
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T6)     # R22 = T6
    asm.append(f"        .word {const_from_pool(4)}, {ADDR_R22}, .+4")  # R22 = T6 - 4
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T11}, {ADDR_Z}, .+4")      # Z = -T11
    asm.append(f"        .word {ADDR_Z}, {ADDR_R22}, .+4")      # R22 = T6 - 4 + T11
    
    asm.append(".Lmemmove_fwd_slow_loop_body:")
    emit_copy_z_dirty(asm, ADDR_T8, ADDR_R21)
    emit_copy_z_dirty(asm, ADDR_T9, ADDR_R22)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_R22)
    
    emit_call_sequence(asm, ".Lmemmove_fwd_lb_ret", "__subleq_lb")
    
    # sb_nomask: R22 = byte (R20), R21 = dest (T8)
    emit_copy_z_clean(asm, ADDR_R22, ADDR_R20)
    emit_copy_z_dirty(asm, ADDR_R21, ADDR_T8)
    
    emit_call_sequence(asm, ".Lmemmove_fwd_sb_ret", "__subleq_sb_nomask")
    
    emit_copy_z_clean(asm, ADDR_R21, ADDR_T8)
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T9)
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
    asm.append(f"        .word {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")
    # Fused n-- with done check: saves 2 ops/byte vs jumping through _early
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lmemmove_done")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_fwd_slow_loop_body")


    asm.append(".Lmemmove_done:")
    # Restore return value: R20 = T10 (original dest)
    asm.append(f"        .word {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T10}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_R20}, .+4")
    emit_pop_ra(asm)
    asm.extend(emit_return_sequence("memmove"))
    
    # Constants
    
    # Debug constant for unaligned path indicator
    asm.append("        .word 37")  # ASCII '%'
    asm.append("        .word 42")  # ASCII '*'
    asm.append("        .word 35")  # ASCII '#'
    asm.append("        .word 64")  # ASCII '@'
    asm.append("        .word 42")  # ASCII '*'
    asm.append("        .word 37")  # ASCII '%'

    # Return address constants (positive for negated-RA calling convention)
    # Backward slow head path (split-entry sb, generic lb)
    asm.append(".Lmemmove_bwo_lb2_ret_neg:")
    asm.append(f"        .word -.Lmemmove_bwo_lb2_ret")
    asm.append(".Lmemmove_bwo_sb2_ret_neg:")
    asm.append(f"        .word -.Lmemmove_bwo_sb2_ret")
    asm.append(".Lmemmove_bwo_lb1_ret_neg:")
    asm.append(f"        .word -.Lmemmove_bwo_lb1_ret")
    asm.append(".Lmemmove_bwo_sb1_ret_neg:")
    asm.append(f"        .word -.Lmemmove_bwo_sb1_ret")
    asm.append(".Lmemmove_bwo_lb0_ret_neg:")
    asm.append(f"        .word -.Lmemmove_bwo_lb0_ret")
    asm.append(".Lmemmove_bwo_sb0_ret_neg:")
    asm.append(f"        .word -.Lmemmove_bwo_sb0_ret")
    # Backward generic tail path (unaligned exit)
    asm.append(".Lmemmove_bwd_gtail_lb_ret_neg:")
    asm.append(f"        .word -.Lmemmove_bwd_gtail_lb_ret")
    asm.append(".Lmemmove_bwd_gtail_sb_ret_neg:")
    asm.append(f"        .word -.Lmemmove_bwd_gtail_sb_ret")
    # Backward fast tail path (split-entry)
    asm.append(".Lmemmove_btail_lb2_ret_neg:")
    asm.append(f"        .word -.Lmemmove_btail_lb2_ret")
    asm.append(".Lmemmove_btail_sb2_ret_neg:")
    asm.append(f"        .word -.Lmemmove_btail_sb2_ret")
    asm.append(".Lmemmove_btail_lb1_ret_neg:")
    asm.append(f"        .word -.Lmemmove_btail_lb1_ret")
    asm.append(".Lmemmove_btail_sb1_ret_neg:")
    asm.append(f"        .word -.Lmemmove_btail_sb1_ret")
    asm.append(".Lmemmove_btail_lb0_ret_neg:")
    asm.append(f"        .word -.Lmemmove_btail_lb0_ret")
    asm.append(".Lmemmove_btail_sb0_ret_neg:")
    asm.append(f"        .word -.Lmemmove_btail_sb0_ret")
    # Backward fast head path (split-entry)
    asm.append(".Lmemmove_bhead_lb3_ret_neg:")
    asm.append(f"        .word -.Lmemmove_bhead_lb3_ret")
    asm.append(".Lmemmove_bhead_sb3_ret_neg:")
    asm.append(f"        .word -.Lmemmove_bhead_sb3_ret")
    asm.append(".Lmemmove_bhead_lb2_ret_neg:")
    asm.append(f"        .word -.Lmemmove_bhead_lb2_ret")
    asm.append(".Lmemmove_bhead_sb2_ret_neg:")
    asm.append(f"        .word -.Lmemmove_bhead_sb2_ret")
    asm.append(".Lmemmove_bhead_lb1_ret_neg:")
    asm.append(f"        .word -.Lmemmove_bhead_lb1_ret")
    asm.append(".Lmemmove_bhead_sb1_ret_neg:")
    asm.append(f"        .word -.Lmemmove_bhead_sb1_ret")
    # Forward fast path (split-entry head)
    asm.append(".Lmemmove_fhead_lb1_ret_neg:")
    asm.append(f"        .word -.Lmemmove_fhead_lb1_ret")
    asm.append(".Lmemmove_fhead_sb1_ret_neg:")
    asm.append(f"        .word -.Lmemmove_fhead_sb1_ret")
    asm.append(".Lmemmove_fhead_lb2_ret_neg:")
    asm.append(f"        .word -.Lmemmove_fhead_lb2_ret")
    asm.append(".Lmemmove_fhead_sb2_ret_neg:")
    asm.append(f"        .word -.Lmemmove_fhead_sb2_ret")
    asm.append(".Lmemmove_fhead_lb3_ret_neg:")
    asm.append(f"        .word -.Lmemmove_fhead_lb3_ret")
    asm.append(".Lmemmove_fhead_sb3_ret_neg:")
    asm.append(f"        .word -.Lmemmove_fhead_sb3_ret")
    asm.append(".Lmemmove_tail_lb0_ret_neg:")
    asm.append(f"        .word -.Lmemmove_tail_lb0_ret")
    asm.append(".Lmemmove_tail_sb0_ret_neg:")
    asm.append(f"        .word -.Lmemmove_tail_sb0_ret")
    asm.append(".Lmemmove_tail_lb1_ret_neg:")
    asm.append(f"        .word -.Lmemmove_tail_lb1_ret")
    asm.append(".Lmemmove_tail_sb1_ret_neg:")
    asm.append(f"        .word -.Lmemmove_tail_sb1_ret")
    asm.append(".Lmemmove_tail_lb2_ret_neg:")
    asm.append(f"        .word -.Lmemmove_tail_lb2_ret")
    asm.append(".Lmemmove_tail_sb2_ret_neg:")
    asm.append(f"        .word -.Lmemmove_tail_sb2_ret")
    # Forward slow path
    asm.append(".Lmemmove_fwd_lb_ret_neg:")
    asm.append(f"        .word -.Lmemmove_fwd_lb_ret")
    asm.append(".Lmemmove_fwd_sb_ret_neg:")
    asm.append(f"        .word -.Lmemmove_fwd_sb_ret")
    asm.append("")
    # Optimized unaligned head path constants (split-entry sb, generic lb)
    asm.append(".Lmemmove_uhead_lb1_ret_neg:")
    asm.append(f"        .word -.Lmemmove_uhead_lb1_ret")
    asm.append(".Lmemmove_uhead_sb1_ret_neg:")
    asm.append(f"        .word -.Lmemmove_uhead_sb1_ret")
    asm.append(".Lmemmove_uhead_lb2_ret_neg:")
    asm.append(f"        .word -.Lmemmove_uhead_lb2_ret")
    asm.append(".Lmemmove_uhead_sb2_ret_neg:")
    asm.append(f"        .word -.Lmemmove_uhead_sb2_ret")
    asm.append(".Lmemmove_uhead_lb3_ret_neg:")
    asm.append(f"        .word -.Lmemmove_uhead_lb3_ret")
    asm.append(".Lmemmove_uhead_sb3_ret_neg:")
    asm.append(f"        .word -.Lmemmove_uhead_sb3_ret")
    # Note: srl_ret constants removed since srl is now fully inline

    asm.append("        .size __subleq_memmove, . - __subleq_memmove")
    
    return asm


def emit_memset32():
    """Generate __subleq_memset32: word-aligned memset for u32 values.
    
    void *memset32(uint32_t *s, uint32_t v, size_t count)
    Input: R21=s, R22=v, R23=count (number of u32 elements)
    Output: R20=s (original pointer)
    
    Since s is a uint32_t pointer, it's guaranteed word-aligned.
    Each store is a direct word store (~6 steps), vs ~80 steps for sh.
    
    Algorithm:
    1. Save dest for return value
    2. Precompute -v for store pattern
    3. Speculative 16x-unrolled body loop
    4. Single-word fixup loop
    """
    asm = []
    asm.append("")
    asm.append("        .globl  __subleq_memset32")
    asm.append("        .type   __subleq_memset32,@function")
    asm.append("# __subleq_memset32(s=R21, v=R22, count=R23) returns R20=s")
    asm.append("__subleq_memset32:")
    
    # Save dest to R20 for return value
    emit_copy_z_clean(asm, ADDR_R20, ADDR_R21)  # R20 = R21 (dest)
    
    # Check if count <= 0
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lms32_done")
    
    # Precompute T0 = -v for store pattern
    asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word {ADDR_R22}, {ADDR_T0}, .+4")  # T0 = -v
    
    # Body loop: speculative 16x unroll
    asm.append(".Lms32_body_loop:")
    asm.append(f"        .word {const_from_pool(16)}, {ADDR_R23}, .Lms32_body_fixup")
    
    # 16 word stores
    for _ in range(16):
        asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        asm.append(f"        .word {ADDR_T0}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R21}, .+4")
    
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lms32_body_loop")
    
    # Fixup: add 16 back
    asm.append(".Lms32_body_fixup:")
    asm.append(f"        .word {const_from_pool(-16)}, {ADDR_R23}, .+4")
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lms32_done")
    
    # Single-word loop
    asm.append(".Lms32_body_single:")
    asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
    asm.append(f"        .word {ADDR_T0}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
    asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R21}, .+4")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .Lms32_done")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lms32_body_single")
    
    # Done
    asm.append(".Lms32_done:")
    asm.extend(emit_return_sequence("memset32"))
    
    # Constants
    asm.append("")
    asm.append("        .size __subleq_memset32, . - __subleq_memset32")
    
    return asm


def emit_memset16():
    """Generate __subleq_memset16: halfword-width memset using word stores.
    
    void *memset16(uint16_t *s, uint16_t v, size_t count)
    Input: R21=s, R22=v, R23=count (number of u16 elements)
    Output: R20=s (original pointer)
    
    Algorithm:
    1. Save dest for return value
    2. Pack v into u32: v32 = (v << 16) | v  using inline SHL16
    3. Handle leading unaligned halfword (if s & 2): __subleq_sh
    4. Body: word stores using v32 pattern (same as memset32)
    5. Handle trailing halfword: __subleq_sh
    
    The packing converts halfword stores (~80 steps each) to word stores
    (~6 steps each), giving ~27x speedup for the bulk body.
    """
    asm = []
    asm.append("")
    asm.append("        .globl  __subleq_memset16")
    asm.append("        .type   __subleq_memset16,@function")
    asm.append("# __subleq_memset16(s=R21, v=R22, count=R23) returns R20=s")
    asm.append("__subleq_memset16:")
    emit_push_ra(asm)
    
    # Save dest to R20 for return value, and T10 for survival across calls
    emit_copy_z_clean(asm, ADDR_R20, ADDR_R21)  # R20 = dest
    emit_copy_z_dirty(asm, ADDR_T10, ADDR_R21)   # T10 = dest (survives calls)
    
    # Check if count <= 0 (Z dead — next use overwrites)
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lms16_done")
    
    # Save v (R22) to T9 for potential sh calls later
    # NOTE: Word pattern (T0/T1) is computed AFTER alignment head path
    # because __subleq_sh clobbers T0-T6.
    emit_copy_z_dirty(asm, ADDR_T9, ADDR_R22)  # T9 = v
    
    # ============================================================
    # CHECK ALIGNMENT: if (s & 2), handle leading halfword
    # ============================================================
    # Copy R21 to T5 to check bit 1
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_T5}, .+4")  # T5 = R21
    # Check bit 1 of T5 inline: subtract 2, if result < 0 bit was 0
    # Actually, use a simpler approach: lattice mod for & 3, check if result & 2
    # Even simpler: check bit 1 directly
    # T5 = dest. We need to test bit 1.
    # Use the sign-bit trick: clear all bits except bit 1, then test.
    # Clear bits 31..2: subtract powers of 2 if set (same as memset mask)
    # This is overkill. Since we only need bit 1:
    # T5 = dest. Clear bit 31 if set: 
    # Actually simplest: use emit_lattice_mod for & 3, then check if >= 2
    emit_lattice_mod(asm, ADDR_T5, ADDR_T5, ADDR_T6, ".Lms16_align", ".Lms16_")
    # T5 = dest & 3. If bit 1 set (T5 >= 2), need leading halfword
    # Test: T5 - 2 <= 0 means T5 <= 1, aligned for u16[2] → word-aligned
    # Wait, actually for u16 alignment we only need bit 1 to be 0 for word-alignment.
    # If dest & 3 == 0: word-aligned, skip head
    # If dest & 3 == 2: halfword-aligned but not word-aligned, need 1 sh
    # If dest & 3 == 1 or 3: byte-misaligned, shouldn't happen for u16*
    # So just check: if T5 == 0, skip head; else (T5 == 2), do one sh
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T5}, .Lms16_body_setup")
    # T5 > 0, meaning T5 == 2 (half-word aligned but not word-aligned)
    # Store one halfword using __subleq_sh
    # R21 = dest (already correct), R22 = v (already correct)
    # Save R23 to T8 (count, survives call)
    emit_copy_z_dirty(asm, ADDR_T8, ADDR_R23)  # T8 = count
    emit_copy_z_dirty(asm, ADDR_T11, ADDR_R21) # T11 = dest
    
    # Call __subleq_sh(addr=R21, val=R22)
    emit_call_sequence(asm, ".Lms16_head_sh_ret", "__subleq_sh")
    
    # Restore registers
    emit_copy_z_clean(asm, ADDR_R21, ADDR_T11) # R21 = dest
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T9)  # R22 = v (from T9)
    emit_copy_z_dirty(asm, ADDR_R23, ADDR_T8)  # R23 = count
    # dest += 2, count -= 1
    asm.append(f"        .word {const_from_pool(-2)}, {ADDR_R21}, .+4")
    asm.append(f"        .word {ADDR_ONE}, {ADDR_R23}, .+4")
    
    # ============================================================
    # BODY: word stores, count/2 words
    # ============================================================
    asm.append(".Lms16_body_setup:")
    
    # Build word pattern NOW (after alignment head which may call __subleq_sh).
    # Use T9 (saved v) since R22 may be clobbered by __subleq_sh.
    # T1 = (v << 16) | v
    emit_copy_z_dirty(asm, ADDR_T1, ADDR_T9)  # T1 = v
    emit_inline_shl(asm, ADDR_T9, ADDR_T2, 16, ".Lms16_shl16")  # T2 = v<<16
    # T1 += T2 → T1 = (v << 16) | v
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T2}, {ADDR_Z}, .+4")   # Z = -T2
    asm.append(f"        .word {ADDR_Z}, {ADDR_T1}, .+4")   # T1 += T2
    # T0 = -pattern for store loop
    asm.append(f"        .word {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word {ADDR_T1}, {ADDR_T0}, .+4")  # T0 = -pattern
    
    # T7 = count / 2 (number of word stores)
    # Inline SRL by 1: use the lattice
    emit_copy_z_dirty(asm, ADDR_T5, ADDR_R23)  # T5 = count
    emit_inline_srl(asm, ADDR_T5, ADDR_T7, 1, ".Lms16_srl1", ".Lms16_")
    # T7 = count >> 1 = number of word stores
    
    # Check T7 <= 0 → go to tail
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T7}, .Lms16_tail_check")
    
    # Speculative 16x unrolled body  
    asm.append(".Lms16_body_loop:")
    asm.append(f"        .word {const_from_pool(16)}, {ADDR_T7}, .Lms16_body_fixup")
    
    for _ in range(16):
        asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        asm.append(f"        .word {ADDR_T0}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
        asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R21}, .+4")  # R21 += 4
    
    # count -= 32 (16 words = 32 u16)
    asm.append(f"        .word {const_from_pool(32)}, {ADDR_R23}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lms16_body_loop")
    
    # Fixup
    asm.append(".Lms16_body_fixup:")
    asm.append(f"        .word {const_from_pool(-16)}, {ADDR_T7}, .+4")
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T7}, .Lms16_tail_check")
    
    # Single word store loop
    asm.append(".Lms16_body_single:")
    asm.append(f"        .word {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
    asm.append(f"        .word {ADDR_T0}, {ADDR_R21 | INDIRECT_FLAG}, .+4")
    asm.append(f"        .word {const_from_pool(-4)}, {ADDR_R21}, .+4")
    asm.append(f"        .word {const_from_pool(2)}, {ADDR_R23}, .+4")  # count -= 2
    asm.append(f"        .word {ADDR_ONE}, {ADDR_T7}, .Lms16_tail_check")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lms16_body_single")
    
    # ============================================================
    # TAIL: handle trailing halfword if count was odd
    # ============================================================
    asm.append(".Lms16_tail_check:")
    # Check if count <= 0 (all consumed)
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lms16_done")
    # count > 0: one remaining halfword, store via __subleq_sh
    # R21 = current dest, R22 may be clobbered, restore from T9
    emit_copy_z_dirty(asm, ADDR_R22, ADDR_T9)  # R22 = v
    
    # Call __subleq_sh(addr=R21, val=R22)
    emit_call_sequence(asm, ".Lms16_tail_sh_ret", "__subleq_sh")
    
    
    # Done: restore R20 from T10 (original dest)
    asm.append(".Lms16_done:")
    asm.append(f"        .word {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_T10}, {ADDR_Z}, .+4")
    asm.append(f"        .word {ADDR_Z}, {ADDR_R20}, .+4")
    emit_pop_ra(asm)
    asm.extend(emit_return_sequence("memset16"))
    

    # Return address constants (positive for negated-RA calling convention)
    asm.append(".Lms16_head_sh_ret_neg:")
    asm.append("        .word -.Lms16_head_sh_ret")
    asm.append(".Lms16_tail_sh_ret_neg:")
    asm.append("        .word -.Lms16_tail_sh_ret")
    asm.append("")
    asm.append("        .size __subleq_memset16, . - __subleq_memset16")
    
    return asm


def emit_memcpy_aligned():
    """Generate __subleq_memcpy_aligned as alias for __subleq_memmove_aligned."""
    asm = []
    asm.append("")
    asm.append("        .globl  __subleq_memcpy_aligned")
    asm.append("        .type   __subleq_memcpy_aligned,@function")
    asm.append("# __subleq_memcpy_aligned(dest=R21, src=R22, n=R23) returns R20=dest")
    asm.append("# PRECONDITION: dest and src are both word-aligned (& 3 == 0)")
    asm.append("__subleq_memcpy_aligned:")
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, __subleq_memmove_aligned")
    asm.append("")
    asm.append("        .size __subleq_memcpy_aligned, . - __subleq_memcpy_aligned")
    return asm


def emit_memmove_aligned():
    """Generate __subleq_memmove_aligned entry point.
    
    PRECONDITION: dest (R21) and src (R22) are both word-aligned.
    This means (dest-src) & 3 == 0 is guaranteed, so we skip:
    1. The lattice_mod alignment compatibility check (~65 ops)
    2. The head/tail byte-alignment loops (0+ ops per byte)
    3. The head/tail lattice_mod checks (~65 ops each)
    
    For forward: jump directly to .Lmemmove_fwd_body_setup
    For backward: adjust pointers to end, jump to .Lmemmove_bwd_body_setup
    """
    asm = []
    asm.append("")
    asm.append("        .globl  __subleq_memmove_aligned")
    asm.append("        .type   __subleq_memmove_aligned,@function")
    asm.append("# __subleq_memmove_aligned(dest=R21, src=R22, n=R23) returns R20=dest")
    asm.append("# PRECONDITION: dest and src are word-aligned (& 3 == 0)")
    asm.append("# Skips alignment lattice + head/tail byte loops")
    asm.append("__subleq_memmove_aligned:")
    emit_push_ra(asm)
    
    # Save dest to T10 (same as normal memmove entry)
    # Z is clean at entry (caller convention)
    emit_copy_z_clean(asm, ADDR_T10, ADDR_R21)  # T10 = dest (3 insn)
    
    # Check if n <= 0, done immediately
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lmemmove_done")
    
    # Direction check: if dest <= src, forward copy
    # Compute T0 = dest - src
    emit_copy_z_dirty(asm, ADDR_T0, ADDR_R21)  # T0 = dest
    asm.append(f"        .word {ADDR_R22}, {ADDR_T0}, .+4")  # T0 = dest - src
    
    # If T0 <= 0 (dest <= src): forward copy
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_T0}, .Lmemmove_fwd_body_setup")
    
    # Backward copy: both are word-aligned, so point to last WORD
    # src += n - 4, dest += n - 4 (point to start of last word)
    # Then jump to .Lmemmove_bwd_body_setup which does NOT subtract 3
    # (unlike bwd_fast_tail which does)
    #
    # Actually, bwd_body_setup (line 1432) DOES subtract 3. That's because
    # the tail phase left pointers at last byte. We need to point to last
    # byte + 1 for body_setup to work correctly.
    # 
    # Since both aligned: use bwd_fast_setup which does proper pointer
    # adjustment then runs the tail phase (which exits immediately since
    # both are aligned, (src+1)&3 = (word_aligned + n - 1 + 1)&3 = n&3).
    # But we want to avoid the tail lattice_mod too.
    #
    # Cleanest approach: compute end pointers ourselves and skip straight
    # to bwd_body_setup. We need R22 and R21 pointing to start of last word.
    # src_end = src + n - 4, dest_end = dest + n - 4
    # Tail bytes (n & 3) need handling. But body loop handles n>>2 words
    # and then bwd_head_setup handles remaining bytes.
    #
    # Actually, bwd_body_setup subtracts 3 because it was designed for
    # pointers at last byte position. Let me just jump to bwd_fast_setup
    # which skips only the first lattice_mod. The tail lattice is still
    # ~65 ops but tail phase itself won't find bytes to copy since both
    # are word-aligned (when n >= 4, the tail exits immediately with 0 bytes).
    #
    # Wait, the tail checks (src+1)&3. If src is word-aligned and we did
    # src += n-1, then src+1 = orig_src + n. If n is a multiple of 4,
    # (src+1)&3 = 0, tail exits. If n%4 != 0, tail copies n%4 bytes.
    # So the tail IS needed for non-multiple-of-4 sizes.
    #
    # Best approach: jump to bwd_fast_setup. We save ~65 ops from the
    # direction-level lattice_mod.
    asm.append(f"        .word {ADDR_Z}, {ADDR_Z}, .Lmemmove_bwd_fast_setup")
    
    asm.append("")
    asm.append("        .size __subleq_memmove_aligned, . - __subleq_memmove_aligned")
    return asm


def emit_memset_aligned():
    """Generate __subleq_memset_aligned entry point.
    
    PRECONDITION: dest (R21) is word-aligned.
    This means we skip:
    1. The head-phase alignment lattice_mod check (~65 ops)
    2. The head byte-by-byte loop (0-3 sb calls)
    
    Jump directly to body setup after pattern computation.
    """
    asm = []
    asm.append("")
    asm.append("        .globl  __subleq_memset_aligned")
    asm.append("        .type   __subleq_memset_aligned,@function")
    asm.append("# __subleq_memset_aligned(dest=R21, c=R22, n=R23) returns R20=dest")
    asm.append("# PRECONDITION: dest is word-aligned (& 3 == 0)")
    asm.append("# Skips head-phase alignment check and byte loop")
    asm.append("__subleq_memset_aligned:")
    emit_push_ra(asm)
    
    # Same preamble as normal memset:
    # Save dest to R20 and T10
    emit_copy_z_dirty(asm, ADDR_R20, ADDR_R21)  # R20 = dest (4 insn), Z = -R21
    asm.append(f"        .word {ADDR_T10}, {ADDR_T10}, .+4")    # T10 = 0
    asm.append(f"        .word {ADDR_Z}, {ADDR_T10}, .+4")      # T10 -= Z = R21
    
    # Check if n <= 0, done immediately (Z dead — next use overwrites)
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R23}, .Lmemset_done")
    
    # Fast zero check (same as normal memset)
    asm.append(f"        .word {ADDR_ZERO}, {ADDR_R22}, .Lmemset_aligned_check_zero")
    # c > 0: go to normal path (skip head, go to body)
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .Lmemset_aligned_normal_path")
    asm.append(".Lmemset_aligned_check_zero:")
    # c <= 0: check if c == 0
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .+4")
    asm.append(f"        .word {ADDR_R22}, {ADDR_T5}, .Lmemset_fz_body_setup")  # T5 = -c; if -c > 0 then c < 0
    # -c > 0 means c < 0, so c != 0
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .Lmemset_aligned_normal_path")
    
    # c != 0: Need byte masking + pattern, then skip to body_setup
    # Jump to the normal masking code, but after masking, go to body_setup
    # instead of head. The simplest: jump to .Lmemset_normal_path_start
    # which does masking and then falls through to .Lmemset_head.
    # Since dest IS aligned, the lattice_mod returns 0 and we go to
    # body_setup. We still pay ~65 ops for the lattice, but we avoid it
    # by jumping past the head entirely.
    #
    # For maximum savings: jump to normal_path_start and accept the ~65 ops
    # lattice cost. The masking cannot be skipped regardless.
    asm.append(".Lmemset_aligned_normal_path:")
    asm.append(f"        .word {ADDR_T5}, {ADDR_T5}, .Lmemset_normal_path_start")
    
    asm.append("")
    asm.append("        .size __subleq_memset_aligned, . - __subleq_memset_aligned")
    return asm


def emit_memory_ops():
    """Generate all memory operation functions."""
    asm = []
    asm.extend(emit_memcpy())
    asm.extend(emit_memcpy_aligned())
    asm.extend(emit_memset())
    asm.extend(emit_memset_aligned())
    asm.extend(emit_memset32())
    asm.extend(emit_memset16())
    asm.extend(emit_memmove())
    asm.extend(emit_memmove_aligned())
    return asm


if __name__ == "__main__":
    for line in emit_memory_ops():
        print(line)

