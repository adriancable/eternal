#!/usr/bin/env python3
"""
Subleq runtime function: emit_xor_o32

OPTIMIZED HYBRID NON-RESTORING IMPLEMENTATION

Algorithm:
1. Fast paths for 0 and small integers.
2. Bit 31 (Sign) handled explicitly (Arithmetic Addition).
   - 1 + 0 = 1
   - 0 + 1 = 1
   - 1 + 1 = 0 (Overflow)
   - This matches XOR behavior for the MSB.
3. Bit 30 handled with Restoring logic.
4. Bits 29-0 handled with Biased Non-Restoring Lattice:
   - Bias operands: A = A + 1, B = B + 1.
   - Lattice States: PP, PN, NP, NN.
   - Transitions (Subtract 2^k):
     - Update State A (Pos/Neg).
     - Update State B (Pos/Neg).
   - Logic (XOR): Add 2^k to result if exactly ONE operand transition indicates Pos (Bit=1).
     - (A_Pos AND B_Neg) -> Add.
     - (A_Neg AND B_Pos) -> Add.
     - (A_Pos AND B_Pos) -> No Add (1^1=0).
     - (A_Neg AND B_Neg) -> No Add (0^0=0).
   - Zero-overhead: No restoration steps. Code path explicitly handles all 4 input state combinations per bit.
"""

from gen_runtime import (ADDR_Z, ADDR_ZERO, ADDR_R20, ADDR_R21, ADDR_R22, ADDR_T0, ADDR_T1, ADDR_T2, ADDR_T3, ADDR_T4, emit_return_sequence, const_from_pool, ADDR_ONE, ADDR_MINUS_ONE)

