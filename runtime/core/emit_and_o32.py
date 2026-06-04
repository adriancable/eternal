#!/usr/bin/env python3
"""
Subleq runtime function: emit_and_o32

OPTIMIZED HYBRID NON-RESTORING LATTICE IMPLEMENTATION

Algorithm:
1. Fast paths for 0 and 1.
2. Bit 31 (Sign) handled explicitly to ensure robust behavior with INT_MIN.
3. Bit 30 handled with Restoring logic (safe 0 checks).
4. Bits 29-0 handled with Biased Non-Restoring Lattice:
   - Bias operands: A = A + 1, B = B + 1.
   - Lattice States: PP (Pos/Pos), PN (Pos/Neg), NP (Neg/Pos), NN (Neg/Neg).
   - Transitions imply bit values:
     - Sub 2^k from operand.
     - if > 0: Bit was 1 (State Pos), continue.
     - if <= 0: Bit was 0 (State Neg), continue.
   - Logic (AND): Only add 2^k to result if transition confirms both bits were 1.
   - Zero-overhead: No restoration steps required inside the loop.

"""

from gen_runtime import (ADDR_Z, ADDR_ZERO, ADDR_R20, ADDR_R21, ADDR_R22, ADDR_T0, ADDR_T1, ADDR_T2, ADDR_T3, ADDR_T4, emit_return_sequence, const_from_pool, ADDR_ONE, ADDR_MINUS_ONE)

