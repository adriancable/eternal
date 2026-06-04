#!/usr/bin/env python3
"""
Subleq runtime function: emit_shl

This module was auto-extracted from gen_runtime.py for maintainability.
OPTIMIZED: Unrolled Linear Dispatch (O(N) vs O(7*N))
Result Copy Elision: Chain doubles R20 directly.
"""

from gen_runtime import ADDR_Z, ADDR_ZERO, ADDR_R20, ADDR_R21, ADDR_R22, ADDR_T0, ADDR_T1, emit_return_sequence, const_from_pool, ADDR_ONE, ADDR_MINUS_ONE


def emit_shl():
    """Generate __subleq_shl: R3 = R3 << R4 (left shift).
    
    Algorithm:
    Unrolled Linear Dispatch.
    1. Check shift amount (R4). If <= 0, copy R21→R20 and done.
    2. Copy R21→R20, dispatch 1..31 using linear decrement check.
    3. Jump into a "Fallthrough Chain" of 31 doubling blocks (operates on R20).
    4. If shift >= 32 (fallthrough dispatch), clear R20.
    
    Register usage:
    - R21 (R3) = value to shift (input)
    - R20 = result (output, doubles in-place via chain)
    - R22 = shift amount (dispatch counter)
    """
    asm = []
    asm.append(f"")
    asm.append(f"        .globl  __subleq_shl")
    asm.append(f"        .type   __subleq_shl,@function")
    asm.append(f"")
    asm.append(f"# __subleq_shl: R3 = R3 << R4 (Unrolled Linear Dispatch, Result Copy Elision)")
    asm.append(f"__subleq_shl:")
    
    # R22 = shift amount (used directly, no copy to T0)
    
    # Check R22 <= 0
    asm.append(f".Lshl_chk_le0:")
    asm.append(f"        .word   {ADDR_ZERO}, {ADDR_R22}, .Lshl_copy_input")  # If R22 <= 0, copy R21→R20

    # Copy R21 → R20 using Z-scratch (Z clean at entry, 3 ops)
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")   # Z = -R21 (Z was 0)
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4") # R20 = 0
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .+4")   # R20 = R21

    # Dispatch 1..31
    for i in range(1, 32):
        asm.append(f"        .word   {ADDR_ONE}, {ADDR_R22}, .Lshl_do_{i}")
        
    # Fallthrough: Shift >= 32. Result is 0.
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .Lshl_exit")  # R20 = 0, always jumps (0 <= 0)
    
    # Chain of Doublers — operates on R20 directly
    # .Lshl_do_31 falls through to 30, etc.
    # Total doublings = K.
    # We must enter at K.
    
    for i in range(31, 0, -1):
        # Global split-entry point: caller sets R20=R21, Z=0, then jumps here
        asm.append(f"        .globl  __subleq_shl_{i}")
        asm.append(f"__subleq_shl_{i}:")
        asm.append(f".Lshl_do_{i}:")
        # Double R20
        asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
        asm.append(f"        .word   {ADDR_R20}, {ADDR_Z}, .+4")  # Z = -R20
        asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .+4")  # R20 -= Z -> R20 += R20
        
    # Done — R20 already has the result. Go to exit.
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .Lshl_exit")

    # Copy input path (shift=0 or shift<0): R20 = R21
    asm.append(f".Lshl_copy_input:")
    asm.append(f"        .word   {ADDR_R20}, {ADDR_R20}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_R21}, {ADDR_Z}, .+4")
    asm.append(f"        .word   {ADDR_Z}, {ADDR_R20}, .Lshl_exit")
    
    # Return
    asm.append(f".Lshl_exit:")
    asm.extend(emit_return_sequence("shl"))
    

    
    asm.append(f"")
    asm.append(f"        .size   __subleq_shl, . - __subleq_shl")
    
    return asm


if __name__ == "__main__":
    for line in emit_shl():
        print(line)
