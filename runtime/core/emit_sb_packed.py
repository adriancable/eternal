#!/usr/bin/env python3
"""
Subleq runtime function: emit_sb with true byte packing

OPTIMIZATION:
- Uses Biased Non-Restoring Lattice to extract bits from Word (T3), clearing the target byte range.
- Directly adds unrolled shifted byte (R22 << shift) to result.
- Operates on R21 (address) and R22 (byte value) directly — no entry copies.
- Replaces loop-based masking with O(1) Lattice extraction + O(1) Unrolled Shift.
"""

from gen_runtime import ADDR_Z, ADDR_ZERO, ADDR_R20, ADDR_R21, ADDR_R22, ADDR_T0, ADDR_T1, ADDR_T2, ADDR_T3, ADDR_T4, ADDR_T5, ADDR_T6, INDIRECT_FLAG, emit_return_sequence, const_from_pool, ADDR_ONE, ADDR_MINUS_ONE

def emit_lattice_mask_insert(asm, byte_pos, prefix):
    """
    Generate Biased Non-Restoring Lattice code to:
    1. Extract T3 into T4 (Result), SKIPPING bits in the target byte range.
    2. Add shifted R22 (New Byte) into T4.
    """
    shift_amount = byte_pos * 8
    target_start = shift_amount
    target_end = shift_amount + 8 # exclusive

    def keep_bit(k):
        # We accumulate bit k from T3 ONLY if it is OUTSIDE the target byte range
        return not (target_start <= k < target_end)

    # === Bit 31 (Sign) — OPTIMIZED: 1 op hot path ===
    asm.append(f"{prefix}_sign:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T3}, {prefix}_le0")  # if T3 <= 0, cold path
    # T3 > 0: fall through (HOT PATH — 1 op!)
    
    # === Magnitude skip: if T3 is small, skip leading non-accum lattice ===
    has_leading_non_accum = not keep_bit(30)  # bit 30 in target range
    if has_leading_non_accum:
        # Find first accumulating bit below the leading non-accum range
        first_accum = target_start - 1  # e.g. byte3: target [24,32) → first_accum = 23
        threshold = 1 << (first_accum + 1)  # e.g. byte3: 1<<24 = 16777216
        
        # Z = -T3 invariant: ldword/split-entry sets Z = -T3, sign check preserves it.
        asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_Z}, {prefix}_full")  # Z += threshold; if T3 >= threshold, full
        # T3 < threshold: all bits within kept range. T4 = T3. Skip lattice.
        # Z = -T3 + threshold from check. Subtract threshold to get Z = -T3.
        asm.append(f"        .word   {const_from_pool(threshold)}, {ADDR_Z}, .+4")  # Z -= threshold = -T3
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T4}, .+4")  # T4 += T3
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_shift")  # clear Z + skip to shift → bias + jump to first accum P
        
        asm.append(f"{prefix}_full:")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_bias")  # clear Z + jump
    else:
        # No leading non-accum (bytes 0, 1, 2).
        # Byte 0 identity: if T3 < 256, all bits in target [0,8), kept = 0
        if byte_pos == 0:
            # Z = -T3 invariant (same reasoning as above)
            asm.append(f"        .word   {const_from_pool(-256)}, {ADDR_Z}, {prefix}_bias_z")  # if T3 >= 256, full
            # T3 < 256: kept bits = 0, T4 already 0. Skip to shift.
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_shift")
            asm.append(f"{prefix}_bias_z:")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_bias")
        elif byte_pos in (1, 2):
            # Bytes 1/2: if T3 < 2^target_start, target byte is already zero,
            # kept bits above are zero, kept bits below = T3. T4 = T3, skip lattice.
            skip_threshold = 1 << target_start  # byte1: 256, byte2: 65536
            # Z = -T3 invariant (same reasoning as above)
            asm.append(f"        .word   {const_from_pool(-skip_threshold)}, {ADDR_Z}, {prefix}_bias_z")  # if T3 >= threshold, full
            # T3 < threshold: T4 = T3. Recover Z = -T3 then copy.
            asm.append(f"        .word   {const_from_pool(skip_threshold)}, {ADDR_Z}, .+4")  # Z -= threshold → Z = -T3
            asm.append(f"        .word   {ADDR_Z}, {ADDR_T4}, .+4")  # T4 -= Z → T4 = T3
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_shift")  # clear Z + skip to shift
            asm.append(f"{prefix}_bias_z:")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_bias")
    
    # === Bias T3 += 1, then Lattice starts at bit 30 (no b30 restoring!) ===
    asm.append(f"{prefix}_bias:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T3}, .+4")
    
    # Determine non-accumulating range.
    # NOW starts at bit 30 (was 29) since we eliminated b30 restoring.
    # keep_bit(k) = not (target_start <= k < target_end)
    # Non-accumulating bits are target_start..target_end-1
    #
    # Layout per byte (now including bit 30):
    # - byte 0: target [0,8). keep=True for 30-8, keep=False for 7-0.
    # - byte 1: target [8,16). keep=True for 30-16, keep=False for 15-8, keep=True for 7-0.
    # - byte 2: target [16,24). keep=True for 30-24, keep=False for 23-16, keep=True for 15-0.
    # - byte 3: target [24,32). keep=False for 30-24, keep=True for 23-0.
    
    leading_non_accum_end = min(target_end - 1, 30)  
    leading_non_accum_start = max(target_start, 0)
    
    # has_leading_non_accum already computed above for magnitude skip
    
    if has_leading_non_accum:
        # === LINEAR P CHAIN for leading non-accumulating bits ===
        # Entry: fall through from bias
        # Branch directly to N-state target (no trampoline!)
        for bit in range(30, leading_non_accum_start, -1):
            if keep_bit(bit):
                break  # Stop when we hit an accumulating bit
            power = 1 << bit
            next_N = f"{prefix}_b{bit-1}_N"
            asm.append(f"{prefix}_b{bit}_P:")
            asm.append(f"        .word   {const_from_pool(power)}, {ADDR_T3}, {next_N}")
        
        # Last leading non-accum P state
        if not keep_bit(leading_non_accum_start) and leading_non_accum_start <= 30:
            bit = leading_non_accum_start
            power = 1 << bit
            next_N = f"{prefix}_b{bit - 1}_N"
            asm.append(f"{prefix}_b{bit}_P:")
            asm.append(f"        .word   {const_from_pool(power)}, {ADDR_T3}, {next_N}")
            non_accum_low = bit
        else:
            non_accum_low = 31  # sentinel
        
        # Find first accumulating bit below non-accum range
        first_accum = non_accum_low - 1
        
        # === ACCUMULATING BITS below ===
        reachable = {first_accum: {'P', 'N'}}  # N reachable from trampolines above
        for bit in range(first_accum, -1, -1):
            power = 1 << bit
            do_acc = keep_bit(bit)
            
            if bit == 0:
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
                # INLINE next P's test: replaces Z,Z with useful work
                if 'N' in states and bit > 0:
                    nb = bit - 1
                    nb_power = 1 << nb
                    nb_acc = keep_bit(nb)
                    if nb == 0:
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
                # Fallthrough optimization: if P was also emitted and bit > 0,
                # next_P is the very next label — no jump needed.
                if not ('P' in states and bit > 0):
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl_P}")
                next_states.add('P')
                next_states.add('N')
                
            if bit > 0:
                reachable[bit-1] = next_states
        
        for bit in range(30, non_accum_low - 1, -1):
            if keep_bit(bit):
                break
            power = 1 << bit
            
            if bit == non_accum_low:
                next_lbl_P = f"{prefix}_b{first_accum}_P"
                next_lbl_N = f"{prefix}_b{first_accum}_N"
            else:
                next_lbl_P = f"{prefix}_b{bit-1}_P"
                next_lbl_N = f"{prefix}_b{bit-1}_N"
            
            asm.append(f"{prefix}_b{bit}_N:")
            asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_T3}, {next_lbl_N}")  # N→N
            # N→P: inline next P's test
            if bit == non_accum_low:
                fab = first_accum
                fab_power = 1 << fab
                fab_acc = keep_bit(fab)
                if fab == 0:
                    fab_N = f"{prefix}_shift"
                    fab_P = f"{prefix}_shift"
                else:
                    fab_N = f"{prefix}_b{fab-1}_N"
                    fab_P = f"{prefix}_b{fab-1}_P"
                asm.append(f"        .word   {const_from_pool(fab_power)}, {ADDR_T3}, {fab_N}")
                if fab_acc:
                    asm.append(f"        .word   {const_from_pool(-fab_power)}, {ADDR_T4}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {fab_P}")
            else:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl_P}")  # N→P
    
    else:
        # No leading non-accum bits — start at bit 30
        # For byte 0: trailing bits 7-0 are all in skip range — terminate early at bit 8
        stop_bit = target_end if target_start == 0 else 0
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
                # INLINE next P's test
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
    res_bit_31 = 31 - target_start  # for accumulation check
    accumulate_b31 = keep_bit(31)
    
    asm.append(f"{prefix}_le0:")
    # OPTIMIZED: Combined restore+branch (operates on T3 directly)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T3}, {prefix}_neg")  # T3 += 1; if <= 0 → T3 < 0
    # T3 was 0 (now 1): T4 already 0, skip lattice entirely (always branches)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T3}, {prefix}_shift")  # restore+skip
    
    asm.append(f"{prefix}_neg:")
    # T3 was < 0: restore T3 (always branches via .+4)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T3}, .+4")  # restore+branch
    # T3 < 0 (bit 31 set). Clear bit 31.
    if accumulate_b31:
        asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_T4}, .+4")
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_T3}, .+4")  # T3 -= INT_MIN (clear bit 31)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_bias")  # goto bias

    # === Shift and Add New Byte ===
    asm.append(f"{prefix}_shift:")
    # R22 is byte value. Shift left by 'shift_amount' and Add to T4.
    
    # OPTIMIZATION: 51% of SB calls store zero. Skip shift entirely.
    # subleq(ZERO, R22, done) — if R22 <= 0, skip ahead.
    # R22 is already masked to [0,255], so R22 <= 0 means R22 == 0.
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, {prefix}_done")
    
    # Check shift amount
    if shift_amount == 0:
        # Just add R22 to T4
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4") # Z = 0
        asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4") # Z = -R22
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T4}, {prefix}_done") # T4 = T4 - (-T1) = T4 + T1
    else:
        # LATTICE-BASED SHIFT: Extract R22 bits and directly accumulate
        # 2^(bit+shift_amount) into T4. R22 > 0 guaranteed by zero-check above.
        # Cost: ~21 ops (constant) vs 31/55/79 ops for doubling byte 1/2/3.
        # R22 is modified in-place (dead after shift section).
        
        # Bias R22 += 1 (no Z dependency)
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
        
        # 8-bit non-restoring lattice: bits 7 down to 0
        for bit in range(7, -1, -1):
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
            
            # P state: subtract 2^bit; if ≤0 → bit was 0, go to next N
            asm.append(f"{prefix}_sl_b{bit}_P:")
            asm.append(f"        .word   {const_from_pool(power)}, {ADDR_R22}, {next_N}")
            asm.append(f"        .word   {acc_label}, {ADDR_T4}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_P}")
            
            # N state: add 2^bit; if ≤0 → bit was 0, go to next N
            asm.append(f"{prefix}_sl_b{bit}_N:")
            asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_R22}, {next_N}")
            asm.append(f"        .word   {acc_label}, {ADDR_T4}, .+4")
            # Fallthrough to next P (saves 1 op) — except at last bit
            if bit == 0:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_P}")
        
    asm.append(f"{prefix}_done:")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsb_store")


