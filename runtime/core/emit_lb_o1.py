#!/usr/bin/env python3
"""
Optimized emit_lb with O(1) modulo calculation and Biased Non-Restoring Lattice extraction.

AGGRESSIVE OPTIMIZATIONS:
1. Z-scratch entry: saves 1 op (Z clean at function entry)
2. Use R21 directly for modulo: saves 4 ops (no T5 copy needed, T0 holds original addr)
3. Eliminate modulo sign check: addresses are ALWAYS positive, saves 2+ ops
4. Linearize N-chain in modulo: N→N transitions are 1 op instead of 2
5. Simplified extraction sign check: 1 op hot path (was 8)
6. Eliminate bit 30 restoring check: extend lattice to start at bit 30 after bias
7. Direct R20 accumulation: extraction lattice writes result to R20 directly, saves 4 ops (no copy)
"""

from gen_runtime import (ADDR_Z, ADDR_SP, ADDR_T0, ADDR_R20, ADDR_R21, INDIRECT_FLAG, emit_return_sequence, ADDR_ZERO, const_from_pool, ADDR_ONE, ADDR_MINUS_ONE)

# Additional local constants
ADDR_T1 = 41 * 4      # = 164
ADDR_T3 = 43 * 4      # = 172
ADDR_T5 = 45 * 4      # = 180
ADDR_T6 = 46 * 4      # = 184
ADDR_T7 = 47 * 4      # = 188