def emit_and_o32():
    asm = []
    asm.append(f"")
    asm.append(f"        .globl  __subleq_and")
    asm.append(f"        .type   __subleq_and,@function")
    asm.append(f"")
    asm.append(f"# __subleq_and: Hybrid Optimized")
    asm.append(f"__subleq_and:")
    
    # === FAST PATHS ===
    # BW-A: Check R21 == 0 — hot path (R21 > 0) falls through to chk_r22
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Land_r21_le0_fast")
    
    # BW-B: Check R22 == 0 — hot path (R22 > 0) falls through to small_check
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Land_r22_le0_fast")
    
    # === MAGNITUDE CHECK CASCADE (hot path: both positive) ===
    # Z = 0 (guaranteed by caller's return convention: subleq(Z,Z,RA|I))
    # Sign re-checks for cold paths are deferred to .Land_small_check_cold.
    
    # --- 24-bit tier: check both < 16777216 (5 ops) ---
    asm.append(f".Land_magnitude_check:")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")             # Z = -R21 (Z was 0)
    asm.append(f"        .word   {const_from_pool(-16777216)}, {ADDR_Z}, .Land_full_positive")  # Z += 16M; if R21 >= 16M → full (both positive)
    asm.append(f"        .word   {ADDR_T1}, {ADDR_T1}, .+4")             # T1 = 0
    asm.append(f"        .word   {const_from_pool(-16777216)}, {ADDR_T1}, .+4")       # T1 = 16M
    asm.append(f"        .word   {ADDR_R22}, {ADDR_T1}, .Land_full_positive")    # T1 -= R22; if R22 >= 16M → full (both positive)
    # After: Z = -R21 + 16M > 0, T1 = 16M - R22 > 0
    
    # --- 16-bit tier: cascading residual reuse (2 ops, was 6) ---
    # R21 >= 65536 iff Z = -R21 + 16M <= 16M - 65536 = 16711680
    asm.append(f"        .word   {const_from_pool(16711680)}, {ADDR_Z}, .Land_fast_24bit")   # Z -= 16711680; if Z <= 0 → R21 >= 65536
    # R22 >= 65536 iff T1 = 16M - R22 <= 16711680
    asm.append(f"        .word   {const_from_pool(16711680)}, {ADDR_T1}, .Land_fast_24bit")  # T1 -= 16711680; if T1 <= 0 → R22 >= 65536
    # After: Z = -R21 + 65536 > 0, T1 = -R22 + 65536 > 0
    
    # --- 8-bit tier: cascading residual reuse (2 ops, was 6) ---
    # R21 >= 256 iff Z = -R21 + 65536 <= 65536 - 256 = 65280
    asm.append(f"        .word   {const_from_pool(65280)}, {ADDR_Z}, .Land_fast_16bit")   # Z -= 65280; if Z <= 0 → R21 >= 256
    # R22 >= 256 iff T1 = -R22 + 65536 <= 65280
    asm.append(f"        .word   {const_from_pool(65280)}, {ADDR_T1}, .Land_fast_16bit")  # T1 -= 65280; if T1 <= 0 → R22 >= 256
    
    # Both < 256: Use 8-bit fast path
    asm.append(f".Land_fast_8bit:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Land_b7_PP")
    
    # Both < 65536 but at least one >= 256: Use 16-bit fast path
    asm.append(f".Land_fast_16bit:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Land_b15_PP")
    
    # Both < 16777216 but at least one >= 65536: Use 24-bit fast path
    asm.append(f".Land_fast_24bit:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Land_b23_PP")

    # === SPLIT ENTRY POINTS for AND-immediate ===
    # When one operand is a compile-time constant, the backend calls
    # __subleq_and_bN to skip directly to bit N of the lattice.
    # Convention: R21 = variable operand, R22 = positive constant (bit 31 = 0).
    # R22's highest set bit is N, so R22 < 2^(N+1) — already fits in the lattice.
    # R21 may have bits above N set, so we must strip bits 30..N+1 from biased R21.
    #
    # NON-RESTORING STRIP (saves ~2 ops/bit executed vs restoring):
    # - Pos chain: subtract each 2^I; if R21<=0 → Neg; else stay Pos
    # - Neg chain: add each 2^I; if R21<=0 → stay Neg (next neg block); 
    #              else went Pos → fall through to remaining Pos strip (inline)
    # - Execution cost: 1 op per stripped bit (vs 3 for restoring)
    # - Code size: O(N²) per entry due to inline Pos remainders in Neg blocks
    for bit in range(30, -1, -1):
        asm.append(f"")
        asm.append(f"        .globl  __subleq_and_b{bit}")
        asm.append(f"        .type   __subleq_and_b{bit},@function")
        asm.append(f"__subleq_and_b{bit}:")
        # Clear accumulators
        asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
        asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
        # Check R21 sign: subleq(ZERO, R21, le0) - non-destructive since ZERO=0
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Land_split_b{bit}_r21_le0")
        # R21 > 0: no bit 31. Bias and enter strip.
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
        
        strip_bits = list(range(30, bit, -1))  # bits to strip: 30 down to bit+1
        
        # Helper: emit inline PP_{bit} entry (replaces Z,Z,PP with useful work)
        # AND PP: test R21 → R21N, test R22 → PN, accumulate → PP (always branches)
        def emit_inline_pp_and(asm, bit):
            pow_lbl = const_from_pool(1 << bit)
            r21n_lbl = f".Land_b{bit}_R21N_R22P"
            if bit == 0:
                t_pn = ".Land_done"
                t_pp = ".Land_done"
            else:
                t_pn = f".Land_b{bit-1}_PN"
                t_pp = f".Land_b{bit-1}_PP"
            asm.append(f"        .word   {pow_lbl}, {ADDR_R21}, {r21n_lbl}")
            asm.append(f"        .word   {pow_lbl}, {ADDR_R22}, {t_pn}")
            asm.append(f"        .word   {pow_lbl}, {ADDR_T0}, {t_pp}")
        
        if not strip_bits:
            # No strip needed — inline PP directly
            emit_inline_pp_and(asm, bit)
        else:
            # === MAGNITUDE CHECK: skip strip if R21 < 2^(bit+1) ===
            if len(strip_bits) >= 4 and bit < 30:
                threshold = 1 << (bit + 1)
                asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_Z}, .Land_split_b{bit}_strip")
                # Skip strip → inline PP
                emit_inline_pp_and(asm, bit)
            
            # === NON-RESTORING STRIP ===
            asm.append(f".Land_split_b{bit}_strip:")
            for i, strip_bit in enumerate(strip_bits):
                asm.append(f"        .word   {const_from_pool(1 << strip_bit)}, {ADDR_R21}, .Land_split_b{bit}_neg_{strip_bit}")
            # End of Pos chain → inline PP (replaces Z,Z,PP)
            emit_inline_pp_and(asm, bit)
            
            # Neg chain
            for i, strip_bit in enumerate(strip_bits):
                remaining = strip_bits[i+1:]
                asm.append(f".Land_split_b{bit}_neg_{strip_bit}:")
                if i == len(strip_bits) - 1:
                    asm.append(f"        .word   {const_from_pool(-(1 << strip_bit))}, {ADDR_R21}, .Land_b{bit}_NP")
                    # Fallthrough → inline PP (replaces Z,Z,PP)
                    emit_inline_pp_and(asm, bit)
                else:
                    first_rem = remaining[0]
                    asm.append(f"        .word   {const_from_pool(-(1 << first_rem))}, {ADDR_R21}, .Land_split_b{bit}_neg_{first_rem}")
                    for rem_bit in remaining[1:]:
                        asm.append(f"        .word   {const_from_pool(1 << rem_bit)}, {ADDR_R21}, .Land_split_b{bit}_neg_{rem_bit}")
                    # End of Pos tail → inline PP (replaces Z,Z,PP)
                    emit_inline_pp_and(asm, bit)

        # R21 <= 0: disambiguate
        asm.append(f".Land_split_b{bit}_r21_le0:")
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .Land_split_b{bit}_r21_neg_restore")
        asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Land_done")
        
        asm.append(f".Land_split_b{bit}_r21_neg_restore:")
        asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .+4")
        asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R21}, .Land_done")
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
        if strip_bits:
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Land_split_b{bit}_strip")
        else:
            emit_inline_pp_and(asm, bit)


    # === FULL POSITIVE PATH (both positive, both >= 16M) ===
    # Both operands are positive (from entry checks), so bit 31 = 0 for both.
    # AND of bit 31 = 0. Skip sign disambiguation and enter 30-bit lattice directly.
    asm.append(f".Land_full_positive:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4") # T0 = 0
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4") # R20 = 0
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4") # R21 += 1 (bias)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4") # R22 += 1 (bias)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Land_Loop_Start") # jump to b30_PP

    # === BIT 31 (SIGN) — Cold path only (one or both operands negative) ===
    asm.append(f".Land_Bit31:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4") # Result T0 = 0
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4") # Result R20 = 0 (Bit 31 accumulator)
    
    # Check R21 Sign - falls through if R21 > 0 to r21_pos path
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Land_b31_r21_le0")
    
    # R21 > 0: R21 is positive, no bit 31. Check R22 but don't add
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Land_b31_r22_neg_only")
    # HOT PATH: Both R21 > 0 and R22 > 0. Fall through directly to Bit30.
    # (Bit31 cold paths relocated after lattice for fallthrough optimization)
    
    # === BIAS SETUP ===
    # R21 and R22 are now < 2^31 (Bit 31 cleared).
    # Add +1 to both to enable 0-free checks for bits 30-0.
    asm.append(f".Land_Bit30:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4") # R21 += 1
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4") # R22 += 1
    
    # === LOOP 30-0 (BIASED NON-RESTORING) ===
    # State PP only at entry. Emit order: NP, PP, PN, NN
    # This allows NN_R21_Neg to fall through to next bit's NP,
    # eliminating one unconditional jump per bit.
    
    asm.append(f".Land_Loop_Start:")
    
    current_states = {'PP'}
    
    # Ordered emit sequence for MAIN blocks (without inline R21_Neg sub-blocks).
    # R21_Neg sub-blocks are shared and emitted after the main blocks.
    STATE_ORDER = ['NP', 'PP', 'PN', 'NN']
    
    for bit in range(30, -1, -1):
        power = 1 << bit
        next_states = set()
        
        # Define next labels (suffix)
        if bit == 0:
            next_lbl_base = ".Land_done"
        else:
            next_lbl_base = f".Land_b{bit-1}"
            
        lbl_base = f".Land_b{bit}"
        
        # Power constants
        pow_label = f"{const_from_pool(1 << bit)}"
        npow_label = f"{const_from_pool(-(1 << bit))}"
        
        # Helper to get jump target for next state
        def get_next_target(state_suffix):
             if bit == 0:
                 return ".Land_done"
             return f".Land_b{bit-1}_{state_suffix}"

        # === SHARED R21_Neg LABELS ===
        # PP_R21_Neg and NP_R21_Neg are identical: subleq(pow, R22, NN) → NP
        # PN_R21_Neg and NN_R21_Neg are identical: subleq(npow, R22, NN) → NP
        r21n_r22p_label = f"{lbl_base}_R21N_R22P"  # shared by PP, NP (R22 Pos)
        r21n_r22n_label = f"{lbl_base}_R21N_R22N"  # shared by PN, NN (R22 Neg)
        
        # Track which shared blocks are needed
        need_r22p = False  # PP or NP present
        need_r22n = False  # PN or NN present
        
        # === EMIT MAIN STATE BLOCKS ===
        for state in STATE_ORDER:
            if state not in current_states:
                continue
                
            if state == 'PP':
                asm.append(f"{lbl_base}_PP:")
                asm.append(f"        .word   {pow_label}, {ADDR_R21}, {r21n_r22p_label}")
                
                if bit > 0: next_states.add('PN')
                target_pn = get_next_target('PN')
                asm.append(f"        .word   {pow_label}, {ADDR_R22}, {target_pn}")
                
                if bit > 0: next_states.add('PP')
                target_pp = get_next_target('PP')
                asm.append(f"        .word   {pow_label}, {ADDR_T0}, {target_pp}")
                
                need_r22p = True
                if bit > 0: next_states.add('NN')
                if bit > 0: next_states.add('NP')
                
            elif state == 'PN':
                asm.append(f"{lbl_base}_PN:")
                asm.append(f"        .word   {pow_label}, {ADDR_R21}, {r21n_r22n_label}")
                
                if bit > 0: next_states.add('PN')
                target_pn = get_next_target('PN')
                asm.append(f"        .word   {npow_label}, {ADDR_R22}, {target_pn}")
                
                if bit > 0: next_states.add('PP')
                target_pp = get_next_target('PP')
                asm.append(f"        .word   {pow_label}, {ADDR_T0}, {target_pp}")
                
                need_r22n = True
                if bit > 0: next_states.add('NN')
                if bit > 0: next_states.add('NP')

            elif state == 'NP':
                asm.append(f"{lbl_base}_NP:")
                asm.append(f"        .word   {npow_label}, {ADDR_R21}, {r21n_r22p_label}")
                
                if bit > 0: next_states.add('PN')
                target_pn = get_next_target('PN')
                asm.append(f"        .word   {pow_label}, {ADDR_R22}, {target_pn}")
                
                if bit > 0: next_states.add('PP')
                target_pp = get_next_target('PP')
                asm.append(f"        .word   {pow_label}, {ADDR_T0}, {target_pp}")
                
                need_r22p = True
                if bit > 0: next_states.add('NN')
                if bit > 0: next_states.add('NP')

            elif state == 'NN':
                asm.append(f"{lbl_base}_NN:")
                asm.append(f"        .word   {npow_label}, {ADDR_R21}, {r21n_r22n_label}")
                
                if bit > 0: next_states.add('PN')
                target_pn = get_next_target('PN')
                asm.append(f"        .word   {npow_label}, {ADDR_R22}, {target_pn}")
                
                if bit > 0: next_states.add('PP')
                target_pp = get_next_target('PP')
                asm.append(f"        .word   {pow_label}, {ADDR_T0}, {target_pp}")
                
                need_r22n = True
                if bit > 0: next_states.add('NN')
                if bit > 0: next_states.add('NP')

        # === EMIT SHARED R21_Neg SUB-BLOCKS ===
        # Emit order: R22N first (needs jump), R22P last (fallthrough to next NP).
        # R22P is reached from PP/NP (more common, we enter at PP), so giving
        # it the fallthrough saves ~1 instruction on the R22=1 path.
        target_nn = get_next_target('NN')
        target_np = get_next_target('NP')
        
        if need_r22n:
            asm.append(f"{r21n_r22n_label}:")
            asm.append(f"        .word   {npow_label}, {ADDR_R22}, {target_nn}")
            if need_r22p:
                # R22P block follows — jump to NP (can't fall through to R22P)
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {target_np}")
            # else: R22P not needed — this IS the last block, fallthrough to next NP
        
        if need_r22p:
            asm.append(f"{r21n_r22p_label}:")
            asm.append(f"        .word   {pow_label}, {ADDR_R22}, {target_nn}")
            # Last block — falls through to next NP (or .Land_done at bit 0)
            if bit == 0:
                # At bit 0, need explicit jump to .Land_done
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Land_done")

        current_states = next_states

    asm.append(f".Land_done:")
    # T0 holds NEGATIVE result (Bits 30-0).
    # R20 holds Bit 31 result (INT_MIN or 0).
    # R20 -= T0 -> R20 = R20 - (-Bits30_0) = Bit31 + Bits30_0.
    asm.append(f"        .word   {ADDR_T0}, {ADDR_R20}, .+4")  # R20 = R20 + (-T0)
    asm.extend(emit_return_sequence("and"))
    
    # === BIT 31 COLD PATHS (relocated from hot path for fallthrough optimization) ===
    asm.append(f".Land_b31_r21_le0:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .Land_b31_r21_neg_restore")  # R21 += 1; if <= 0 → negative
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Land_b31_r21_zero")  # R21 was 0: restore+branch
    
    asm.append(f".Land_b31_r21_neg_restore:")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .+4")  # restore
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R21}, .Land_b31_both_check")  # Clear bit 31, jump if <= 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Land_b31_both_check")  # Fallback if > 0
    
    asm.append(f".Land_b31_r21_zero:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Land_b31_r22_neg_only")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Land_Bit30")
    
    asm.append(f".Land_b31_r22_neg_only:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .Land_b31_r22_negonly_restore")  # R22 += 1; if <= 0 → negative
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .Land_Bit30")  # R22 was 0: restore+branch
    
    asm.append(f".Land_b31_r22_negonly_restore:")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .+4")  # restore
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R22}, .Land_Bit30")  # Clear, may jump
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Land_Bit30")  # Fallback

    asm.append(f".Land_b31_both_check:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Land_b31_r22_neg_both")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Land_Bit30")
    
    asm.append(f".Land_b31_r22_neg_both:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .Land_b31_r22_negboth_restore")  # R22 += 1; if <= 0 → negative
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .Land_Bit30")  # R22 was 0: restore+branch
    
    asm.append(f".Land_b31_r22_negboth_restore:")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .+4")  # restore
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R20}, .Land_Bit30")  # Fused: R20 = INT_MIN <= 0, always jumps
    
    # === COLD PATHS: R21/R22 zero checks (relocated from entry for hot-path fallthrough) ===
    asm.append(f".Land_r21_le0_fast:")
    # OPTIMIZED: Combined restore+branch (operates on R21 directly)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .Land_r21_neg_restore")  # R21 += 1; if <= 0 → negative
    # R21 was 0: restore and return zero
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Land_ret_zero")  # restore+branch
    
    asm.append(f".Land_r21_neg_restore:")
    # R21 was < 0: restore R21 (always branches via .+4)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .+4")  # restore+branch
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Land_small_check_cold")
    
    asm.append(f".Land_r22_le0_fast:")
    # OPTIMIZED: Combined restore+branch (operates on R22 directly)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .Land_r22_neg_restore")  # R22 += 1; if <= 0 → negative
    # R22 was 0: restore and return zero
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .Land_ret_zero")  # restore+branch
    
    asm.append(f".Land_r22_neg_restore:")
    # R22 was < 0: restore R22 (always branches via .+4)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .+4")  # restore+branch
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Land_small_check_cold")
    
    # === COLD PATH: sign re-check for negative operands ===
    # Reached from r21_neg_restore / r22_neg_restore. Z = 0 (cleared by jump).
    # Re-check signs (only fires on cold path; hot path bypasses these).
    asm.append(f".Land_small_check_cold:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Land_Bit31")  # if R21 <= 0, full path
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Land_Bit31")  # if R22 <= 0, full path
    # Both positive: Z is still 0 (sign checks don't touch Z).
    # Jump to magnitude check with Z clean.
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Land_magnitude_check")
    
    asm.append(f".Land_ret_zero:")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.extend(emit_return_sequence("and_zero"))
    
    # Constants

    # Power constants
    for bit in range(30, -1, -1):
        power = 1 << bit

    asm.append(f"")
    asm.append(f"        .size   __subleq_and, . - __subleq_and")
    return asm

if __name__ == "__main__":
    for line in emit_and_o32():
        print(line)
