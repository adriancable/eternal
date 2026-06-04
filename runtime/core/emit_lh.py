#!/usr/bin/env python3
"""
Subleq runtime function: Load Halfword (zero-extending)

__subleq_lh: Load Halfword - Biased Non-Restoring Lattice Optimization

Algorithm:
1. Modulo Calculation (O(1) Unrolled):
   - Determine offset = byte_addr % 4 using subtract-and-test loop on bits 31..2.
   - Word aligned address = byte_addr - offset.
   - Half Position = (offset >> 1) & 1.
2. Load Word.
3. Lattice Extraction:
   - Half 0 (Low): Run Lattice 30..0. Accumulate only bits 15..0.
   - Half 1 (High): Bit 31 is Result Bit 15. Run Lattice 30..0. Accumulate bits 30..16 into Result bits 14..0.
"""

from gen_runtime import ADDR_Z, ADDR_ZERO, ADDR_R20, ADDR_R21, ADDR_T0, ADDR_T1, ADDR_T3, ADDR_T5, ADDR_T6, INDIRECT_FLAG, emit_return_sequence, const_from_pool, ADDR_ONE, ADDR_MINUS_ONE

# Result register for extraction lattice (direct R20 accumulation, no copy needed)
ADDR_RESULT = ADDR_R20