def emit_xor_o32():
    asm = []
    asm.append(f"")
    asm.append(f"        .globl  __subleq_xor")
    asm.append(f"        .type   __subleq_xor,@function")
    asm.append(f"")
    asm.append(f"# __subleq_xor: Hybrid Optimized")
    asm.append(f"__subleq_xor:")
    


    # === FAST PATHS ===
    # BW-A: Check R21 == 0 — hot path (R21 > 0) falls through to chk_r22
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Lxor_r21_le0_fast")
    
    # BW-B: Check R22 == 0 — hot path (R22 > 0) falls through to small_check
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lxor_r22_le0_fast")

    # === MAGNITUDE CHECK CASCADE (hot path: both positive) ===
    # Z = 0 (guaranteed by caller's return convention: subleq(Z,Z,RA|I))
    # Sign re-checks for cold paths are deferred to .Lxor_small_check_cold.
    
    # --- 24-bit tier: check both < 16777216 (5 ops) ---
    asm.append(f".Lxor_magnitude_check:")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")             # Z = -R21 (Z was 0)
    asm.append(f"        .word   {const_from_pool(-16777216)}, {ADDR_Z}, .Lxor_full_positive")  # Z += 16M; if R21 >= 16M → full (both positive)
    asm.append(f"        .word   {ADDR_T2}, {ADDR_T2}, .+4")             # T2 = 0
    asm.append(f"        .word   {const_from_pool(-16777216)}, {ADDR_T2}, .+4")       # T2 = 16M
    asm.append(f"        .word   {ADDR_R22}, {ADDR_T2}, .Lxor_full_positive")    # T2 -= R22; if R22 >= 16M → full (both positive)
    # After: Z = -R21 + 16M > 0, T2 = 16M - R22 > 0
    
    # --- 16-bit tier: cascading residual reuse (2 ops, was 6) ---
    asm.append(f"        .word   {const_from_pool(16711680)}, {ADDR_Z}, .Lxor_fast_24bit")   # Z -= 16711680; if Z <= 0 → R21 >= 65536
    asm.append(f"        .word   {const_from_pool(16711680)}, {ADDR_T2}, .Lxor_fast_24bit")  # T2 -= 16711680; if T2 <= 0 → R22 >= 65536
    # After: Z = -R21 + 65536 > 0, T2 = -R22 + 65536 > 0
    
    # --- 8-bit tier: cascading residual reuse (2 ops, was 6) ---
    asm.append(f"        .word   {const_from_pool(65280)}, {ADDR_Z}, .Lxor_fast_16bit")   # Z -= 65280; if Z <= 0 → R21 >= 256
    asm.append(f"        .word   {const_from_pool(65280)}, {ADDR_T2}, .Lxor_fast_16bit")  # T2 -= 65280; if T2 <= 0 → R22 >= 256
    
    # Both < 256: 8-bit fast path
    asm.append(f".Lxor_fast_8bit:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lxor_b7_PP")
    
    # 16-bit fast path
    asm.append(f".Lxor_fast_16bit:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lxor_b15_PP")
    
    # 24-bit fast path
    asm.append(f".Lxor_fast_24bit:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lxor_b23_PP")

    # === SPLIT ENTRY POINTS for XOR-immediate ===
    # When one operand is a compile-time constant, the backend calls
    # __subleq_xor_bN to skip directly to bit N of the lattice.
    # Convention: R21 = variable operand, R22 = positive constant (bit 31 = 0).
    # R22's highest set bit is N, so R22 < 2^(N+1).
    # R21 may have bits above N set; strip them and accumulate into T0
    # since XOR(bit, 0) = bit (those upper bits pass through to the result).
    for bit in range(30, -1, -1):
        asm.append(f"")
        asm.append(f"        .globl  __subleq_xor_b{bit}")
        asm.append(f"        .type   __subleq_xor_b{bit},@function")
        asm.append(f"__subleq_xor_b{bit}:")
        # Clear accumulators: T0 (bits 30-0), R20 (bit 31)
        asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")
        asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
        # Check R21 sign
        asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Lxor_split_b{bit}_r21_le0")
        # R21 > 0: bias R21 and fall through to strip
        # NOTE: R22 bias is deferred to just before lattice entry to avoid
        # corrupting its bit pattern (e.g. 0xFFFF+1=0x10000 changes highBit).
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")
        strip_bits = list(range(30, bit, -1))

        # Helper: emit inline PP_{bit} entry for XOR
        # XOR PP: test R21 → R21N_R22P, test R22 → R22N_acc, then Z,Z,PP_{K-1}
        def emit_inline_pp_xor(asm, bit):
            pow_lbl = const_from_pool(1 << bit)
            r21n_lbl = f".Lxor_b{bit}_R21N_R22P"
            r22n_lbl = f".Lxor_b{bit}_R22N_acc"
            if bit == 0:
                t_pp = ".Lxor_done"
            else:
                t_pp = f".Lxor_b{bit-1}_PP"
            asm.append(f"        .word   {pow_lbl}, {ADDR_R21}, {r21n_lbl}")
            asm.append(f"        .word   {pow_lbl}, {ADDR_R22}, {r22n_lbl}")
            # Both=1: XOR=0, jump into PP chain at K-1
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {t_pp}")

        # Helper: emit inline NP_{bit} entry for XOR
        def emit_inline_np_xor(asm, bit):
            npow_lbl = const_from_pool(-(1 << bit))
            pow_lbl = const_from_pool(1 << bit)
            r21n_lbl = f".Lxor_b{bit}_R21N_R22P"
            r22n_lbl = f".Lxor_b{bit}_R22N_acc"
            if bit == 0:
                t_pp = ".Lxor_done"
            else:
                t_pp = f".Lxor_b{bit-1}_PP"
            asm.append(f"        .word   {npow_lbl}, {ADDR_R21}, {r21n_lbl}")
            asm.append(f"        .word   {pow_lbl}, {ADDR_R22}, {r22n_lbl}")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {t_pp}")

        if not strip_bits:
            # No strip needed — bias R22 and inline PP
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
            emit_inline_pp_xor(asm, bit)
        else:
            # === MAGNITUDE CHECK ===
            if len(strip_bits) >= 4 and bit < 30:
                threshold = 1 << (bit + 1)
                asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
                asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_Z}, .Lxor_split_b{bit}_strip")
                # Skip strip → bias R22 and inline PP
                asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
                emit_inline_pp_xor(asm, bit)
            
            # === Pos chain ===
            asm.append(f".Lxor_split_b{bit}_strip:")
            for strip_bit in strip_bits:
                asm.append(f"        .word   {const_from_pool(1 << strip_bit)}, {ADDR_R21}, .Lxor_split_b{bit}_neg_{strip_bit}")
                asm.append(f"        .word   {const_from_pool(1 << strip_bit)}, {ADDR_T0}, .+4")
            # End of Pos chain → bias R22 and inline PP
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
            emit_inline_pp_xor(asm, bit)

            # === Neg chain ===
            for i, strip_bit in enumerate(strip_bits):
                remaining = strip_bits[i+1:]
                asm.append(f".Lxor_split_b{bit}_neg_{strip_bit}:")
                if i == len(strip_bits) - 1:
                    asm.append(f"        .word   {const_from_pool(-(1 << strip_bit))}, {ADDR_R21}, .Lxor_split_b{bit}_enter_NP")
                    # Fallthrough → bias R22 and inline PP
                    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
                    emit_inline_pp_xor(asm, bit)
                else:
                    first_rem = remaining[0]
                    asm.append(f"        .word   {const_from_pool(-(1 << first_rem))}, {ADDR_R21}, .Lxor_split_b{bit}_neg_{first_rem}")
                    asm.append(f"        .word   {const_from_pool(1 << first_rem)}, {ADDR_T0}, .+4")
                    for rem_bit in remaining[1:]:
                        asm.append(f"        .word   {const_from_pool(1 << rem_bit)}, {ADDR_R21}, .Lxor_split_b{bit}_neg_{rem_bit}")
                        asm.append(f"        .word   {const_from_pool(1 << rem_bit)}, {ADDR_T0}, .+4")
                    # End of Pos tail → bias R22 and inline PP
                    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
                    emit_inline_pp_xor(asm, bit)

            # Shared NP entry: bias R22 and inline NP
            asm.append(f".Lxor_split_b{bit}_enter_NP:")
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
            emit_inline_np_xor(asm, bit)
        # R21 <= 0: disambiguate
        asm.append(f".Lxor_split_b{bit}_r21_le0:")
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .Lxor_split_b{bit}_r21_neg_restore")
        asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Lxor_split_b{bit}_r21_zero")
        
        asm.append(f".Lxor_split_b{bit}_r21_neg_restore:")
        asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .+4")
        asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R21}, .+4")
        asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R20}, .+4")
        asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")
        if strip_bits:
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lxor_split_b{bit}_strip")
        else:
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4")
            emit_inline_pp_xor(asm, bit)
        # R21 = 0: XOR(0, const) = const. Return R22 directly.
        asm.append(f".Lxor_split_b{bit}_r21_zero:")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lxor_ret_r22")


    # === FULL POSITIVE PATH (both positive, both >= 16M) ===
    # Both operands are positive (from entry checks), so bit 31 = 0 for both.
    # XOR of bit 31 = 0. Skip sign disambiguation and enter 30-bit lattice directly.
    asm.append(f".Lxor_full_positive:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4") # T0 = 0
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4") # R20 = 0
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4") # R21 += 1 (bias)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4") # R22 += 1 (bias)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lxor_Loop_Start") # jump to b30_PP

    # === BIT 31 (SIGN) — Cold path only (one or both operands negative) ===
    asm.append(f".Lxor_Bit31:")
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")  # T0 = 0
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4") # R20 = 0 (Bit 31 accumulator)
    
    # Check R21 Sign
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Lxor_b31_r21_neg")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lxor_b31_chk_r22")
    
    asm.append(f".Lxor_b31_r21_neg:")
    # OPTIMIZED: Combined restore+branch (operates on R21 directly)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .Lxor_b31_r21_neg_restore")  # R21 += 1; if <= 0 → negative
    # R21 was 0 (now 1): restore and skip to chk_r22
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Lxor_b31_chk_r22")  # restore+branch
    
    asm.append(f".Lxor_b31_r21_neg_restore:")
    # R21 was < 0: restore R21 (always branches via .+4)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .+4")  # restore+branch
    # R21 < 0 (including INT_MIN). Add INT_MIN to R20 (bit 31 accumulator). Clear bit 31.
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R21}, .+4")  # Clear bit 31

    asm.append(f".Lxor_b31_chk_r22:")
    # Check R22 Sign
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lxor_b31_r22_neg")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lxor_Bit30")
    
    asm.append(f".Lxor_b31_r22_neg:")
    # OPTIMIZED: Combined restore+branch (operates on R22 directly)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .Lxor_b31_r22_neg_restore")  # R22 += 1; if <= 0 → negative
    # R22 was 0 (now 1): restore and skip to Bit30
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .Lxor_Bit30")  # restore+branch
    
    asm.append(f".Lxor_b31_r22_neg_restore:")
    # R22 was < 0: restore R22 (always branches via .+4)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .+4")  # restore+branch
    # R22 < 0 (including INT_MIN). Add INT_MIN to R20 (bit 31 accumulator). Clear bit 31.
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_R22}, .+4")  # Clear bit 31

    # === BIT 30 (LATTICE) ===
    # R21 and R22 are now < 2^31 (Bit 31 cleared).
    # Add +1 to both to enable 0-free checks for bits 30-0.
    asm.append(f".Lxor_Bit30:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4") # R21 += 1
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .+4") # R22 += 1
    
    # === LOOP 30-0 (BIASED NON-RESTORING, DEDICATED PP CHAIN) ===
    # PP chain is emitted as consecutive entries (both=1 → XOR=0 → fall through).
    # Non-PP states (NP, PN, NN) jump into the PP chain when both=1.
    # Each non-PP state inlines one PP copy, so re-entry saves 1 op.
    asm.append(f".Lxor_Loop_Start:")
    
    # === DEDICATED PP CHAIN (hot path: both bits=1 falls through) ===
    for bit in range(30, -1, -1):
        lbl_base = f".Lxor_b{bit}"
        pow_label = f"{const_from_pool(1 << bit)}"
        r21n_r22p_label = f"{lbl_base}_R21N_R22P"
        r22n_acc_label = f"{lbl_base}_R22N_acc"
        
        asm.append(f"{lbl_base}_PP:")
        asm.append(f"        .word   {pow_label}, {ADDR_R21}, {r21n_r22p_label}")
        asm.append(f"        .word   {pow_label}, {ADDR_R22}, {r22n_acc_label}")
        # Both=1: XOR=0, no accumulate. Fall through to next PP.
    
    # PP chain end: fall through to done
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lxor_done")
    
    # === NON-PP STATES + SUB-BLOCKS (per bit) ===
    current_states = {'PP'}  # track reachable states for emission
    
    for bit in range(30, -1, -1):
        next_states = set()
        lbl_base = f".Lxor_b{bit}"
        pow_label = f"{const_from_pool(1 << bit)}"
        npow_label = f"{const_from_pool(-(1 << bit))}"
        
        if bit == 0:
            target_pp = ".Lxor_done"
            target_pn = ".Lxor_done"
            target_np = ".Lxor_done"
            target_nn = ".Lxor_done"
        else:
            target_pp = f".Lxor_b{bit-1}_PP"
            target_pn = f".Lxor_b{bit-1}_PN"
            target_np = f".Lxor_b{bit-1}_NP"
            target_nn = f".Lxor_b{bit-1}_NN"
        
        r21n_r22p_label = f"{lbl_base}_R21N_R22P"
        r21n_r22n_label = f"{lbl_base}_R21N_R22N"
        r22n_acc_label = f"{lbl_base}_R22N_acc"
        
        need_r22p = False
        need_r22n = False
        
        # === NON-PP STATE BLOCKS (NP, PN, NN) ===
        for state in ['NP', 'PN', 'NN']:
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
            asm.append(f"        .word   {r22_pow}, {ADDR_R22}, {r22n_acc_label}")
            # Both=1: XOR=0, no accumulate. Inline next PP to save 1 op.
            if bit > 0:
                next_bit = bit - 1
                next_pow = f"{const_from_pool(1 << next_bit)}"
                next_r21n = f".Lxor_b{next_bit}_R21N_R22P"
                next_r22n = f".Lxor_b{next_bit}_R22N_acc"
                if next_bit == 0:
                    inline_pp_target = ".Lxor_done"
                else:
                    inline_pp_target = f".Lxor_b{next_bit-1}_PP"
                # Inline PP_{K-1}: replaces Z,Z,PP with useful work
                asm.append(f"        .word   {next_pow}, {ADDR_R21}, {next_r21n}")
                asm.append(f"        .word   {next_pow}, {ADDR_R22}, {next_r22n}")
                # Inline PP both=1: jump into PP chain at K-2
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {inline_pp_target}")
            else:
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lxor_done")
            
            if bit > 0:
                next_states.update({'PP', 'PN', 'NP', 'NN'})
        
        # PP also generates reachable states
        if 'PP' in current_states:
            need_r22p = True
            if bit > 0:
                next_states.update({'PP', 'PN', 'NP', 'NN'})
        
        # === R22N ACCUMULATE (1 instruction) ===
        asm.append(f"{r22n_acc_label}:")
        asm.append(f"        .word   {pow_label}, {ADDR_T0}, {target_pn}")
        
        # === R21N SHARED BLOCKS ===
        if need_r22n:
            asm.append(f"{r21n_r22n_label}:")
            asm.append(f"        .word   {npow_label}, {ADDR_R22}, {target_nn}")
            asm.append(f"        .word   {pow_label}, {ADDR_T0}, {target_np}")

        if need_r22p:
            asm.append(f"{r21n_r22p_label}:")
            asm.append(f"        .word   {pow_label}, {ADDR_R22}, {target_nn}")
            asm.append(f"        .word   {pow_label}, {ADDR_T0}, {target_np}")
        
        current_states = next_states

    asm.append(f".Lxor_done:")
    # T0 holds NEGATIVE result for bits 30-0.
    # R20 holds bit 31 result (INT_MIN, 0, or wraps to 0 if both set).
    # Combine: R20 -= T0 → R20 = R20 + (-T0) = Bit31 + Bits30_0.
    asm.append(f"        .word   {ADDR_T0}, {ADDR_R20}, .+4")  # R20 = R20 - T0
    asm.extend(emit_return_sequence("xor"))
    
    # === COLD PATHS: R21/R22 zero checks (relocated from entry for hot-path fallthrough) ===
    asm.append(f".Lxor_r21_le0_fast:")
    # OPTIMIZED: Combined restore+branch (operates on R21 directly)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .Lxor_r21_neg_fast_restore")  # R21 += 1; if <= 0 → negative
    # R21 was 0: restore and return R22
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Lxor_ret_r22")  # restore+branch
    
    asm.append(f".Lxor_r21_neg_fast_restore:")
    # R21 was < 0: restore R21 (always branches via .+4)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .+4")  # restore+branch
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lxor_small_check_cold")
    
    asm.append(f".Lxor_ret_r22:")
    asm.append(f"        .word   {ADDR_R22}, {ADDR_Z}, .+4")    # Z = -R22
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")  # R20 = 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .+4")    # R20 = R22
    asm.extend(emit_return_sequence("xor_r22"))
    
    asm.append(f".Lxor_r22_le0_fast:")
    # OPTIMIZED: Combined restore+branch (operates on R22 directly)
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R22}, .Lxor_r22_neg_fast_restore")  # R22 += 1; if <= 0 → negative
    # R22 was 0: restore and return R21
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .Lxor_ret_r21")  # restore+branch
    
    asm.append(f".Lxor_r22_neg_fast_restore:")
    # R22 was < 0: restore R22 (always branches via .+4)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .+4")  # restore+branch
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lxor_small_check_cold")
    
    # === COLD PATH: sign re-check for negative operands ===
    # Reached from r21/r22_neg_fast_restore. Z = 0 (cleared by jump).
    asm.append(f".Lxor_small_check_cold:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Lxor_Bit31")  # if R21 <= 0, full path
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lxor_Bit31")  # if R22 <= 0, full path
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lxor_magnitude_check")
    
    asm.append(f".Lxor_ret_r21:")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")    # Z = -R21
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")  # R20 = 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .+4")    # R20 = R21
    asm.extend(emit_return_sequence("xor_r21"))
    
    # Constants

    # Power constants
    for bit in range(30, -1, -1):
        power = 1 << bit

    asm.append(f"")
    asm.append(f"        .size   __subleq_xor, . - __subleq_xor")
    return asm

if __name__ == "__main__":
    for line in emit_xor_o32():
        print(line)
