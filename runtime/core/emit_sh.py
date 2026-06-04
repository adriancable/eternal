#!/usr/bin/env python3
"""
Subleq runtime function: Store Halfword with true halfword packing

OPTIMIZATION:
- Uses Biased Non-Restoring Lattice to extract bits from Word (T3), clearing the target halfword.
- Directly adds unrolled shifted halfword (R22 << shift) to result.
- Operates on R21 (address) and R22 (halfword value) directly — no entry copies.
- Replaces loop-based masking with O(1) Lattice extraction + O(1) Unrolled Shift.
"""

from gen_runtime import ADDR_Z, ADDR_ZERO, ADDR_R20, ADDR_R21, ADDR_R22, ADDR_T0, ADDR_T1, ADDR_T2, ADDR_T3, ADDR_T4, ADDR_T5, ADDR_T6, INDIRECT_FLAG, emit_return_sequence, const_from_pool, ADDR_ONE, ADDR_MINUS_ONE

def emit_lattice_mask_insert_sh(asm, high_half, prefix):
    """
    Generate Biased Non-Restoring Lattice code to:
    1. Extract T3 into T4 (Result), SKIPPING bits in the target halfword range.
    2. Add shifted T1 (New Halfword) into T4.
    
    Arguments:
    - high_half: False (Low, bits 0-15), True (High, bits 16-31)
    """
    
    # Define range to SKIP (the target range)
    if high_half:
        # Target is High Half (16-31). Skip these. Keep 0-15.
        skip_start = 16
        skip_end = 32
        shift_amount = 16
    else:
        # Target is Low Half (0-15). Skip these. Keep 16-31.
        skip_start = 0
        skip_end = 16
        shift_amount = 0

    def keep_bit(k):
        # We accumulate bit k from T3 ONLY if it is OUTSIDE the target range
        # i.e. we are preserving this bit
        return not (skip_start <= k < skip_end)

    # === Bit 31 (Sign) — OPTIMIZED: 1 op hot path ===
    asm.append(f"{prefix}_sign:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T3}, {prefix}_le0")  # if T3 <= 0, cold path
    # T3 > 0: fall through (HOT PATH — 1 op!)
    
    has_leading_non_accum = not keep_bit(30)  # True when high_half=True
    
    # === Magnitude skip / identity fast path ===
    if has_leading_non_accum:
        # high_half: leading non-accum bits 30..16. Check if T3 < 65536.
        first_accum = 15
        # Z = -T3 invariant: ldword/split-entry sets Z = -T3, sign check preserves it.
        asm.append(f"        .word   {const_from_pool(-65536)}, {ADDR_Z}, {prefix}_full")  # Z += 65536; if <= 0, T3 >= 65536
        # IDENTITY: T3 < 65536, all bits within kept range. T4 = T3.
        asm.append(f"        .word   {const_from_pool(65536)}, {ADDR_Z}, .+4")  # Z -= 65536 = -T3
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T4}, .+4")  # T4 += T3
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_shift")  # clear Z + skip to shift
        
        asm.append(f"{prefix}_full:")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_bias")  # clear Z + jump
    else:
        # Low half: if T3 < 65536, all bits in target [0:16), kept = 0
        # Z = -T3 invariant (same as above)
        asm.append(f"        .word   {const_from_pool(-65536)}, {ADDR_Z}, {prefix}_bias_z")  # Z += 65536; if <= 0, T3 >= 65536
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_shift")  # T4 = 0, shift
        asm.append(f"{prefix}_bias_z:")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_bias")
    
    # === Bias T3 += 1, then Lattice starts at bit 30 (no b30 restoring!) ===
    asm.append(f"{prefix}_bias:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T3}, .+4")
    
    # Determine if we have leading non-accumulating bits.
    # high_half=True (target [16,32)): keep bits 0-15, skip 16-31.
    #   Leading bits 29-16 are non-accumulating (14 bits) → linearize!
    # high_half=False (target [0,16)): keep bits 16-29, skip 0-15.
    #   Leading bits 29-16 ALL accumulate → standard interleaved.
    # has_leading_non_accum already computed above
    
    if has_leading_non_accum:
        # === LINEAR P CHAIN for leading non-accumulating bits 30-16 ===
        # Branch directly to N-state target (no trampoline!)
        first_accum = 15  # first accumulating bit
        
        for bit in range(30, 16, -1):
            power = 1 << bit
            next_N = f"{prefix}_b{bit-1}_N"
            asm.append(f"{prefix}_b{bit}_P:")
            asm.append(f"        .word   {const_from_pool(power)}, {ADDR_T3}, {next_N}")
        
        # Last non-accum P state (bit 16)
        next_N = f"{prefix}_b{first_accum}_N"
        asm.append(f"{prefix}_b16_P:")
        asm.append(f"        .word   {const_from_pool(1 << 16)}, {ADDR_T3}, {next_N}")
        # Fall through to first accumulating P state (bit 15)
        
        # === ACCUMULATING BITS 15-0: interleaved ===
        for bit in range(first_accum, -1, -1):
            power = 1 << bit
            
            if bit == 0:
                next_lbl_P = f"{prefix}_shift"
                next_lbl_N = f"{prefix}_shift"
            else:
                next_lbl_P = f"{prefix}_b{bit-1}_P"
                next_lbl_N = f"{prefix}_b{bit-1}_N"
            
            # P state — branch directly to next_lbl_N (no trampoline!)
            asm.append(f"{prefix}_b{bit}_P:")
            asm.append(f"        .word   {const_from_pool(power)}, {ADDR_T3}, {next_lbl_N}")
            asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_T4}, .+4")
            if bit > 0:
                nb = bit - 1
                nb_power = 1 << nb
                if nb == 0:
                    inl_P = f"{prefix}_shift"
                    inl_N = f"{prefix}_shift"
                else:
                    inl_P = f"{prefix}_b{nb-1}_P"
                    inl_N = f"{prefix}_b{nb-1}_N"
                asm.append(f"        .word   {const_from_pool(nb_power)}, {ADDR_T3}, {inl_N}")
                asm.append(f"        .word   {const_from_pool(-nb_power)}, {ADDR_T4}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {inl_P}")
            else:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl_P}")
            
            # N state — branch directly to next_lbl_N (no trampoline!)
            asm.append(f"{prefix}_b{bit}_N:")
            asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_T3}, {next_lbl_N}")
            asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_T4}, .+4")
            # Fallthrough optimization: for bit > 0, next_P is the very next label
            if bit == 0:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl_P}")
        
        # P→N trampolines eliminated: P-chain now branches directly to N states
        
        for bit in range(30, 15, -1):
            power = 1 << bit
            
            if bit == 16:
                next_lbl_P = f"{prefix}_b{first_accum}_P"
                next_lbl_N = f"{prefix}_b{first_accum}_N"
            else:
                next_lbl_P = f"{prefix}_b{bit-1}_P"
                next_lbl_N = f"{prefix}_b{bit-1}_N"
            
            asm.append(f"{prefix}_b{bit}_N:")
            asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_T3}, {next_lbl_N}")
            if bit == 16:
                fab = first_accum
                fab_power = 1 << fab
                if fab == 0:
                    fab_N = f"{prefix}_shift"
                    fab_P = f"{prefix}_shift"
                else:
                    fab_N = f"{prefix}_b{fab-1}_N"
                    fab_P = f"{prefix}_b{fab-1}_P"
                asm.append(f"        .word   {const_from_pool(fab_power)}, {ADDR_T3}, {fab_N}")
                asm.append(f"        .word   {const_from_pool(-fab_power)}, {ADDR_T4}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {fab_P}")
            else:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl_P}")
    
    else:
        # No leading non-accum bits — start at bit 30
        # Bits 15-0 are all in the skip range — terminate lattice at bit 16
        stop_bit = 16
        reachable = {30: {'P'}}
        
        for bit in range(30, stop_bit - 1, -1):
            power = 1 << bit
            do_acc = keep_bit(bit)
            
            if bit == stop_bit:
                next_lbl_P = f"{prefix}_shift"
                next_lbl_N = f"{prefix}_shift"
            else:
                next_lbl_P = f"{prefix}_b{bit-1}_P"
                next_lbl_N = f"{prefix}_b{bit-1}_N"
                
            states = reachable.get(bit, set())
            next_states = set()
            
            if 'P' in states:
                asm.append(f"{prefix}_b{bit}_P:")
                asm.append(f"        .word   {const_from_pool(power)}, {ADDR_T3}, {next_lbl_N}")
                if do_acc:
                    asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_T4}, .+4")
                if 'N' in states and bit > stop_bit:
                    nb = bit - 1
                    nb_power = 1 << nb
                    nb_acc = keep_bit(nb)
                    if nb == stop_bit:
                        inl_P = f"{prefix}_shift"
                        inl_N = f"{prefix}_shift"
                    else:
                        inl_P = f"{prefix}_b{nb-1}_P"
                        inl_N = f"{prefix}_b{nb-1}_N"
                    asm.append(f"        .word   {const_from_pool(nb_power)}, {ADDR_T3}, {inl_N}")
                    if nb_acc:
                        asm.append(f"        .word   {const_from_pool(-nb_power)}, {ADDR_T4}, .+4")
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {inl_P}")
                else:
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl_P}")
                next_states.add('P')
                next_states.add('N')
                
            if 'N' in states:
                asm.append(f"{prefix}_b{bit}_N:")
                asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_T3}, {next_lbl_N}")
                if do_acc:
                    asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_T4}, .+4")
                # Fallthrough optimization: if P was also emitted and not last bit
                if not ('P' in states and bit > stop_bit):
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl_P}")
                next_states.add('P')
                next_states.add('N')
                
            if bit > stop_bit:
                reachable[bit-1] = next_states
            
    # === Cold path: T3 <= 0 (sign bit handling) ===
    # OPTIMIZED: Combined restore+branch (operates on T3 directly)
    accumulate_b31 = keep_bit(31)
    
    asm.append(f"{prefix}_le0:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T3}, {prefix}_neg")  # T3 += 1; if <= 0 → T3 < 0
    # T3 was 0 (now 1): T4 already 0, skip lattice entirely (always branches)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T3}, {prefix}_shift")  # restore+skip
    asm.append(f"{prefix}_neg:")
    # T3 was < 0: restore T3 (always branches via .+4)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T3}, .+4")  # restore+branch
    if accumulate_b31:
        asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_T4}, .+4")
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_T3}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_bias")

    # === Shift and Add New Halfword ===
    asm.append(f"{prefix}_shift:")
    # R22 is halfword value. Shift left by 'shift_amount' and Add to T4.
    
    # Check shift amount
    if shift_amount == 0:
        # Just add R22 to T4
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4") # Z = 0
        asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4") # Z = -R22
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T4}, {prefix}_done") # T4 += R22
    else:
        # LATTICE-BASED SHIFT: Extract R22 bits and directly accumulate
        # 2^(bit+16) into T4. Cost: ~41 ops vs 55 ops for 16× doubling.
        # R22 is modified in-place (dead after shift section).
        
        # R22 == 0 skip: halfword value 0 means nothing to add (R22 masked to [0,65535])
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, {prefix}_done")
        
        # Bias R22 += 1 (no Z dependency)
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
        
        # 16-bit non-restoring lattice: bits 15 down to 0
        for bit in range(15, -1, -1):
            power = 1 << bit
            shifted = bit + shift_amount
            # Accumulate constant: T4 -= npow → T4 += 2^shifted
            if shifted == 31:
                acc_label = f"{const_from_pool(-2147483648)}"
            else:
                acc_label = f"{const_from_pool(-(1 << shifted))}"
            
            if bit == 0:
                next_P = f"{prefix}_done"
                next_N = f"{prefix}_done"
            else:
                next_P = f"{prefix}_sl_b{bit-1}_P"
                next_N = f"{prefix}_sl_b{bit-1}_N"
            
            # P state
            asm.append(f"{prefix}_sl_b{bit}_P:")
            asm.append(f"        .word   {const_from_pool(power)}, {ADDR_R22}, {next_N}")
            asm.append(f"        .word   {acc_label}, {ADDR_T4}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_P}")
            
            # N state
            asm.append(f"{prefix}_sl_b{bit}_N:")
            asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_R22}, {next_N}")
            asm.append(f"        .word   {acc_label}, {ADDR_T4}, .+4")
            # Fallthrough to next P — except at last bit
            if bit == 0:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_P}")
        
    asm.append(f"{prefix}_done:")
    # Fuse store preparation if possible, but we just jump to store
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsh_store")