def emit_lattice_extract_lh(asm, low_half, prefix):
    """
    Generate Biased Non-Restoring Lattice code to extract a halfword from T3.
    
    Arguments:
    - low_half: True for bits 0-15, False for bits 16-31.
    - prefix: Label prefix.
    
    Logic:
    1. Bit 31: Robust check (Signed/INT_MIN handling).
    2. Bit 30: Restoring check.
    3. Bias: T3 += 1.
    4. Lattice Loop (29..0).
    """
    
    # === Bit 31 (Sign) — OPTIMIZED: 1 op hot path ===
    accumulate_b31 = not low_half
    
    asm.append(f"{prefix}_sign:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T3}, {prefix}_le0")  # if T3 <= 0, cold path
    # T3 > 0: fall through (HOT PATH — 1 op!)
    
    # === Magnitude skip: if T3 is small, skip non-accum lattice ===
    if low_half:
        # Low half: accum bits 15..0, non-accum bits 30..16. Skip if T3 < 65536.
        # Z = -T3 invariant: ldword/split-entry sets Z = -T3, sign check preserves it.
        asm.append(f"        .word   {const_from_pool(-65536)}, {ADDR_Z}, {prefix}_full")  # Z += 65536; if \u2264 0, T3 \u2265 65536
        # IDENTITY: T3 < 65536 → word IS the halfword. R20 = T3.
        # Z = -T3 + 65536. Subtract 65536 to get Z = -T3.
        asm.append(f"        .word   {const_from_pool(65536)}, {ADDR_Z}, .+4")  # Z -= 65536 = -T3
        asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .+4")  # R20 += T3
        # Inline return: saves 1 op vs jumping to .Llh_ret1
        ret_lines = emit_return_sequence("lh_h0_id")
        asm.extend(ret_lines[1:])  # skip the label, emit Z,Z,RA|I directly
        
        asm.append(f"{prefix}_full:")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_bias")  # clear Z + jump
    else:
        # High half: if T3 < 65536, bits [30:16] all zero, R20 = 0
        # Z = -T3 invariant (same as above)
        asm.append(f"        .word   {const_from_pool(-65536)}, {ADDR_Z}, {prefix}_bias_z")  # Z += 65536; if ≤ 0, T3 ≥ 65536
        # T3 < 65536: bits [30:16] all zero, R20 = 0
        # Inline return: saves 1 op vs jumping to .Llh_ret1
        ret_lines = emit_return_sequence("lh_h1_id")
        asm.extend(ret_lines[1:])
        asm.append(f"{prefix}_bias_z:")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_bias")
    
    # === Bias T3 += 1, then Lattice starts at bit 30 (no b30 restoring!) ===
    asm.append(f"{prefix}_bias:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T3}, .+4")
    
    # Determine non-accumulating range.
    # Low half: accum bits 0-15, non-accum bits 29-16 (14 leading non-accum)
    # High half: accum bits 16-29, no non-accum bits
    
    if low_half:
        # Leading non-accum: bits 30 down to 16
        first_accum_bit = 15  # highest accumulating bit
        last_non_accum = 16   # lowest non-accumulating bit
        
        # === LINEAR P CHAIN: non-accumulating bits 30 down to 16 ===
        # Branch directly to N-state target (no trampoline!)
        for bit in range(30, last_non_accum, -1):
            power = 1 << bit
            next_N = f"{prefix}_b{bit-1}_N"
            asm.append(f"{prefix}_b{bit}_P:")
            asm.append(f"        .word   {const_from_pool(power)}, {ADDR_T3}, {next_N}")
        
        # Last non-accum P state (bit 16)
        next_N = f"{prefix}_b{first_accum_bit}_N"
        asm.append(f"{prefix}_b{last_non_accum}_P:")
        asm.append(f"        .word   {const_from_pool(1 << last_non_accum)}, {ADDR_T3}, {next_N}")
        # Fall through to first accumulating P state (bit 15)
        
        # === ACCUMULATING BITS 15-0: interleaved ===
        for bit in range(first_accum_bit, -1, -1):
            power = 1 << bit
            res_val = 1 << bit  # res_bit = bit - 0 = bit
            
            if bit == 0:
                next_lbl_P = ".Llh_ret1"
                next_lbl_N = ".Llh_ret1"
            else:
                next_lbl_P = f"{prefix}_b{bit-1}_P"
                next_lbl_N = f"{prefix}_b{bit-1}_N"
            
            # P state — branch directly to next_lbl_N (no trampoline!)
            asm.append(f"{prefix}_b{bit}_P:")
            asm.append(f"        .word   {const_from_pool(power)}, {ADDR_T3}, {next_lbl_N}")
            asm.append(f"        .word   {const_from_pool(-res_val)}, {ADDR_RESULT}, .+4")
            if bit > 0:
                # INLINE next P's test
                nb = bit - 1
                nb_power = 1 << nb
                nb_res = 1 << nb  # res_bit = nb - 0 = nb
                if nb == 0:
                    inl_P = ".Llh_ret1"
                    inl_N = ".Llh_ret1"
                else:
                    inl_P = f"{prefix}_b{nb-1}_P"
                    inl_N = f"{prefix}_b{nb-1}_N"
                asm.append(f"        .word   {const_from_pool(nb_power)}, {ADDR_T3}, {inl_N}")
                asm.append(f"        .word   {const_from_pool(-nb_res)}, {ADDR_RESULT}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {inl_P}")
            else:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl_P}")
            
            # N state — branch directly to next_lbl_N (no trampoline!)
            asm.append(f"{prefix}_b{bit}_N:")
            asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_T3}, {next_lbl_N}")
            asm.append(f"        .word   {const_from_pool(-res_val)}, {ADDR_RESULT}, .+4")
            # Fallthrough optimization: for bit > 0, next_P is the very next label
            if bit == 0:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl_P}")
        
        # P→N trampolines eliminated: P-chain now branches directly to N states
        
        for bit in range(30, last_non_accum - 1, -1):
            power = 1 << bit
            
            if bit == last_non_accum:
                next_lbl_P = f"{prefix}_b{first_accum_bit}_P"
                next_lbl_N = f"{prefix}_b{first_accum_bit}_N"
            else:
                next_lbl_P = f"{prefix}_b{bit-1}_P"
                next_lbl_N = f"{prefix}_b{bit-1}_N"
            
            asm.append(f"{prefix}_b{bit}_N:")
            asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_T3}, {next_lbl_N}")  # N→N
            # N→P: inline first accum P's test
            if bit == last_non_accum:
                fab = first_accum_bit
                fab_power = 1 << fab
                fab_res = 1 << fab
                if fab == 0:
                    fab_N = ".Llh_ret1"
                    fab_P = ".Llh_ret1"
                else:
                    fab_N = f"{prefix}_b{fab-1}_N"
                    fab_P = f"{prefix}_b{fab-1}_P"
                asm.append(f"        .word   {const_from_pool(fab_power)}, {ADDR_T3}, {fab_N}")
                asm.append(f"        .word   {const_from_pool(-fab_res)}, {ADDR_RESULT}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {fab_P}")
            else:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl_P}")  # N→P
    
        # === Cold path: T3 <= 0 (sign bit handling) ===
        # OPTIMIZED: Combined restore+branch (operates on T3 directly)
        asm.append(f"{prefix}_le0:")
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T3}, {prefix}_neg")  # T3 += 1; if <= 0 → T3 < 0
        # T3 was 0 (now 1): R20 already 0, skip lattice entirely (always branches)
        asm.append(f"        .word   {ADDR_ONE}, {ADDR_T3}, .Llh_ret1")  # restore+skip
        asm.append(f"{prefix}_neg:")
        # T3 was < 0: restore T3 (always branches via .+4)
        asm.append(f"        .word   {ADDR_ONE}, {ADDR_T3}, .+4")  # restore+branch
        if accumulate_b31:
            asm.append(f"        .word   {const_from_pool(-32768)}, {ADDR_RESULT}, .+4")
        asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_T3}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_bias")
    
    else:
        # High half: all bits 30-16 accumulate (res_bit = bit - 16)
        # Bits 15-0 are non-accumulating — terminate lattice at bit 16
        # No leading non-accum bits — start at bit 30
        stop_bit = 16
        reachable = {30: {'P'}}
        
        for bit in range(30, stop_bit - 1, -1):
            power = 1 << bit
            accum = (bit >= 16)
            
            if accum:
                res_val = 1 << (bit - 16)
            
            if bit == stop_bit:
                next_lbl_P = ".Llh_ret1"
                next_lbl_N = ".Llh_ret1"
            else:
                next_lbl_P = f"{prefix}_b{bit-1}_P"
                next_lbl_N = f"{prefix}_b{bit-1}_N"
                
            states = reachable.get(bit, set())
            next_states = set()
            
            if 'P' in states:
                asm.append(f"{prefix}_b{bit}_P:")
                asm.append(f"        .word   {const_from_pool(power)}, {ADDR_T3}, {next_lbl_N}")
                if accum:
                    asm.append(f"        .word   {const_from_pool(-res_val)}, {ADDR_RESULT}, .+4")
                # INLINE next P's test
                if 'N' in states and bit > stop_bit:
                    nb = bit - 1
                    nb_power = 1 << nb
                    nb_accum = (nb >= 16)
                    if nb == stop_bit:
                        inl_P = ".Llh_ret1"
                        inl_N = ".Llh_ret1"
                    else:
                        inl_P = f"{prefix}_b{nb-1}_P"
                        inl_N = f"{prefix}_b{nb-1}_N"
                    asm.append(f"        .word   {const_from_pool(nb_power)}, {ADDR_T3}, {inl_N}")
                    if nb_accum:
                        nb_res = 1 << (nb - 16)
                        asm.append(f"        .word   {const_from_pool(-nb_res)}, {ADDR_RESULT}, .+4")
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {inl_P}")
                else:
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl_P}")
                next_states.add('P')
                next_states.add('N')
                
            if 'N' in states:
                asm.append(f"{prefix}_b{bit}_N:")
                asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_T3}, {next_lbl_N}")
                if accum:
                    asm.append(f"        .word   {const_from_pool(-res_val)}, {ADDR_RESULT}, .+4")
                # Fallthrough optimization: if P was also emitted and not last bit
                if not ('P' in states and bit > stop_bit):
                    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl_P}")
                next_states.add('P')
                next_states.add('N')
                
            if bit > stop_bit:
                reachable[bit-1] = next_states
    
        # === Cold path for high half ===
        # OPTIMIZED: Combined restore+branch (operates on T3 directly)
        asm.append(f"{prefix}_le0:")
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T3}, {prefix}_neg")  # T3 += 1; if <= 0 → T3 < 0
        # T3 was 0 (now 1): R20 already 0, skip lattice entirely (always branches)
        asm.append(f"        .word   {ADDR_ONE}, {ADDR_T3}, .Llh_ret1")  # restore+skip
        asm.append(f"{prefix}_neg:")
        # T3 was < 0: restore T3 (always branches via .+4)
        asm.append(f"        .word   {ADDR_ONE}, {ADDR_T3}, .+4")  # restore+branch
        if accumulate_b31:
            asm.append(f"        .word   {const_from_pool(-32768)}, {ADDR_RESULT}, .+4")
        asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_T3}, .+4")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_bias")


