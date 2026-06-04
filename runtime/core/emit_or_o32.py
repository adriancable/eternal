#!/usr/bin/env python3
"""
Subleq runtime function: emit_or_o32

AND-STRUCTURED NON-RESTORING LATTICE

Algorithm:
1. Fast paths for 0 and small integers.
2. Bit 31 (Sign) handled explicitly.
3. Bits 30-0 handled with Biased Non-Restoring Lattice:
   - Bias operands: A = A + 1, B = B + 1.
   - Lattice States: PP, PN, NP, NN.
   - State body (3 instructions, same structure as AND):
     - Test R21: if bit=0, jump to R21N shared block.
     - Test R22: if bit=0, jump to R22N accumulate trampoline.
     - Both bits=1: accumulate 2^k into T0 + branch to next PP.
   - R22N trampoline (1 instr): R21 bit=1 alone → accumulate + branch PN.
   - R21N shared (2 instr): test R22, if bit=1 → accumulate + branch NP.
   - Per-bit cost: 2-3 instructions (~2.75 average vs AND's ~2.5).
"""

from gen_runtime import (ADDR_Z, ADDR_ZERO, ADDR_R20, ADDR_R21, ADDR_R22, ADDR_T0, ADDR_T1, ADDR_T2, ADDR_T3, ADDR_T4, emit_return_sequence, const_from_pool, ADDR_ONE, ADDR_MINUS_ONE)