def emit_lattice_extract(asm, shift, prefix):
    """
    Generate Biased Non-Restoring Lattice code to extract a byte from T3.
    
    OPTIMIZED:
    - Sign check: 1 op hot path (T3 > 0 falls through to bias)
    - No separate bit 30 restoring: lattice starts at bit 30 after bias
    - Cold path (_le0) placed after lattice
    - Accumulates into R20 directly (no copy needed in return)
    """
    # Bit 31 result position
    res_bit_31 = 31 - shift
    accumulate_b31 = (res_bit_31 < 8)

    # === Sign check: 1 op hot path ===
    asm.append(f"{prefix}_sign:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_T3}, {prefix}_le0")  # if T3 <= 0, cold path
    # T3 > 0: fall through (HOT PATH — 1 op!)

    # === Magnitude skip: if T3 fits in target byte range, skip non-accum lattice ===
    first_accum_bit = shift + 7  # highest accumulating bit (res_bit=7)
    if first_accum_bit > 30:
        first_accum_bit = 30
    threshold = 1 << (first_accum_bit + 1)  # e.g. byte0: 256, byte1: 65536, byte2: 16777216
    
    if first_accum_bit < 30:  # bytes 0, 1, 2 have non-accum bits to skip
        # Z = -T3 invariant: ldword/split-entry sets Z = -T3, sign check preserves it.
        asm.append(f"        .word   {const_from_pool(-threshold)}, {ADDR_Z}, {prefix}_full")  # Z += threshold; if \u2264 0, T3 \u2265 threshold
        # T3 < threshold: all upper bits are 0
        
        if shift == 0:
            # IDENTITY FAST PATH (byte 0): T3 IS the byte value.
            # Z = -T3 + threshold from check above. Subtract threshold to get Z = -T3.
            asm.append(f"        .word   {const_from_pool(threshold)}, {ADDR_Z}, .+4")  # Z -= threshold \u2192 Z = -T3
            asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .+4")  # R20 -= Z = R20 + T3
            # Inline return: saves 1 op vs jumping to .Llb_ret1
            ret_lines = emit_return_sequence("lb_b0_id")
            asm.extend(ret_lines[1:])  # skip the label, emit Z,Z,RA|I directly
        else:
            # Bytes 1, 2: skip to first accumulating bit
            asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T3}, .+4")  # bias T3 += 1
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_b{first_accum_bit}_P")  # clear Z + jump
        
        asm.append(f"{prefix}_full:")
        # T3 >= threshold: need full lattice. Z is dirty \u2192 clear it
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_bias")  # clear Z + jump to bias
    elif shift == 24:  # byte 3: all bits 30-24 accumulate, skip if T3 < 2^24
        # Z = -T3 invariant (same as above)
        asm.append(f"        .word   {const_from_pool(-16777216)}, {ADDR_Z}, {prefix}_full")  # Z += 16M; if <= 0, T3 >= 16M
        # T3 < 16M: bits 30-24 are all 0, byte 3 = 0, R20 stays 0
        # Inline return: saves 1 op vs jumping to .Llb_ret1
        ret_lines = emit_return_sequence("lb_b3_id")
        asm.extend(ret_lines[1:])
        asm.append(f"{prefix}_full:")
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_bias")  # clear Z + bias

    # === Bias T3 += 1 for Lattice Loop ===
    asm.append(f"{prefix}_bias:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T3}, .+4")  # T3 += 1

    # === Lattice Loop: bits 30 down to shift ===
    # LINEARIZED: P→P fallthroughs for non-accumulating bits
    
    # first_accum_bit already computed above
    last_non_accum = first_accum_bit + 1
    
    has_non_accum = (last_non_accum <= 30)
    
    if has_non_accum:
        # === LINEAR P CHAIN: non-accumulating bits 30 down to last_non_accum ===
        # Branch directly to N-state target (no trampoline!)
        for bit in range(30, last_non_accum, -1):
            power = 1 << bit
            next_N = f"{prefix}_b{bit-1}_N"
            asm.append(f"{prefix}_b{bit}_P:")
            asm.append(f"        .word   {const_from_pool(power)}, {ADDR_T3}, {next_N}")
        
        bit = last_non_accum
        power = 1 << bit
        next_N = f"{prefix}_b{first_accum_bit}_N"
        asm.append(f"{prefix}_b{bit}_P:")
        asm.append(f"        .word   {const_from_pool(power)}, {ADDR_T3}, {next_N}")
        # Fall through to first accumulating bit P state
    else:
        # byte 3 (shift=24): all bits 30-24 accumulate
        # Need explicit jump since bias falls through here
        pass  # bias falls through to b30_P (first accumulating bit)
    
    # === ACCUMULATING BITS: standard interleaved P/N pattern ===
    # Accumulates into R20 directly (saves 4-op copy in return)
    for bit in range(first_accum_bit, shift - 1, -1):
        power = 1 << bit
        res_bit = bit - shift
        
        if bit == shift:
            next_lbl_P = ".Llb_ret1"
            next_lbl_N = ".Llb_ret1"
        else:
            next_lbl_P = f"{prefix}_b{bit-1}_P"
            next_lbl_N = f"{prefix}_b{bit-1}_N"
        
        # P state — branch directly to next_lbl_N (no trampoline!)
        asm.append(f"{prefix}_b{bit}_P:")
        asm.append(f"        .word   {const_from_pool(power)}, {ADDR_T3}, {next_lbl_N}")
        asm.append(f"        .word   {const_from_pool(-(1<<res_bit))}, {ADDR_R20}, .+4")  # accumulate into R20
        if bit > shift:
            # INLINE next P's test: replaces Z,Z,next_P with useful work
            next_bit = bit - 1
            next_power = 1 << next_bit
            next_res_bit = next_bit - shift
            if next_bit == shift:
                inline_next_N = ".Llb_ret1"
                inline_next_P = ".Llb_ret1"
            else:
                inline_next_N = f"{prefix}_b{next_bit-1}_N"
                inline_next_P = f"{prefix}_b{next_bit-1}_P"
            asm.append(f"        .word   {const_from_pool(next_power)}, {ADDR_T3}, {inline_next_N}")
            asm.append(f"        .word   {const_from_pool(-(1<<next_res_bit))}, {ADDR_R20}, .+4")
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {inline_next_P}")
        elif bit == shift:
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl_P}")
        # else: fall through to next P (no Neg block to skip)
        
        # N state — branch directly to next_lbl_N (no trampoline!)
        asm.append(f"{prefix}_b{bit}_N:")
        asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_T3}, {next_lbl_N}")
        asm.append(f"        .word   {const_from_pool(-(1<<res_bit))}, {ADDR_R20}, .+4")  # accumulate into R20
        # Fallthrough optimization: for bit > shift, next_P is the very next label
        if bit == shift:
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl_P}")
    
    # === N STATES for non-accumulating bits (LINEARIZED N→N) ===
    if has_non_accum:
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
            # N→P: inline next P's test (replaces Z,Z,next_P)
            if bit == last_non_accum:
                # Next P is first_accum_bit P — it has test + accumulate
                fab = first_accum_bit
                fab_power = 1 << fab
                fab_res = fab - shift
                if fab == shift:
                    fab_next_N = ".Llb_ret1"
                    fab_next_P = ".Llb_ret1"
                else:
                    fab_next_N = f"{prefix}_b{fab-1}_N"
                    fab_next_P = f"{prefix}_b{fab-1}_P"
                asm.append(f"        .word   {const_from_pool(fab_power)}, {ADDR_T3}, {fab_next_N}")
                asm.append(f"        .word   {const_from_pool(-(1<<fab_res))}, {ADDR_R20}, .+4")
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {fab_next_P}")
            else:
                # Next P is another non-accum N entry (just test, no accumulate)
                # Actually next_lbl_P points to a P state. For non-accum bits, there's no
                # separate P state - P test is in the accum section. So Z,Z is needed here.
                asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {next_lbl_P}")  # N→P
    
    # === Cold path: T3 <= 0 (sign bit handling) ===
    # OPTIMIZED: Combined restore+branch pattern (operates on T3 directly)
    asm.append(f"{prefix}_le0:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_T3}, {prefix}_neg")  # T3 += 1; if <= 0 → T3 < 0
    # T3 was 0 (now 1): R20 already 0, skip lattice entirely (always branches)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T3}, .Llb_ret1")  # restore+skip
    
    asm.append(f"{prefix}_neg:")
    # T3 was < 0 (now orig+1, still <= 0): restore T3 (orig+1 - 1 = orig <= 0, always branches)
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_T3}, .+4")  # restore+branch (fall through via .+4)
    # T3 < 0 (bit 31 set). Clear bit 31.
    if accumulate_b31:
        asm.append(f"        .word   {const_from_pool(-(1<<res_bit_31))}, {ADDR_R20}, .+4")  # accumulate into R20
    asm.append(f"        .word   {const_from_pool(-2147483648)}, {ADDR_T3}, .+4")  # T3 -= INT_MIN (clear bit 31)
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {prefix}_bias")  # goto bias