def emit_lh():
    asm = []
    asm.append(f"")
    asm.append(f"        .globl  __subleq_lh")
    asm.append(f"        .type   __subleq_lh,@function")
    asm.append(f"")
    asm.append(f"# __subleq_lh: Load halfword - Biased Non-Restoring Lattice")
    asm.append(f"__subleq_lh:")
    
    # Save byte address in T0 (Z-scratch: Z is clean at entry)
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")   # Z = -R21 (Z was 0)
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")   # T0 = 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T0}, .Llh_offset")  # T0 = R21
    
    # ===== MODULO CALCULATION (addresses always positive) =====
    asm.append(f".Llh_offset:")
    
    # === Bias (skip sign check — addresses always positive!) ===
    # LH-A: Use R21 directly for modulo (T0 preserves original addr).
    asm.append(f".Llh_mod_bias:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")  # R21 += 1 (bias)
    
    # === LINEAR P CHAIN: bits 30 down to 2 ===
    # Branch directly to N-state targets (no trampolines!)
    for bit in range(30, 2, -1):
        power = 1 << bit
        pow_label = f"{const_from_pool(power)}"
        next_N = f".Llh_mod_b{bit-1}_N"
        asm.append(f".Llh_mod_b{bit}_P:")
        asm.append(f"        .word   {pow_label}, {ADDR_R21}, {next_N}")
    
    asm.append(f".Llh_mod_b2_P:")
    asm.append(f"        .word   {const_from_pool(4)}, {ADDR_R21}, .Llh_mod_done_n")
    # Fall through to mod_done (P-path: R21 > 0)
    
    # === MODULO DONE ===
    # P-exit: R21 ∈ [1,4]. Unbias: R21 -= 1 → offset [0,3].
    # N-exit: R21 ∈ [-3,0]. Restore+unbias: R21 += 3 → offset [0,3].
    asm.append(f".Llh_mod_done:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Llh_mod_done_n")  # if R21 ≤ 0 → N path
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Llh_align")           # R21 -= 1 (unbias)
    # Word Address = T0 - offset
    asm.append(f".Llh_align:")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_T0}, .+4")  # T0 -= R21 = word_addr
    # Fall through to ldword (no jump needed!)
    
    # Load Word
    asm.append(f".Llh_ldword:")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_T3}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T0 | INDIRECT_FLAG}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T3}, .Llh_branch")
    
    # Branch
    asm.append(f".Llh_branch:")
    # LH-C: Accumulate into R20 directly (no R21→R20 copy at return)
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    # Dispatch on R21 (offset 0 or 2)
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Llh_half0")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_ZERO}, .Llh_half1")
    
    # P→N trampolines eliminated: P-chain now branches directly to N states
    
    # === N STATES with INLINE P: bits 30-2 ===
    for bit in range(30, 2, -1):
        power = 1 << bit
        power_prev = 1 << (bit - 1)
        next_N = f".Llh_mod_b{bit-1}_N"
        
        asm.append(f".Llh_mod_b{bit}_N:")
        asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_R21}, {next_N}")  # N→N: branch (1 op)
        
        # Inline P_{bit-1}
        if bit - 1 == 2:
            asm.append(f"        .word   {const_from_pool(power_prev)}, {ADDR_R21}, .Llh_mod_done_n")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Llh_mod_done")
        else:
            inline_branch = f".Llh_mod_b{bit-2}_N"
            inline_skip = f".Llh_mod_b{bit-2}_P"
            asm.append(f"        .word   {const_from_pool(power_prev)}, {ADDR_R21}, {inline_branch}")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {inline_skip}")
    
    # Bit 2: terminal N-state
    asm.append(f".Llh_mod_b2_N:")
    asm.append(f"        .word   {const_from_pool(-4)}, {ADDR_R21}, .Llh_mod_done_n")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Llh_mod_done")
    
    # === N-exit cold path: restore + unbias + align ===
    asm.append(f".Llh_mod_done_n:")
    asm.append(f"        .word   {const_from_pool(-3)}, {ADDR_R21}, .+4")        # R21 += 3 (restore+unbias)
    asm.append(f"        .word   {ADDR_R21}, {ADDR_T0}, .+4")        # T0 -= R21 = word_addr
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Llh_ldword")   # jump to ldword

    # ========== SPLIT ENTRY POINTS + HALF HANDLERS (Interleaved) ==========
    # __subleq_lh_h{0,1}: R21 = word-aligned byte address
    # Skips the entire modulo lattice (~40 ops saved per call).
    # OPTIMIZED: 8 ops (was 9). Fused load+jump: subleq(Z, T3, handler)
    # Both branch and fall-through reach the handler label placed after entry.
    half_configs = [(True, ".Llh_h0"), (False, ".Llh_h1")]
    for half_pos in range(2):
        low_half, prefix = half_configs[half_pos]
        asm.append(f"")
        asm.append(f"        .globl  __subleq_lh_h{half_pos}")
        asm.append(f"__subleq_lh_h{half_pos}:")
        # Load word directly via R21|I (R21 = word address, no T0 copy needed!)
        asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")    # R20 = 0 (result accumulator)
        asm.append(f"        .word   {ADDR_T3}, {ADDR_T3}, .+4")      # T3 = 0
        # Z is clean at function entry (caller's return clears it)
        asm.append(f"        .word   {ADDR_R21 | INDIRECT_FLAG}, {ADDR_Z}, .+4")  # Z = -mem[R21]
        # Fused copy+jump: T3 = mem[R21], handler reached either way
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T3}, .Llh_half{half_pos}")
        # Handler placed right after entry
        asm.append(f".Llh_half{half_pos}:")
        emit_lattice_extract_lh(asm, low_half, prefix)
    
    # === Return ===
    asm.append(f".Llh_ret1:")
    # LH-C: R20 already contains result — no copy needed
    
    asm.extend(emit_return_sequence("lh"))
    
    # Constants
    
    asm.append(f"")
    asm.append(f"        .size   __subleq_lh, . - __subleq_lh")
    
    return asm

if __name__ == "__main__":
    for line in emit_lh():
        print(line)