def emit_sb():
    asm = []
    asm.append(f"")
    asm.append(f"        .globl  __subleq_sb")
    asm.append(f"        .type   __subleq_sb,@function")
    asm.append(f"")
    asm.append(f"# __subleq_sb: Store byte - Biased Non-Restoring Lattice")
    asm.append(f"__subleq_sb:")
    
    # R21 = byte address (used directly, no copy to T0)
    # R22 = byte value (used directly, no copy to T1)
    
    # ===== FAST PATH: Skip masking if R22 is already in [0, 255] =====
    # If R22 >= 0 and R22 <= 255, we don't need to mask - go directly to modulo
    # 
    # Check 1: R22 >= 0 (if R22 < 0, need masking for bit 31)
    # Note: subleq only gives us "if X <= 0", so we need to disambiguate R22 = 0 from R22 < 0
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lsb_fast_chk0")  # if R22 <= 0, check further
    # R22 > 0: continue to check R22 <= 255
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsb_fast_chk255")
    
    asm.append(f".Lsb_fast_chk0:")
    # R22 <= 0. Disambiguate R22 = 0 (OK to skip) from R22 < 0 (need mask)
    # If R22 + 1 <= 0, then R22 < 0 (need mask). Special case: INT_MIN + 1 is still < 0, correct!
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
    # Z is clean from function entry (subleq(ZERO, R22, ...) doesn't modify Z)
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")  # Z = -R22
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T5}, .+4")  # T5 = R22
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T5}, .Lsb_mask")  # T5 += 1; if <= 0 → R22 < 0 (combined +1-and-test)
    # R22 = 0: fall through to skip mask (0 is valid byte, 0 - 256 = -256 <= 0, will skip)
    
    asm.append(f".Lsb_fast_chk255:")
    # Check 2: R22 - 255 <= 0 (i.e., R22 <= 255)
    # Copy R22 to T5, subtract 255, check if <= 0
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
    # Z is clean (cleared by subleq(Z, Z, ...) on all entry paths)
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")  # Z = -R22
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T5}, .+4")  # T5 = R22
    asm.append(f"        .word   {const_from_pool(255)}, {ADDR_T5}, .Lsb_off")  # T5 = R22 - 255, if <= 0 skip mask
    # R22 > 255, fall through to full masking
    
    # ===== MASK R22 to 8 bits using O(24) bit extraction =====
    # LLVM may pass values with garbage in upper 24 bits - we must clear them
    asm.append(f".Lsb_mask:")
    
    # Handle sign bit (bit 31) first - clear if set
    # EDGE CASE: R22 = INT_MIN (-2147483648)
    #   The naive pattern: T5 = -R22, branch if T5 <= 0
    #   Fails because -INT_MIN = INT_MIN (overflow), so T5 <= 0, incorrectly skipping!
    # FIX: Use R22+1 <= 0 pattern (like SubleqAsmPrinter.cpp):
    #   1. Check R22 <= 0 first. If R22 > 0, skip (bit 31 not set)
    #   2. If R22 <= 0, check R22 + 1 <= 0:
    #      - R22 + 1 <= 0 means R22 <= -1, so R22 < 0 (negative, clear bit 31)
    #      - R22 + 1 > 0 means R22 > -1, combined with R22 <= 0, so R22 = 0 (skip)
    # NOTE: T5 self-clear omitted here — both paths (chk31, b30) re-clear T5 before use.
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lsb_mask_chk31")  # branch if R22 <= 0
    # R22 > 0: bit 31 not set, skip to bit 30
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsb_mask_b30")
    asm.append(f".Lsb_mask_chk31:")
    # R22 <= 0: disambiguate R22 = 0 from R22 < 0 using R22 + 1
    # Copy R22 to T5, add 1, check if <= 0
    # (Removed wasted T5 -= R22 — result was immediately clobbered by T5 self-clear)
    asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")         # T5 = 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")           # Z = 0
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")         # Z = -R22
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T5}, .+4")          # T5 = R22
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T5}, .Lsb_mask_clr31")  # T5 += 1; if <= 0 → R22 < 0 (combined +1-and-test)
    # R22 + 1 > 0: R22 = 0, skip to bit 30
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsb_mask_b30")
    asm.append(f".Lsb_mask_clr31:")
    # R22 < 0: clear bit 31 by subtracting INT_MIN
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R22}, .Lsb_mask_b30")
    
    # Clear bits 30 down to 8 using combined subtract-and-test
    for bit in range(30, 7, -1):
        power = 1 << bit
        next_bit = f".Lsb_mask_b{bit-1}" if bit > 8 else ".Lsb_off"
        asm.append(f".Lsb_mask_b{bit}:")
        # R22 -= power, branch if R22 <= 0
        asm.append(f"        .word   {const_from_pool(power)}, {ADDR_R22}, .Lsb_mask_c{bit}")
        # R22 > 0: bit was set (already cleared), go to next
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_bit}")
        asm.append(f".Lsb_mask_c{bit}:")
        # R22 <= 0: disambiguate R22=0 (bit exactly set) vs R22<0 (bit not set)
        asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")
        asm.append(f"        .word   {ADDR_R22}, {ADDR_T5}, {next_bit}")  # T5=-R22, if R22>=0 done
        # R22 < 0: bit NOT set, restore R22 += power
        asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_R22}, {next_bit}")
        # For bit 8 (last bit): the restore subleq may not branch if R22 > 0
        # after restore. Must add unconditional jump to prevent falling through
        # to __subleq_sb_nomask which assumes Z-clean entry.
        if bit == 8:
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsb_off")

    
    # === FAST ENTRY: __subleq_sb_nomask ===
    # Callers that guarantee R21 = byte address, R22 ∈ [0,255] can jump here
    # to skip the mask check (10-50 insn).
    # Used by memmove where bytes come from lb (always [0,255]).
    asm.append(f"        .globl  __subleq_sb_nomask")
    asm.append(f"__subleq_sb_nomask:")
    
    # Z-SCRATCH ENTRY: Z is clean at function call entry (caller's return clears it)
    # Saves 1 op vs standard copy (3 ops instead of 4)
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")   # Z = -R21 (Z was 0)
    asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")   # T2 = 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T2}, .Lsb_mod_bias")  # T2 = R21
    
    # Standard entry from masking path (Z is dirty)
    asm.append(f".Lsb_off:")
    asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T2}, .Lsb_mod_bias")
    
    # === Bias (skip sign check — addresses always positive!) ===
    asm.append(f".Lsb_mod_bias:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T2}, .+4")   # T2 += 1 (bias)
    
    # === LINEAR P CHAIN: bits 30 down to 2 ===
    # Branch directly to N-state targets (no trampolines!)
    for bit in range(30, 2, -1):
        power = 1 << bit
        pow_label = f"{const_from_pool(power)}"
        next_N = f".Lsb_mb{bit-1}_N"
        asm.append(f".Lsb_mb{bit}_P:")
        asm.append(f"        .word   {pow_label}, {ADDR_T2}, {next_N}")
    
    asm.append(f".Lsb_mb2_P:")
    asm.append(f"        .word   {const_from_pool(4)}, {ADDR_T2}, .Lsb_mod_done_n")
    # Fall through to mod_done (P-path: T2 > 0)
    
    # === MODULO DONE ===
    # P-exit: T2 ∈ [1,4]. Unbias: T2 -= 1 → offset [0,3].
    # N-exit: T2 ∈ [-3,0]. Restore+unbias: T2 += 3 → offset [0,3].
    asm.append(f".Lsb_mod_done:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T2}, .Lsb_mod_done_n")  # if T2 ≤ 0 → N path
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T2}, .Lsb_align")           # T2 -= 1 (unbias)
    asm.append(f".Lsb_align:")
    asm.append(f"        .word   {ADDR_T2}, {ADDR_R21}, .+4")  # R21 -= T2 = word_addr
    # Fall through to ldword (no jump needed!)
    
    asm.append(f".Lsb_ldword:")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_T3}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R21 | INDIRECT_FLAG}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T3}, .Lsb_branch")
    
    asm.append(f".Lsb_branch:")
    asm.append(f"        .word   {ADDR_T4}, {ADDR_T4}, .+4") # Clear Result
    # Dispatch on T2 (offset 0-3) via linear decrement
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T2}, .Lsb_byte0")      # T2=0 → byte 0
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T2}, .Lsb_byte1")         # T2=1 → byte 1
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T2}, .Lsb_byte2")         # T2=2 → byte 2
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_ZERO}, .Lsb_byte3")      # Z-preserving unconditional jump
    
    # P→N trampolines eliminated: P-chain now branches directly to N states
    
    # === N STATES with INLINE P: bits 30-2 ===
    for bit in range(30, 2, -1):
        power = 1 << bit
        power_prev = 1 << (bit - 1)
        next_N = f".Lsb_mb{bit-1}_N"
        
        asm.append(f".Lsb_mb{bit}_N:")
        asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_T2}, {next_N}")  # N→N: branch (1 op)
        
        # Inline P_{bit-1}
        if bit - 1 == 2:
            asm.append(f"        .word   {const_from_pool(power_prev)}, {ADDR_T2}, .Lsb_mod_done_n")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsb_mod_done")
        else:
            inline_branch = f".Lsb_mb{bit-2}_N"
            inline_skip = f".Lsb_mb{bit-2}_P"
            asm.append(f"        .word   {const_from_pool(power_prev)}, {ADDR_T2}, {inline_branch}")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {inline_skip}")
    
    # Bit 2: terminal N-state
    asm.append(f".Lsb_mb2_N:")
    asm.append(f"        .word   {const_from_pool(-4)}, {ADDR_T2}, .Lsb_mod_done_n")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsb_mod_done")
    
    # === N-exit cold path: restore + unbias + align ===
    asm.append(f".Lsb_mod_done_n:")
    asm.append(f"        .word   {const_from_pool(-3)}, {ADDR_T2}, .+4")        # T2 += 3 (restore+unbias)
    asm.append(f"        .word   {ADDR_T2}, {ADDR_R21}, .+4")        # R21 -= T2 = word_addr
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsb_ldword")   # jump to ldword
    
    # ========== SPLIT ENTRY POINTS (known byte offset) ==========
    # __subleq_sb_b{0,1,2,3}: R21 = word-aligned byte address, R22 = value
    # Skips modulo lattice (~35 ops saved per call).
    # OPTIMIZED: Entry falls through to fast-check (no jump, saves 1 op).
    # Merged range check: compute T5=R22 once, check ≤0 then ≤255 (saves 1 op).
    for byte_pos in range(4):
        asm.append(f"")
        asm.append(f"        .globl  __subleq_sb_b{byte_pos}")
        asm.append(f"__subleq_sb_b{byte_pos}:")
        # Set T2 = byte position so dispatch table works
        asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")              # T2 = 0
        if byte_pos == 1:
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T2}, .+4")          # T2 = 1
        elif byte_pos == 2:
            asm.append(f"        .word   {const_from_pool(-2)}, {ADDR_T2}, .+4")         # T2 = 2
        elif byte_pos == 3:
            asm.append(f"        .word   {const_from_pool(-3)}, {ADDR_T2}, .+4")          # T2 = 3
        # Fall through to fast-check (no jump needed! Z clean at entry)
        
        mask_target = f".Lsb_mask_s{byte_pos}" if byte_pos > 0 else ".Lsb_mask"
        
        # Merged R22 range check (Z clean from entry):
        # Compute T5 = R22 once, then check ≤0 and ≤255 sequentially.
        # Hot path (R22 ∈ [1,255]): 5 ops (was 6).
        asm.append(f".Lsb_fast_s{byte_pos}:")
        asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")                          # Z = -R22 (Z was clean)
        asm.append(f"        .word   {ADDR_T5}, {ADDR_T5}, .+4")                          # T5 = 0
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T5}, .+4")                           # T5 = R22
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T5}, .Lsb_fast_le0_s{byte_pos}")  # if R22 ≤ 0, check further
        asm.append(f"        .word   {const_from_pool(255)}, {ADDR_T5}, .Lsb_ldword")     # if R22 ≤ 255, done → ldword
        # R22 > 255: need masking
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {mask_target}")

        asm.append(f".Lsb_fast_le0_s{byte_pos}:")
        # T5 = R22 ≤ 0. Check R22 = 0 (ok) vs R22 < 0 (mask).
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T5}, {mask_target}")   # T5 += 1; if ≤ 0 → R22 < 0, mask
        # R22 = 0: go to ldword
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsb_ldword")

        if byte_pos > 0:
            asm.append(f".Lsb_mask_s{byte_pos}:")
            # Mask R22 via existing .Lsb_mask code.
            # .Lsb_mask falls through to .Lsb_off which recomputes byte position
            # from R21 via modulo. Since R21 is word-aligned, add byte offset
            # back so modulo gives the correct position.
            if byte_pos == 1:
                asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")       # R21 += 1
            elif byte_pos == 2:
                asm.append(f"        .word   {const_from_pool(-2)}, {ADDR_R21}, .+4")      # R21 += 2
            elif byte_pos == 3:
                asm.append(f"        .word   {const_from_pool(-3)}, {ADDR_R21}, .+4")       # R21 += 3
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lsb_mask")

    # Implement Byte Handlers
    asm.append(f".Lsb_byte0:")
    emit_lattice_mask_insert(asm, 0, ".Lsb_b0")
    asm.append(f".Lsb_byte1:")
    emit_lattice_mask_insert(asm, 1, ".Lsb_b1")
    asm.append(f".Lsb_byte2:")
    emit_lattice_mask_insert(asm, 2, ".Lsb_b2")
    asm.append(f".Lsb_byte3:")
    emit_lattice_mask_insert(asm, 3, ".Lsb_b3")
    
    # Store (Z clean from handler exit: all handlers jump via Z,Z,.Lsb_store)
    asm.append(f".Lsb_store:")
    asm.append(f"        .word   {ADDR_R21 | INDIRECT_FLAG}, {ADDR_R21 | INDIRECT_FLAG}, .+4")  # mem[R21] = 0
    asm.append(f"        .word   {ADDR_T4}, {ADDR_Z}, .+4")                                     # Z = -T4 (Z was clean)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R21 | INDIRECT_FLAG}, .Lsb_ret")               # mem[R21] = T4; both paths reach ret
    
    asm.append(f".Lsb_ret:")
    asm.extend(emit_return_sequence("sb"))
    

        
    asm.append(f"")
    asm.append(f"        .size   __subleq_sb, . - __subleq_sb")
    
    return asm

if __name__ == "__main__":
    for line in emit_sb():
        print(line)