def emit_sh():
    asm = []
    asm.append(f"")
    asm.append(f"        .globl  __subleq_sh")
    asm.append(f"        .type   __subleq_sh,@function")
    asm.append(f"")
    asm.append(f"# __subleq_sh: Store Halfword - Biased Non-Restoring Lattice")
    asm.append(f"__subleq_sh:")
    
    # R21 = byte address (used directly, no copy to T0)
    # R22 = halfword value (used directly, no copy to T1)
    
    # ===== FAST PATH: Skip masking if R22 is already in [0, 65535] =====
    # If R22 >= 0 and R22 <= 65535, we don't need to mask - go directly to modulo
    # 
    # Check 1: R22 >= 0 (if R22 < 0, need masking for bit 31)
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lsh_fast_chk0")  # if R22 <= 0, check further
    # R22 > 0: continue to check R22 <= 65535
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsh_fast_chk65535")
    
    asm.append(f".Lsh_fast_chk0:")
    # R22 <= 0. Disambiguate R22 = 0 (OK to skip) from R22 < 0 (need mask)
    # If R22 + 1 <= 0, then R22 < 0 (need mask). Special case: INT_MIN + 1 is still < 0, correct!
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
    # SH-A: Z is clean from function entry (subleq(ZERO, R22, ...) doesn't modify Z)
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")  # Z = -R22
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T5}, .+4")  # T5 = R22
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T5}, .Lsh_mask")  # T5 += 1; if <= 0 → R22 < 0 (combined +1-and-test)
    # R22 = 0: fall through to skip mask (0 is valid halfword)
    
    asm.append(f".Lsh_fast_chk65535:")
    # Check 2: R22 - 65535 <= 0 (i.e., R22 <= 65535)
    # Copy R22 to T5, subtract 65535, check if <= 0
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
    # SH-B: Z is clean (cleared by subleq(Z, Z, ...) on all entry paths)
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")  # Z = -R22
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T5}, .+4")  # T5 = R22
    asm.append(f"        .word   {const_from_pool(65535)}, {ADDR_T5}, .Lsh_off")  # T5 = R22 - 65535, if <= 0 skip mask
    # R22 > 65535, fall through to full masking
    
    # ===== MASK R22 to 16 bits using O(16) bit extraction =====
    # LLVM may pass values with garbage in upper 16 bits - we must clear them
    asm.append(f".Lsh_mask:")
    
    # Handle sign bit (bit 31) first - clear if set
    # EDGE CASE: T1 = INT_MIN (-2147483648)
    #   The naive pattern: T5 = -T1, branch if T5 <= 0
    #   Fails because -INT_MIN = INT_MIN (overflow), so T5 <= 0, incorrectly skipping!
    # FIX: Use T1+1 <= 0 pattern (like SubleqAsmPrinter.cpp):
    #   1. Check T1 <= 0 first. If T1 > 0, skip (bit 31 not set)
    #   2. If T1 <= 0, check T1 + 1 <= 0:
    #      - T1 + 1 <= 0 means T1 <= -1, so T1 < 0 (negative, clear bit 31)
    #      - T1 + 1 > 0 means T1 > -1, combined with T1 <= 0, so T1 = 0 (skip)
    # NOTE: T5 self-clear omitted here — both paths (chk31, b30) re-clear T5 before use.
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lsh_mask_chk31")  # branch if R22 <= 0
    # R22 > 0: bit 31 not set, skip to bit 30
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsh_mask_b30")
    asm.append(f".Lsh_mask_chk31:")
    # R22 <= 0: disambiguate R22 = 0 from R22 < 0 using R22 + 1
    # Copy R22 to T5, add 1, check if <= 0
    # SH-C: Removed wasted T5 -= R22 (result immediately clobbered by T5 self-clear)
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")         # T5 = 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")           # Z = 0
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")         # Z = -R22
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T5}, .+4")          # T5 = R22
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T5}, .Lsh_mask_clr31")  # T5 += 1; if <= 0 → R22 < 0 (combined +1-and-test)
    # R22 + 1 > 0: R22 = 0, skip to bit 30
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsh_mask_b30")
    asm.append(f".Lsh_mask_clr31:")
    # R22 < 0: clear bit 31 by subtracting INT_MIN
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R22}, .Lsh_mask_b30")
    
    # Clear bits 30 down to 16 using combined subtract-and-test
    for bit in range(30, 15, -1):
        power = 1 << bit
        next_bit = f".Lsh_mask_b{bit-1}" if bit > 16 else ".Lsh_off"
        asm.append(f".Lsh_mask_b{bit}:")
        # R22 -= power, branch if R22 <= 0
        asm.append(f"        .word   {const_from_pool(power)}, {ADDR_R22}, .Lsh_mask_c{bit}")
        # R22 > 0: bit was set (already cleared), go to next
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_bit}")
        asm.append(f".Lsh_mask_c{bit}:")
        # R22 <= 0: disambiguate R22=0 (bit exactly set) vs R22<0 (bit not set)
        asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
        asm.append(f"        .word   {ADDR_R22}, {ADDR_T5}, {next_bit}")  # T5=-R22, if R22>=0 done
        # R22 < 0: bit NOT set, restore R22 += power
        asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_R22}, {next_bit}")
    
    # Modulo Calculation — addresses are ALWAYS positive
    asm.append(f".Lsh_off:")
    asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T2}, .Lsh_mod_bias")
    
    # === Bias (skip sign check — addresses always positive!) ===
    asm.append(f".Lsh_mod_bias:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T2}, .+4")   # T2 += 1 (bias)
    
    # === LINEAR P CHAIN: bits 30 down to 2 ===
    # Branch directly to N-state targets (no trampolines!)
    for bit in range(30, 2, -1):
        power = 1 << bit
        pow_label = f"{const_from_pool(power)}"
        next_N = f".Lsh_mb{bit-1}_N"
        asm.append(f".Lsh_mb{bit}_P:")
        asm.append(f"        .word   {pow_label}, {ADDR_T2}, {next_N}")
    
    asm.append(f".Lsh_mb2_P:")
    asm.append(f"        .word   {const_from_pool(4)}, {ADDR_T2}, .Lsh_mod_done_n")
    # Fall through to mod_done (P-path: T2 > 0)
    
    # === MODULO DONE ===
    # P-exit: T2 ∈ [1,4]. Unbias: T2 -= 1 → offset [0,3].
    # N-exit: T2 ∈ [-3,0]. Restore+unbias: T2 += 3 → offset [0,3].
    asm.append(f".Lsh_mod_done:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T2}, .Lsh_mod_done_n")  # if T2 ≤ 0 → N path
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T2}, .Lsh_align")           # T2 -= 1 (unbias)
    asm.append(f".Lsh_align:")
    asm.append(f"        .word   {ADDR_T2}, {ADDR_R21}, .+4")  # R21 -= T2 = word_addr
    # Fall through to ldword (no jump needed!)
    
    asm.append(f".Lsh_ldword:")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_T3}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R21 | INDIRECT_FLAG}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T3}, .Lsh_branch")
    
    asm.append(f".Lsh_branch:")
    asm.append(f"        .word   {ADDR_T4}, {ADDR_T4}, .+4") # Clear Result
    
    # Branch based on T2 (0 or 2)
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T2}, .Lsh_h0") # T2 == 0
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_ZERO}, .Lsh_h1")     # Z-preserving unconditional jump
    
    # P→N trampolines eliminated: P-chain now branches directly to N states
    
    # === N STATES with INLINE P: bits 30-2 ===
    for bit in range(30, 2, -1):
        power = 1 << bit
        power_prev = 1 << (bit - 1)
        next_N = f".Lsh_mb{bit-1}_N"
        
        asm.append(f".Lsh_mb{bit}_N:")
        asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_T2}, {next_N}")  # N→N: branch (1 op)
        
        # Inline P_{bit-1}
        if bit - 1 == 2:
            asm.append(f"        .word   {const_from_pool(power_prev)}, {ADDR_T2}, .Lsh_mod_done_n")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsh_mod_done")
        else:
            inline_branch = f".Lsh_mb{bit-2}_N"
            inline_skip = f".Lsh_mb{bit-2}_P"
            asm.append(f"        .word   {const_from_pool(power_prev)}, {ADDR_T2}, {inline_branch}")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {inline_skip}")
    
    # Bit 2: terminal N-state
    asm.append(f".Lsh_mb2_N:")
    asm.append(f"        .word   {const_from_pool(-4)}, {ADDR_T2}, .Lsh_mod_done_n")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsh_mod_done")
    
    # === N-exit cold path: restore + unbias + align ===
    asm.append(f".Lsh_mod_done_n:")
    asm.append(f"        .word   {const_from_pool(-3)}, {ADDR_T2}, .+4")        # T2 += 3 (restore+unbias)
    asm.append(f"        .word   {ADDR_T2}, {ADDR_R21}, .+4")        # R21 -= T2 = word_addr
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsh_ldword")   # jump to ldword

    # ========== SPLIT ENTRY POINTS (known halfword offset) ==========
    # __subleq_sh_h{0,1}: R21 = word-aligned byte address, R22 = halfword value
    # Skips the entire modulo lattice (~40 ops saved per call).
    # OPTIMIZED: Entry falls through to fast-check (no jump, saves 1 op).
    # Merged range check: compute T5=R22 once, check ≤0 then ≤65535 (saves 1 op).
    for half_pos in range(2):
        target_offset = half_pos * 2  # 0 or 2
        asm.append(f"")
        asm.append(f"        .globl  __subleq_sh_h{half_pos}")
        asm.append(f"__subleq_sh_h{half_pos}:")
        # Set T2 = offset (0 or 2) so modulo result is pre-computed
        asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")      # T2 = 0
        if target_offset != 0:
            asm.append(f"        .word   {const_from_pool(-target_offset)}, {ADDR_T2}, .+4") # T2 = offset
        # Fall through to fast-check (no jump needed! Z clean at entry)
        
        mask_split_target = f".Lsh_mask_split{half_pos}" if half_pos > 0 else ".Lsh_mask"
        
        # Merged R22 range check (Z clean from entry):
        # Compute T5 = R22 once, then check ≤0 and ≤65535 sequentially.
        asm.append(f".Lsh_fast_chk0_split{half_pos}:")
        asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")                                  # Z = -R22 (Z was clean)
        asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")                                  # T5 = 0
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T5}, .+4")                                   # T5 = R22
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T5}, .Lsh_fast_le0_s{half_pos}")          # if R22 ≤ 0, check further
        asm.append(f"        .word   {const_from_pool(65535)}, {ADDR_T5}, .Lsh_ldword")            # if R22 ≤ 65535, done → ldword
        # R22 > 65535: need masking
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {mask_split_target}")

        asm.append(f".Lsh_fast_le0_s{half_pos}:")
        # T5 = R22 ≤ 0. Check R22 = 0 (ok) vs R22 < 0 (mask).
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T5}, {mask_split_target}")   # T5 += 1; if ≤ 0 → R22 < 0, mask
        # R22 = 0: go to ldword
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsh_ldword")

        if half_pos > 0:
            asm.append(f".Lsh_mask_split{half_pos}:")
            # Need to mask R22 - jump to the existing mask code.
            # After masking, .Lsh_mask falls through to .Lsh_off (modulo computation).
            # For h0: R21 is word-aligned, modulo gives T2=0 — correct.
            # For h1: R21 is word-aligned, modulo gives T2=0 — WRONG (need T2=2).
            # Fix for h1: add target_offset to R21 before masking so modulo
            # correctly computes T2=2 from the un-aligned address.
            if target_offset != 0:
                asm.append(f"        .word   {const_from_pool(-target_offset)}, {ADDR_R21}, .+4")  # R21 += target_offset
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsh_mask")
    
    # Low Half (0-15)
    asm.append(f".Lsh_h0:")
    emit_lattice_mask_insert_sh(asm, False, ".Lsh_b0")

    # High Half (16-31)
    asm.append(f".Lsh_h1:")
    emit_lattice_mask_insert_sh(asm, True, ".Lsh_b1")
    
    # Store (Z clean from handler exit: all handlers jump via Z,Z,.Lsh_store)
    asm.append(f".Lsh_store:")
    asm.append(f"        .word   {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")  # mem[R21] = 0
    asm.append(f"        .word   {ADDR_T4}, {ADDR_Z}, .+4")                                     # Z = -T4 (Z was clean)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R21 | INDIRECT_FLAG}, .Lsh_ret")               # mem[R21] = T4; both paths reach ret
    
    asm.append(f".Lsh_ret:")
    asm.extend(emit_return_sequence("sh"))
    

        
    asm.append(f"")
    asm.append(f"        .size   __subleq_sh, . - __subleq_sh")
    
    return asm

if __name__ == "__main__":
    for line in emit_sh():
        print(line)