def emit_lb():
    """Generate __subleq_lb with O(1) modulo and O(32) bit extraction."""
    asm = []
    asm.append(f"")
    asm.append(f"        .globl  __subleq_lb")
    asm.append(f"        .type   __subleq_lb,@function")
    asm.append(f"")
    asm.append(f"# __subleq_lb: Load byte - Aggressively Optimized")
    asm.append(f"__subleq_lb:")
    
    # === Z-SCRATCH ENTRY: 3 ops (was 4) ===
    # Z is clean at function entry (caller's return sequence clears it)
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")   # Z = -R21 (Z was 0)
    asm.append(f"        .word   {ADDR_T0}, {ADDR_T0}, .+4")   # T0 = 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T0}, .Llb_offset")  # T0 = R21
    
    # ===== O(1) MODULO: addr & 3 using R21 directly (no copy!) =====
    # R21 is clobbered by the lattice; T0 preserves the original address.
    
    asm.append(f".Llb_offset:")
    
    # === BIAS (addresses are ALWAYS positive — skip sign check entirely!) ===
    asm.append(f".Llb_mod_bias:")
    asm.append(f"        .word   {ADDR_MINUS_ONE}, {ADDR_R21}, .+4")  # R21 += 1 (bias)
    
    # === LINEAR P CHAIN: bits 30 down to 2 (non-accumulating) ===
    # Branch directly to N-state targets (no trampolines!)
    for bit in range(30, 2, -1):
        power = 1 << bit
        next_N = f".Llb_mod_b{bit-1}_N"
        asm.append(f".Llb_mod_b{bit}_P:")
        asm.append(f"        .word   {const_from_pool(power)}, {ADDR_R21}, {next_N}")
    
    asm.append(f".Llb_mod_b2_P:")
    asm.append(f"        .word   {const_from_pool(4)}, {ADDR_R21}, .Llb_mod_done_n")
    # Fall through to mod_done (P-path: R21 > 0)
    
    # === MODULO DONE ===
    # P-exit: R21 ∈ [1,4]. Unbias: R21 -= 1 → offset [0,3].
    # N-exit: R21 ∈ [-3,0]. Restore+unbias: R21 += 3 → offset [0,3].
    asm.append(f".Llb_mod_done:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Llb_mod_done_n")  # if R21 ≤ 0 → N path
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Llb_align")           # R21 -= 1 (unbias)
    # Compute Word Address: T0 = byte_addr - offset
    asm.append(f".Llb_align:")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_T0}, .+4")  # T0 -= R21 = word_addr
    # Fall through to ldword (no jump needed!)
    
    # Load Word
    asm.append(f".Llb_ldword:")
    asm.append(f"        .word   {ADDR_T3}, {ADDR_T3}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_T0 | INDIRECT_FLAG}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_T3}, .Llb_branch")
    
    # Clear R20 (Result Accumulator — accumulate directly into return register)
    asm.append(f".Llb_branch:")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    
    # Dispatch on R21 (offset 0-3)
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R21}, .Llb_byte0")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Llb_byte1")
    asm.append(f"        .word   {ADDR_ONE}, {ADDR_R21}, .Llb_byte2")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_ZERO}, .Llb_byte3")  # Z-preserving unconditional jump
    
    # P→N trampolines eliminated: P-chain now branches directly to N states
    
    # === N STATES with INLINE P: bits 30-2 ===
    # Each N-state inlines the NEXT P-state computation. After N→P (fall-through),
    # the inline P fires immediately. If inline P→N (common), branches in 1 more op.
    # Total: 2 ops for N→P + P→N (was 3). Saves ~9 ops per modulo call.
    for bit in range(30, 2, -1):
        power = 1 << bit
        power_prev = 1 << (bit - 1)
        next_N = f".Llb_mod_b{bit-1}_N"
        
        asm.append(f".Llb_mod_b{bit}_N:")
        asm.append(f"        .word   {const_from_pool(-power)}, {ADDR_R21}, {next_N}")  # N→N: branch (1 op)
        
        # Inline P_{bit-1}: subtract power_{bit-1}
        if bit - 1 == 2:
            # Inline P_2: last bit
            asm.append(f"        .word   {const_from_pool(power_prev)}, {ADDR_R21}, .Llb_mod_done_n")  # P→N: done_n
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Llb_mod_done")  # P→P: done
        else:
            inline_branch = f".Llb_mod_b{bit-2}_N"  # P→N: jump to N_{bit-2}
            inline_skip = f".Llb_mod_b{bit-2}_P"    # P→P: jump to P-chain at P_{bit-2}
            asm.append(f"        .word   {const_from_pool(power_prev)}, {ADDR_R21}, {inline_branch}")  # P→N (1 op)
            asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, {inline_skip}")  # P→P: skip (1 op)
    
    # Bit 2: terminal N-state (no inline, final bit)
    asm.append(f".Llb_mod_b2_N:")
    asm.append(f"        .word   {const_from_pool(-4)}, {ADDR_R21}, .Llb_mod_done_n")  # N→N: done_n
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Llb_mod_done")  # N→P: done
    
    # === N-exit cold path: restore + unbias + align ===
    asm.append(f".Llb_mod_done_n:")
    asm.append(f"        .word   {const_from_pool(-3)}, {ADDR_R21}, .+4")        # R21 += 3 (restore+unbias)
    asm.append(f"        .word   {ADDR_R21}, {ADDR_T0}, .+4")        # T0 -= R21 = word_addr
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Llb_ldword")   # jump to ldword

    # ========== SPLIT ENTRY POINTS + BYTE HANDLERS (Interleaved) ==========
    # __subleq_lb_b{0,1,2,3}: R21 = word address (NOT byte address!)
    # Skips the entire modulo lattice (~44 ops saved per call).
    # 4 ops (was 5): fused copy+jump via subleq(Z, T3, handler).
    # subleq(Z, T3, byteN) does T3 = -Z = mem[R21]. If T3 ≤ 0, branch;
    # if T3 > 0, fall through. Either way, .Llb_byteN is reached.
    # Non-split path still jumps to .Llb_byteN labels from dispatch above.
    shifts = [0, 8, 16, 24]
    for byte_pos in range(4):
        asm.append(f"")
        asm.append(f"        .globl  __subleq_lb_b{byte_pos}")
        asm.append(f"__subleq_lb_b{byte_pos}:")
        asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")                       # R20 = 0  (result accumulator)
        asm.append(f"        .word   {ADDR_T3}, {ADDR_T3}, .+4")                         # T3 = 0
        asm.append(f"        .word   {ADDR_R21 | INDIRECT_FLAG}, {ADDR_Z}, .+4")          # Z = -mem[R21]  (Z clean at entry)
        asm.append(f"        .word   {ADDR_Z}, {ADDR_T3}, .Llb_byte{byte_pos}")           # T3 = mem[R21]; both paths reach handler
        # Handler placed immediately after entry — fall-through reaches it
        asm.append(f".Llb_byte{byte_pos}:")
        emit_lattice_extract(asm, shifts[byte_pos], f".Llb_b{byte_pos}")
    
    # Return — R20 already contains the result (no copy needed)
    asm.append(f".Llb_ret1:")
    asm.extend(emit_return_sequence("lb"))
    

    asm.append(f"")
    asm.append(f"        .size   __subleq_lb, . - __subleq_lb")
    
    return asm

if __name__ == "__main__":
    for line in emit_lb():
        print(line)