def emit_or_o32():
    asm = []
    asm.append(f"")
    asm.append(f"        .globl  __subleq_or")
    asm.append(f"        .type   __subleq_or,@function")
    asm.append(f"")
    asm.append(f"# __subleq_or: Hybrid Optimized")
    asm.append(f"__subleq_or:")
    

    # === FAST PATHS ===
    # BW-A: Check R21 == 0 — hot path (R21 > 0) falls through to chk_r22
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Lor_r21_le0_fast")
    
    # BW-B: Check R22 == 0 — hot path (R22 > 0) falls through to small_check
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lor_r22_le0_fast")

    # === MAGNITUDE CHECK CASCADE (hot path: both positive) ===
    # Z = 0 (guaranteed by caller's return convention: subleq(Z,Z,RA|I))
    # Sign re-checks for cold paths are deferred to .Lor_small_check_cold.
    
    # --- 24-bit tier: check both < 16777216 (5 ops) ---
    asm.append(f".Lor_magnitude_check:")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")             # Z = -R21 (Z was 0)
    asm.append(f"        .word   {const_from_pool(-16777216)}, {ADDR_Z}, .Lor_full_positive")  # Z += 16M; if R21 >= 16M → full (both positive)
    asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")             # T2 = 0
    asm.append(f"        .word   {const_from_pool(-16777216)}, {ADDR_T2}, .+4")       # T2 = 16M
    asm.append(f"        .word   {ADDR_R22}, {ADDR_T2}, .Lor_full_positive")    # T2 -= R22; if R22 >= 16M → full (both positive)
    # After: Z = -R21 + 16M > 0, T2 = 16M - R22 > 0
    
    # --- 16-bit tier: cascading residual reuse (2 ops, was 6) ---
    asm.append(f"        .word   {const_from_pool(16711680)}, {ADDR_Z}, .Lor_fast_24bit")   # Z -= 16711680; if Z <= 0 → R21 >= 65536
    asm.append(f"        .word   {const_from_pool(16711680)}, {ADDR_T2}, .Lor_fast_24bit")  # T2 -= 16711680; if T2 <= 0 → R22 >= 65536
    # After: Z = -R21 + 65536 > 0, T2 = -R22 + 65536 > 0
    
    # --- 8-bit tier: cascading residual reuse (2 ops, was 6) ---
    asm.append(f"        .word   {const_from_pool(65280)}, {ADDR_Z}, .Lor_fast_16bit")   # Z -= 65280; if Z <= 0 → R21 >= 256
    asm.append(f"        .word   {const_from_pool(65280)}, {ADDR_T2}, .Lor_fast_16bit")  # T2 -= 65280; if T2 <= 0 → R22 >= 256
    
    # Both < 256: 8-bit fast path
    asm.append(f".Lor_fast_8bit:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lor_b7_PP")
    
    # 16-bit fast path
    asm.append(f".Lor_fast_16bit:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lor_b15_PP")
    
    # 24-bit fast path
    asm.append(f".Lor_fast_24bit:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lor_b23_PP")

    # === SPLIT ENTRY POINTS for OR-immediate ===
    # When one operand is a compile-time constant, the backend calls
    # __subleq_or_bN to skip directly to bit N of the lattice.
    # Convention: R21 = variable operand, R22 = positive constant (bit 31 = 0).
    # R22's highest set bit is N, so R22 < 2^(N+1).
    # R21 may have bits above N set; strip them and accumulate into T0
    # since OR(bit, 0) = bit (those upper bits pass through to the result).
    for bit in range(30, -1, -1):
        asm.append(f"")
        asm.append(f"        .globl  __subleq_or_b{bit}")
        asm.append(f"        .type   __subleq_or_b{bit},@function")
        asm.append(f"__subleq_or_b{bit}:")
        # Clear accumulators: T0 (bits 30-0), R20 (bit 31)
        asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
        asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
        # Check R21 sign
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Lor_split_b{bit}_r21_le0")
        # R21 > 0: bias R21 and fall through to strip
        # NOTE: R22 bias is deferred to just before lattice entry to avoid
        # corrupting its bit pattern (e.g. 0xFFFF+1=0x10000 changes highBit).
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")
        strip_bits = list(range(30, bit, -1))

        # Helper: emit inline PP_{bit} entry for OR
        # OR PP: test R21 → R21N_R22P, test R22 → R22N_acc, accumulate → PP
        def emit_inline_pp_or(asm, bit):
            pow_lbl = const_from_pool(1 << bit)
            r21n_lbl = f".Lor_b{bit}_R21N_R22P"
            r22n_lbl = f".Lor_b{bit}_R22N_acc"
            if bit == 0:
                t_pp = ".Lor_done"
            else:
                t_pp = f".Lor_b{bit-1}_PP"
            asm.append(f"        .word   {pow_lbl}, {ADDR_R21}, {r21n_lbl}")
            asm.append(f"        .word   {pow_lbl}, {ADDR_R22}, {r22n_lbl}")
            asm.append(f"        .word   {pow_lbl}, {ADDR_T0}, {t_pp}")

        # Helper: emit inline NP_{bit} entry for OR
        def emit_inline_np_or(asm, bit):
            npow_lbl = const_from_pool(-(1 << bit))
            pow_lbl = const_from_pool(1 << bit)
            r21n_lbl = f".Lor_b{bit}_R21N_R22P"
            r22n_lbl = f".Lor_b{bit}_R22N_acc"
            if bit == 0:
                t_pp = ".Lor_done"
            else:
                t_pp = f".Lor_b{bit-1}_PP"
            asm.append(f"        .word   {npow_lbl}, {ADDR_R21}, {r21n_lbl}")
            asm.append(f"        .word   {pow_lbl}, {ADDR_R22}, {r22n_lbl}")
            asm.append(f"        .word   {pow_lbl}, {ADDR_T0}, {t_pp}")

        if not strip_bits:
            # No strip needed — bias R22 and inline PP
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
            emit_inline_pp_or(asm, bit)
        else:
            # === MAGNITUDE CHECK ===
            if len(strip_bits) >= 4 and bit < 30:
                threshold = 1 << (bit + 1)
                asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_Z}, .Lor_split_b{bit}_strip")
                # Skip strip → bias R22 and inline PP
                asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
                emit_inline_pp_or(asm, bit)
            
            # === Pos chain ===
            asm.append(f".Lor_split_b{bit}_strip:")
            for strip_bit in strip_bits:
                asm.append(f"        .word   {const_from_pool(1 << strip_bit)}, {ADDR_R21}, .Lor_split_b{bit}_neg_{strip_bit}")
                asm.append(f"        .word   {const_from_pool(1 << strip_bit)}, {ADDR_T0}, .+4")
            # End of Pos chain → bias R22 and inline PP
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
            emit_inline_pp_or(asm, bit)

            # === Neg chain ===
            for i, strip_bit in enumerate(strip_bits):
                remaining = strip_bits[i+1:]
                asm.append(f".Lor_split_b{bit}_neg_{strip_bit}:")
                if i == len(strip_bits) - 1:
                    asm.append(f"        .word   {const_from_pool(-(1 << strip_bit))}, {ADDR_R21}, .Lor_split_b{bit}_enter_NP")
                    # Fallthrough → bias R22 and inline PP
                    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
                    emit_inline_pp_or(asm, bit)
                else:
                    first_rem = remaining[0]
                    asm.append(f"        .word   {const_from_pool(-(1 << first_rem))}, {ADDR_R21}, .Lor_split_b{bit}_neg_{first_rem}")
                    asm.append(f"        .word   {const_from_pool(1 << first_rem)}, {ADDR_T0}, .+4")
                    for rem_bit in remaining[1:]:
                        asm.append(f"        .word   {const_from_pool(1 << rem_bit)}, {ADDR_R21}, .Lor_split_b{bit}_neg_{rem_bit}")
                        asm.append(f"        .word   {const_from_pool(1 << rem_bit)}, {ADDR_T0}, .+4")
                    # End of Pos tail → bias R22 and inline PP
                    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
                    emit_inline_pp_or(asm, bit)

            # Shared NP entry: bias R22 and inline NP
            asm.append(f".Lor_split_b{bit}_enter_NP:")
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
            emit_inline_np_or(asm, bit)
        # R21 <= 0: disambiguate
        asm.append(f".Lor_split_b{bit}_r21_le0:")
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .Lor_split_b{bit}_r21_neg_restore")
        asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Lor_split_b{bit}_r21_zero")
        
        asm.append(f".Lor_split_b{bit}_r21_neg_restore:")
        asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .+4")
        asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R21}, .+4")
        asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R20}, .+4")
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")
        if strip_bits:
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lor_split_b{bit}_strip")
        else:
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
            emit_inline_pp_or(asm, bit)
        # R21 = 0: OR(0, const) = const. Return R22 directly.
        asm.append(f".Lor_split_b{bit}_r21_zero:")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lor_ret_r22")


    # === FULL POSITIVE PATH (both positive, both >= 16M) ===
    # Both operands are positive (from entry checks), so bit 31 = 0 for both.
    # OR of bit 31 = 0. Skip sign disambiguation and enter 30-bit lattice directly.
    asm.append(f".Lor_full_positive:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4") # T0 = 0
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4") # R20 = 0
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4") # R21 += 1 (bias)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4") # R22 += 1 (bias)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lor_Loop_Start") # jump to b30_PP

    asm.append(f".Lor_Bit31:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")  # T0 = 0
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4") # R20 = 0 (Bit 31 accumulator)
    # Check R21 Sign
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Lor_b31_r21_neg")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lor_b31_r21_pos")
    
    asm.append(f".Lor_b31_r21_neg:")
    # OPTIMIZED: Combined restore+branch (operates on R21 directly)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .Lor_b31_r21_neg_restore")  # R21 += 1; if <= 0 → negative
    # R21 was 0 (now 1): restore and skip to pos
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Lor_b31_r21_pos")  # restore+branch
    
    asm.append(f".Lor_b31_r21_neg_restore:")
    # R21 was < 0: restore R21 (always branches via .+4)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .+4")  # restore+branch
    # R21 < 0 (including INT_MIN). Clear bit 31. Add to R20 (bit 31 accumulator).
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R20}, .+4")
    # R21 had Bit 31. Check R22 (to clear it, result already set).
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lor_b31_r21_set_chk_r22")
    
    asm.append(f".Lor_b31_r21_pos:")
    # R21 Pos. No Bit 31. Result needs bit 31 from R22.
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lor_b31_r22_neg_add")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lor_Bit30")
    
    asm.append(f".Lor_b31_r22_neg_add:")
    # OPTIMIZED: Combined restore+branch (operates on R22 directly)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .Lor_b31_r22_negadd_restore")  # R22 += 1; if <= 0 → negative
    # R22 was 0 (now 1): restore and skip to Bit30
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .Lor_Bit30")  # restore+branch
    
    asm.append(f".Lor_b31_r22_negadd_restore:")
    # R22 was < 0: restore R22 (always branches via .+4)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .+4")  # restore+branch
    # Real Neg (including INT_MIN). Clear bit 31. Add to R20 (bit 31 accumulator).
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R20}, .Lor_Bit30")  # Fused: R20 = INT_MIN <= 0, always jumps

    asm.append(f".Lor_b31_r21_set_chk_r22:")
    # R21 bit 31 set. Result set. Check R22 ONLY to clear bit 31.
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lor_b31_r22_neg_clear")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lor_Bit30")
    
    asm.append(f".Lor_b31_r22_neg_clear:")
    # OPTIMIZED: Combined restore+branch (operates on R22 directly)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .Lor_b31_r22_negclr_restore")  # R22 += 1; if <= 0 → negative
    # R22 was 0 (now 1): restore and skip to Bit30
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .Lor_Bit30")  # restore+branch
    
    asm.append(f".Lor_b31_r22_negclr_restore:")
    # R22 was < 0: restore R22 (always branches via .+4)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .+4")  # restore+branch
    # Real Neg (including INT_MIN). Clear bit 31.
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R22}, .Lor_Bit30")  # Clear, 0 <= 0 always jumps
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lor_Bit30")  # Fallback

    # === BIT 30 (LATTICE) ===
    # R21 and R22 are now < 2^31 (Bit 31 cleared).
    # Add +1 to both to enable 0-free checks for bits 30-0.
    asm.append(f".Lor_Bit30:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4") # R21 += 1
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4") # R22 += 1
    
    # === LOOP 30-0 (BIASED NON-RESTORING, AND-STRUCTURED) ===
    # Same 3-instruction state body as AND. Accumulates T0 in the 3rd
    # instruction when both bits=1. Single-bit OR cases handled by:
    #   - R22N trampoline: R21 bit=1, R22 bit=0 → accumulate + PN
    #   - R21N shared: R21 bit=0, test R22 → accumulate if R22=1 + NP
    asm.append(f".Lor_Loop_Start:")
    
    current_states = {'PP'}
    STATE_ORDER = ['NP', 'PP', 'PN', 'NN']
    
    for bit in range(30, -1, -1):
        next_states = set()
        lbl_base = f".Lor_b{bit}"
        pow_label = f"{const_from_pool(1 << bit)}"
        npow_label = f"{const_from_pool(-(1 << bit))}"
        
        if bit == 0:
            target_pp = ".Lor_done"
            target_pn = ".Lor_done"
            target_np = ".Lor_done"
            target_nn = ".Lor_done"
        else:
            target_pp = f".Lor_b{bit-1}_PP"
            target_pn = f".Lor_b{bit-1}_PN"
            target_np = f".Lor_b{bit-1}_NP"
            target_nn = f".Lor_b{bit-1}_NN"
        
        # Shared labels
        r21n_r22p_label = f"{lbl_base}_R21N_R22P"  # shared by PP, NP (R22 Pos)
        r21n_r22n_label = f"{lbl_base}_R21N_R22N"  # shared by PN, NN (R22 Neg)
        r22n_accum_label = f"{lbl_base}_R22N_acc"   # shared trampoline
        
        need_r22p = False
        need_r22n = False
        
        # === STATE BLOCKS (3 instructions each) ===
        for state in STATE_ORDER:
            if state not in current_states:
                continue
            
            r21_pow = pow_label if state[0] == 'P' else npow_label
            r22_pow = pow_label if state[1] == 'P' else npow_label
            r21n_shared = r21n_r22p_label if state[1] == 'P' else r21n_r22n_label
            
            if state[1] == 'P':
                need_r22p = True
            else:
                need_r22n = True
            
            asm.append(f"{lbl_base}_{state}:")
            asm.append(f"        .word   {r21_pow}, {ADDR_R21}, {r21n_shared}")
            asm.append(f"        .word   {r22_pow}, {ADDR_R22}, {r22n_accum_label}")
            asm.append(f"        .word   {pow_label}, {ADDR_T0}, {target_pp}")
            
            if bit > 0:
                next_states.update({'PP', 'PN', 'NP', 'NN'})
        
        # === R22N ACCUMULATE TRAMPOLINE (1 instruction) ===
        # R21 bit=1, R22 bit=0 → OR=1 → accumulate + branch to PN
        asm.append(f"{r22n_accum_label}:")
        asm.append(f"        .word   {pow_label}, {ADDR_T0}, {target_pn}")
        
        # === R21N SHARED BLOCKS (2 instructions each) ===
        # R21 bit=0. Test R22: if bit=0 → NN (no accum). If bit=1 → accum + NP.
        if need_r22p:
            asm.append(f"{r21n_r22p_label}:")
            asm.append(f"        .word   {pow_label}, {ADDR_R22}, {target_nn}")
            asm.append(f"        .word   {pow_label}, {ADDR_T0}, {target_np}")
        
        if need_r22n:
            asm.append(f"{r21n_r22n_label}:")
            asm.append(f"        .word   {npow_label}, {ADDR_R22}, {target_nn}")
            asm.append(f"        .word   {pow_label}, {ADDR_T0}, {target_np}")
        
        current_states = next_states

    asm.append(f".Lor_done:")
    # T0 holds NEGATIVE result for bits 30-0 (accumulated via pow subtractions).
    # R20 holds bit 31 result (INT_MIN or 0, from Bit31 handler).
    # Combine: R20 -= T0 → R20 = R20 + (-T0) = Bit31 + Bits30_0.
    asm.append(f"        .word   {ADDR_T0}, {ADDR_R20}, .+4")  # R20 = R20 - T0
    asm.extend(emit_return_sequence("or"))
    
    # === COLD PATHS: R21/R22 zero checks (relocated from entry for hot-path fallthrough) ===
    asm.append(f".Lor_r21_le0_fast:")
    # OPTIMIZED: Combined restore+branch (operates on R21 directly)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .Lor_r21_neg_fast_restore")  # R21 += 1; if <= 0 → negative
    # R21 was 0: restore and return R22
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Lor_ret_r22")  # restore+branch
    
    asm.append(f".Lor_r21_neg_fast_restore:")
    # R21 was < 0: restore R21 (always branches via .+4)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .+4")  # restore+branch
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lor_small_check_cold")
    
    asm.append(f".Lor_ret_r22:")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")    # Z = -R22
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")  # R20 = 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .+4")    # R20 = R22
    asm.extend(emit_return_sequence("or_r22"))
    
    asm.append(f".Lor_r22_le0_fast:")
    # OPTIMIZED: Combined restore+branch (operates on R22 directly)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .Lor_r22_neg_fast_restore")  # R22 += 1; if <= 0 → negative
    # R22 was 0: restore and return R21
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .Lor_ret_r21")  # restore+branch
    
    asm.append(f".Lor_r22_neg_fast_restore:")
    # R22 was < 0: restore R22 (always branches via .+4)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .+4")  # restore+branch
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lor_small_check_cold")
    
    # === COLD PATH: sign re-check for negative operands ===
    # Reached from r21/r22_neg_fast_restore. Z = 0 (cleared by jump).
    asm.append(f".Lor_small_check_cold:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Lor_Bit31")  # if R21 <= 0, full path
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lor_Bit31")  # if R22 <= 0, full path
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lor_magnitude_check")
    
    asm.append(f".Lor_ret_r21:")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")    # Z = -R21
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")  # R20 = 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .+4")    # R20 = R21
    asm.extend(emit_return_sequence("or_r21"))
    
    # Constants

    # Power constants
    for bit in range(30, -1, -1):
        power = 1 << bit

    asm.append(f"")
    asm.append(f"        .size   __subleq_or, . - __subleq_or")
    return asm

if __name__ == "__main__":
    for line in emit_or_o32():
        print(line)
