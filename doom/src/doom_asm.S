/* SPDX-License-Identifier: GPL-2.0 */
/*
 * doom_asm.S - Hand-optimized Subleq assembly for DOOM hot functions
 *
 * Calling convention:
 *   R21 = first arg, R22 = second arg, R20 = return value
 *   Callee-saved: R3-R19, R25-R31, SP, FP
 *   T0-T7: clobbered by runtime calls (__subleq_mul, etc.)
 *   T8-T14: free across runtime calls (used for persistent state)
 *   RA-Direct: RA register holds return address on entry.
 *   Non-leaf functions save/restore RA on the stack.
 *
 * Z hygiene: clear Z before use, not after. Comments track Z state.
 */

        .text

/* ---- Register addresses ---- */
.set REG_Z,   12
.set REG_SP,  16
.set REG_RA,  20
.set REG_R20, 96
.set REG_R21, 100
.set REG_R22, 104
.set REG_R23, 108
.set REG_R24, 112
.set ZERO,    144
.set REG_T0,  160
.set REG_T1,  164
.set REG_T2,  168
.set REG_T3,  172
.set REG_T4,  176
.set REG_T5,  180
.set REG_T6,  184
.set REG_T7,  188
.set REG_T8,  192
.set REG_T9,  196
.set REG_T10, 200
.set REG_T11, 204
.set REG_T12, 208
.set REG_T13, 212
.set REG_T14, 216
.set REG_T15, 220
.set REG_R31, 140
.set INDIRECT, 1

/*===========================================================================
 * FixedMul: R20 = (R21 * R22) >> 16  (fixed-point 16.16 multiply)
 *
 * Optimized 3-multiply algorithm:
 *   a = a_hi*65536 + a_lo,  b = b_hi*65536 + b_lo
 *   (a*b)>>16 = a_hi*b + a_lo*b_hi + (a_lo*b_lo)>>16
 *
 * Key insight: a_hi*b = a_hi*(b_hi*65536 + b_lo) folds the old
 * (a_hi*b_hi)<<16 and a_hi*b_lo terms into a single multiply,
 * eliminating one __subleq_mul call and one inline <<16 loop.
 *
 * Register plan (T8-T14, persist across runtime calls):
 *   T8  = a (original)       T9  = b (original)
 *   T10 = a_hi               T11 = a_lo
 *   T12 = b_hi               T13 = b_lo
 *   T14 = result accumulator
 *===========================================================================*/
        .globl  FixedMul
        .type   FixedMul, @function
        .balign 4
FixedMul:
        /* --- Z: clean (entry convention) --- */

        /* Save RA: SP -= 4; [SP] = -RA (non-leaf function) */
        .word   .Lfm_c4, REG_SP, .+4              /* SP -= 4           Z: clean */
        .word   REG_SP | INDIRECT, REG_SP | INDIRECT, .+4  /* [SP] = 0 */
        .word   REG_RA, REG_SP | INDIRECT, .+4    /* [SP] = -RA        */

        /* T8 = R21 (a) — Z-clean 3-insn copy */
        .word   REG_T8, REG_T8, .+4            /* T8 = 0            Z: clean */
        .word   REG_R21, REG_Z, .+4            /* Z = -a            Z: dirty */
        .word   REG_Z, REG_T8, .+4             /* T8 = a            Z: dirty */

        /* T9 = R22 (b) — need Z clean first */
        .word   REG_T9, REG_T9, .+4            /* T9 = 0            Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_R22, REG_Z, .+4            /* Z = -b            Z: dirty */
        .word   REG_Z, REG_T9, .+4             /* T9 = b            Z: dirty */

        /* === a_hi = a >> 16 — call __subleq_sra_16 === */
        /* R21 already = a. __subleq_sra_16 doesn't need R22. */
        .word   REG_RA, REG_RA, .+4                   /* RA = 0 */
        .word   .Lfm_sra1_ret_neg, REG_RA, .+4         /* RA = ret */
        .word   REG_Z, REG_Z, __subleq_sra_16  /* jump (Z clean)    Z: clean */
.Lfm_sra1_ret:
        /* --- Z: clean (returned from sra_16) --- */

        /* T10 = R20 (a_hi) — Z-clean copy */
        .word   REG_T10, REG_T10, .+4          /* T10 = 0           Z: clean */
        .word   REG_R20, REG_Z, .+4            /* Z = -a_hi         Z: dirty */
        .word   REG_Z, REG_T10, .+4            /* T10 = a_hi        Z: dirty */

        /* === a_lo = a - (a_hi << 16) === */
        /* T0 = a_hi, then double 16 times */
        .word   REG_T0, REG_T0, .+4            /* T0 = 0            Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T10, REG_Z, .+4            /* Z = -a_hi         Z: dirty */
        .word   REG_Z, REG_T0, .+4             /* T0 = a_hi         Z: dirty */
        /* 16 doublings: each does Z=0, Z=-T0, T0+=T0 */
.irp i,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
        .word   REG_Z, REG_Z, .+4              /*                   Z: clean */
        .word   REG_T0, REG_Z, .+4             /* Z = -T0           Z: dirty */
        .word   REG_Z, REG_T0, .+4             /* T0 = 2*T0         Z: dirty */
.endr
        /* T0 = a_hi << 16. T11 = a - T0 = a_lo */
        .word   REG_T11, REG_T11, .+4          /* T11 = 0           Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T8, REG_Z, .+4             /* Z = -a            Z: dirty */
        .word   REG_Z, REG_T11, .+4            /* T11 = a           Z: dirty */
        .word   REG_T0, REG_T11, .+4           /* T11 = a_lo        Z: dirty */

        /* === b_hi = b >> 16 — call __subleq_sra_16 === */
        .word   REG_R21, REG_R21, .+4          /* R21 = 0           Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T9, REG_Z, .+4             /* Z = -b            Z: dirty */
        .word   REG_Z, REG_R21, .+4            /* R21 = b           Z: dirty */
        .word   REG_RA, REG_RA, .+4                   /* RA = 0 */
        .word   .Lfm_sra2_ret_neg, REG_RA, .+4         /* RA = ret */
        .word   REG_Z, REG_Z, __subleq_sra_16  /* jump              Z: clean */
.Lfm_sra2_ret:
        /* --- Z: clean --- */

        /* T12 = R20 (b_hi) */
        .word   REG_T12, REG_T12, .+4          /* T12 = 0           Z: clean */
        .word   REG_R20, REG_Z, .+4            /* Z = -b_hi         Z: dirty */
        .word   REG_Z, REG_T12, .+4            /* T12 = b_hi        Z: dirty */

        /* === b_lo = b - (b_hi << 16) === */
        .word   REG_T0, REG_T0, .+4            /* T0 = 0            Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T12, REG_Z, .+4            /* Z = -b_hi         Z: dirty */
        .word   REG_Z, REG_T0, .+4             /* T0 = b_hi         Z: dirty */
.irp i,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
        .word   REG_Z, REG_Z, .+4
        .word   REG_T0, REG_Z, .+4
        .word   REG_Z, REG_T0, .+4
.endr
        .word   REG_T13, REG_T13, .+4          /* T13 = 0           Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T9, REG_Z, .+4             /* Z = -b            Z: dirty */
        .word   REG_Z, REG_T13, .+4            /* T13 = b           Z: dirty */
        .word   REG_T0, REG_T13, .+4           /* T13 = b_lo        Z: dirty */

        /* === T14 = 0 (result) === */
        .word   REG_T14, REG_T14, .+4          /* T14 = 0           Z: dirty */

        /* === Term 1: a_hi * b (no shift needed!) ===
         * (a*b)>>16 = a_hi*b + a_lo*b_hi + (a_lo*b_lo)>>16
         * a_hi*b folds the old (a_hi*b_hi)<<16 and a_hi*b_lo terms
         * into a single multiply, saving one mul call + one <<16 loop.
         */
        .word   REG_R21, REG_R21, .+4          /* R21 = 0           Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T10, REG_Z, .+4            /* Z = -a_hi         Z: dirty */
        .word   REG_Z, REG_R21, .+4            /* R21 = a_hi        Z: dirty */
        .word   REG_R22, REG_R22, .+4          /* R22 = 0           Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T9, REG_Z, .+4             /* Z = -b            Z: dirty */
        .word   REG_Z, REG_R22, .+4            /* R22 = b           Z: dirty */
        .word   REG_RA, REG_RA, .+4                   /* RA = 0 */
        .word   .Lfm_mul1_ret_neg, REG_RA, .+4         /* RA = ret */
        .word   REG_Z, REG_Z, __subleq_mul     /*                   Z: clean */
.Lfm_mul1_ret:
        /* --- Z: clean. R20 = a_hi * b. No shift needed! --- */
        /* T14 += R20                            Z: clean */
        .word   REG_R20, REG_Z, .+4            /* Z = -R20          Z: dirty */
        .word   REG_Z, REG_T14, .+4            /* T14 += R20        Z: dirty */

        /* === Term 2: a_lo * b_hi === */
        .word   REG_R21, REG_R21, .+4          /* R21 = 0           Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T11, REG_Z, .+4            /* Z = -a_lo         Z: dirty */
        .word   REG_Z, REG_R21, .+4            /* R21 = a_lo        Z: dirty */
        .word   REG_R22, REG_R22, .+4          /* R22 = 0           Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T12, REG_Z, .+4            /* Z = -b_hi         Z: dirty */
        .word   REG_Z, REG_R22, .+4            /* R22 = b_hi        Z: dirty */
        .word   REG_RA, REG_RA, .+4                   /* RA = 0 */
        .word   .Lfm_mul2_ret_neg, REG_RA, .+4         /* RA = ret */
        .word   REG_Z, REG_Z, __subleq_mul     /*                   Z: clean */
.Lfm_mul2_ret:
        /* T14 += R20                            Z: clean */
        .word   REG_R20, REG_Z, .+4            /* Z = -R20          Z: dirty */
        .word   REG_Z, REG_T14, .+4            /* T14 += R20        Z: dirty */

        /* === Term 3: (a_lo * b_lo) >> 16 === */
        .word   REG_R21, REG_R21, .+4          /* R21 = 0           Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T11, REG_Z, .+4            /* Z = -a_lo         Z: dirty */
        .word   REG_Z, REG_R21, .+4            /* R21 = a_lo        Z: dirty */
        .word   REG_R22, REG_R22, .+4          /* R22 = 0           Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T13, REG_Z, .+4            /* Z = -b_lo         Z: dirty */
        .word   REG_Z, REG_R22, .+4            /* R22 = b_lo        Z: dirty */
        .word   REG_RA, REG_RA, .+4                   /* RA = 0 */
        .word   .Lfm_mul3_ret_neg, REG_RA, .+4         /* RA = ret */
        .word   REG_Z, REG_Z, __subleq_mul     /*                   Z: clean */
.Lfm_mul3_ret:
        /* R20 = a_lo*b_lo. SRL 16 — R21 = R20 for srl input.       Z: clean */
        .word   REG_R21, REG_R21, .+4          /* R21 = 0           Z: clean */
        .word   REG_R20, REG_Z, .+4            /* Z = -R20          Z: dirty */
        .word   REG_Z, REG_R21, .+4            /* R21 = R20         Z: dirty */
        .word   REG_RA, REG_RA, .+4                   /* RA = 0 */
        .word   .Lfm_srl_ret_neg, REG_RA, .+4         /* RA = ret */
        .word   REG_Z, REG_Z, __subleq_srl_16  /*                   Z: clean */
.Lfm_srl_ret:
        /* T14 += R20                            Z: clean */
        .word   REG_R20, REG_Z, .+4            /* Z = -R20          Z: dirty */
        .word   REG_Z, REG_T14, .+4            /* T14 += R20        Z: dirty */

        /* === Skip over fast path (full path done) === */
        .word   REG_Z, REG_Z, .Lfm_done         /* jump to done       Z: clean */

        /* =====================================================================
         * Small-operand fast path: a in [1, 0xFFFF], a_hi = 0, a_lo = a.
         * result = a * b_hi + (a * b_lo) >> 16
         * Saves: 1 sra_16, 1 <<16 loop, 1 mul vs full path.
         * ===================================================================*/
.Lfm_small:
        /* --- Z: clean (from jump) --- */

        /* b_hi = b >> 16: R21 = b for sra_16 call */
        .word   REG_R21, REG_R21, .+4           /* R21 = 0            Z: clean */
        .word   REG_T9, REG_Z, .+4              /* Z = -b             Z: dirty */
        .word   REG_Z, REG_R21, .+4             /* R21 = b            Z: dirty */
        .word   REG_RA, REG_RA, .+4
        .word   .Lfms_sra_ret_neg, REG_RA, .+4
        .word   REG_Z, REG_Z, __subleq_sra_16   /* Z: clean */
.Lfms_sra_ret:
        /* R20 = b_hi. Z: clean */
        .word   REG_T12, REG_T12, .+4           /* T12 = 0            Z: clean */
        .word   REG_R20, REG_Z, .+4             /* Z = -b_hi          Z: dirty */
        .word   REG_Z, REG_T12, .+4             /* T12 = b_hi         Z: dirty */

        /* b_lo = b - (b_hi << 16) */
        .word   REG_T0, REG_T0, .+4             /* T0 = 0             Z: dirty */
        .word   REG_Z, REG_Z, .+4               /* Z = 0              Z: clean */
        .word   REG_T12, REG_Z, .+4             /* Z = -b_hi          Z: dirty */
        .word   REG_Z, REG_T0, .+4              /* T0 = b_hi          Z: dirty */
.irp i,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
        .word   REG_Z, REG_Z, .+4
        .word   REG_T0, REG_Z, .+4
        .word   REG_Z, REG_T0, .+4
.endr
        /* T13 = b - T0 = b_lo */
        .word   REG_T13, REG_T13, .+4           /* T13 = 0            Z: dirty */
        .word   REG_Z, REG_Z, .+4               /* Z = 0              Z: clean */
        .word   REG_T9, REG_Z, .+4              /* Z = -b             Z: dirty */
        .word   REG_Z, REG_T13, .+4             /* T13 = b            Z: dirty */
        .word   REG_T0, REG_T13, .+4            /* T13 = b_lo         Z: dirty */

        /* T14 = 0 (result accumulator) */
        .word   REG_T14, REG_T14, .+4           /* T14 = 0            Z: dirty */

        /* === Term 1: a * b_hi === */
        .word   REG_R21, REG_R21, .+4           /* R21 = 0            Z: dirty */
        .word   REG_Z, REG_Z, .+4               /* Z = 0              Z: clean */
        .word   REG_T8, REG_Z, .+4              /* Z = -a             Z: dirty */
        .word   REG_Z, REG_R21, .+4             /* R21 = a            Z: dirty */
        .word   REG_R22, REG_R22, .+4           /* R22 = 0            Z: dirty */
        .word   REG_Z, REG_Z, .+4               /* Z = 0              Z: clean */
        .word   REG_T12, REG_Z, .+4             /* Z = -b_hi          Z: dirty */
        .word   REG_Z, REG_R22, .+4             /* R22 = b_hi         Z: dirty */
        .word   REG_RA, REG_RA, .+4
        .word   .Lfms_mul1_ret_neg, REG_RA, .+4
        .word   REG_Z, REG_Z, __subleq_mul      /* Z: clean */
.Lfms_mul1_ret:
        /* R20 = a * b_hi. Z: clean */
        .word   REG_R20, REG_Z, .+4             /* Z = -R20           Z: dirty */
        .word   REG_Z, REG_T14, .+4             /* T14 += a*b_hi      Z: dirty */

        /* === Term 2: (a * b_lo) >> 16 === */
        .word   REG_R21, REG_R21, .+4           /* R21 = 0            Z: dirty */
        .word   REG_Z, REG_Z, .+4               /* Z = 0              Z: clean */
        .word   REG_T8, REG_Z, .+4              /* Z = -a             Z: dirty */
        .word   REG_Z, REG_R21, .+4             /* R21 = a            Z: dirty */
        .word   REG_R22, REG_R22, .+4           /* R22 = 0            Z: dirty */
        .word   REG_Z, REG_Z, .+4               /* Z = 0              Z: clean */
        .word   REG_T13, REG_Z, .+4             /* Z = -b_lo          Z: dirty */
        .word   REG_Z, REG_R22, .+4             /* R22 = b_lo         Z: dirty */
        .word   REG_RA, REG_RA, .+4
        .word   .Lfms_mul2_ret_neg, REG_RA, .+4
        .word   REG_Z, REG_Z, __subleq_mul      /* Z: clean */
.Lfms_mul2_ret:
        /* R20 = a * b_lo. Shift >>16. Z: clean */
        .word   REG_R21, REG_R21, .+4           /* R21 = 0            Z: clean */
        .word   REG_R20, REG_Z, .+4             /* Z = -R20           Z: dirty */
        .word   REG_Z, REG_R21, .+4             /* R21 = R20          Z: dirty */
        .word   REG_RA, REG_RA, .+4
        .word   .Lfms_srl_ret_neg, REG_RA, .+4
        .word   REG_Z, REG_Z, __subleq_srl_16   /* Z: clean */
.Lfms_srl_ret:
        /* R20 = (a * b_lo) >> 16. Z: clean */
        .word   REG_R20, REG_Z, .+4             /* Z = -R20           Z: dirty */
        .word   REG_Z, REG_T14, .+4             /* T14 += (a*b_lo)>>16 Z: dirty */

        /* Fall through to .Lfm_done */

.Lfm_done:
        /* === R20 = T14 (final result) ===      Z: dirty */
        .word   REG_R20, REG_R20, .+4          /* R20 = 0           Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T14, REG_Z, .+4            /* Z = -T14          Z: dirty */
        .word   REG_Z, REG_R20, .+4            /* R20 = T14         Z: dirty */

        /* === Return: restore saved RA, jump === */
        .word   REG_RA, REG_RA, .+4            /* RA = 0            Z: dirty */
        .word   REG_SP | INDIRECT, REG_RA, .+4 /* RA = 0-(-ret)     Z: dirty */
        .word   .Lfm_cn4, REG_SP, .+4          /* SP += 4 (pop)     */
        .word   REG_Z, REG_Z, REG_RA | INDIRECT /* jump to RA       */

/* ---- Constants ---- */
.Lfm_c4:    .word 4
.Lfm_cn4:   .word -4
.Lfm_sra1_ret_neg:  .word -.Lfm_sra1_ret
.Lfm_sra2_ret_neg:  .word -.Lfm_sra2_ret
.Lfm_mul1_ret_neg:  .word -.Lfm_mul1_ret
.Lfm_mul2_ret_neg:  .word -.Lfm_mul2_ret
.Lfm_mul3_ret_neg:  .word -.Lfm_mul3_ret
.Lfm_srl_ret_neg:  .word -.Lfm_srl_ret
.Lfm_cn_0x10000:   .word -0x10000
.Lfms_sra_ret_neg: .word -.Lfms_sra_ret
.Lfms_mul1_ret_neg: .word -.Lfms_mul1_ret
.Lfms_mul2_ret_neg: .word -.Lfms_mul2_ret
.Lfms_srl_ret_neg: .word -.Lfms_srl_ret

.size FixedMul, . - FixedMul

/*===========================================================================
 * FixedDiv2: R20 = ((R21 << 16) / R22)  (fixed-point 16.16 divide)
 *
 * Algorithm (from C, integer-only):
 *   1. Handle signs: make both positive, track parity
 *   2. q = ua / ub, r = ua % ub  (via __subleq_udivrem)
 *   3. 16-step restoring division for fractional bits,
 *      doubling T10 each iteration so it becomes (q<<16)+frac
 *   4. Negate if needed
 *
 * Key optimization: T10 starts as q and is doubled each iteration.
 * After 16 iterations it naturally equals (q<<16)+frac_bits,
 * eliminating the post-loop <<16 shift entirely.
 *
 * Register plan (T8-T14):
 *   T8  = ua (abs(a))        T9  = ub (abs(b))
 *   T10 = quotient → result   T11 = remainder (r)
 *   T13 = neg flag (0/1)      T14 = loop counter
 *===========================================================================*/
        .globl  FixedDiv2
        .type   FixedDiv2, @function
        .balign 4
FixedDiv2:
        /* --- Z: clean (entry convention) --- */

        /* Save RA: SP -= 4; [SP] = -RA (non-leaf function) */
        .word   .Lfd_c4, REG_SP, .+4              /* SP -= 4           Z: clean */
        .word   REG_SP | INDIRECT, REG_SP | INDIRECT, .+4  /* [SP] = 0 */
        .word   REG_RA, REG_SP | INDIRECT, .+4    /* [SP] = -RA        */
        /* T13 = 0 (neg flag) */
        .word   REG_T13, REG_T13, .+4          /*                   Z: clean */

        /* === T8 = |R21| (ua), toggle T13 if R21 < 0 === */
        /* Copy R21 to T8 */
        .word   REG_T8, REG_T8, .+4            /* T8 = 0            Z: clean */
        .word   REG_R21, REG_Z, .+4            /* Z = -a            Z: dirty */
        .word   REG_Z, REG_T8, .+4             /* T8 = a            Z: dirty */
        /* Check sign: subleq(ZERO, T8, le0) — if T8 <= 0, jump */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   ZERO, REG_T8, .Lfd_a_le0       /* T8 -= 0; if<=0    Z: clean */
        /* a > 0: T8 is correct */
        .word   REG_Z, REG_Z, .Lfd_chk_b       /* jump              Z: clean */

.Lfd_a_le0:
        /* a <= 0: check zero vs negative */
        .word   .Lfd_cn1, REG_T8, .Lfd_a_neg   /* T8 += 1; if<=0, neg Z: clean */
        /* a was 0 (now 1): restore T8 = 0 */
        .word   .Lfd_c1, REG_T8, .Lfd_chk_b    /* T8 -= 1 = 0; jump Z: clean */

.Lfd_a_neg:
        /* a was negative: restore T8, then negate */
        .word   .Lfd_c1, REG_T8, .+4           /* T8 -= 1 (restore) Z: clean */
        /* T8 = -T8 (negate in place) */
        .word   REG_T0, REG_T0, .+4            /* T0 = 0            Z: clean */
        .word   REG_T8, REG_T0, .+4            /* T0 = -T8 = |a|    Z: clean */
        .word   REG_T8, REG_T8, .+4            /* T8 = 0            Z: clean */
        .word   REG_T0, REG_Z, .+4             /* Z = -T0 = -|a|    Z: dirty */
        .word   REG_Z, REG_T8, .+4             /* T8 = |a|          Z: dirty */
        /* Toggle neg flag */
        .word   .Lfd_cn1, REG_T13, .+4         /* T13 += 1          Z: dirty */
        .word   REG_Z, REG_Z, .Lfd_chk_b       /* jump              Z: clean */

.Lfd_chk_b:
        /* --- Z: clean --- */
        /* === T9 = |R22| (ub), toggle T13 if R22 < 0 === */
        .word   REG_T9, REG_T9, .+4            /* T9 = 0            Z: clean */
        .word   REG_R22, REG_Z, .+4            /* Z = -b            Z: dirty */
        .word   REG_Z, REG_T9, .+4             /* T9 = b            Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   ZERO, REG_T9, .Lfd_b_le0       /* T9 -= 0; if<=0    Z: clean */
        .word   REG_Z, REG_Z, .Lfd_do_div      /* jump              Z: clean */

.Lfd_b_le0:
        .word   .Lfd_cn1, REG_T9, .Lfd_b_neg   /* T9 += 1; if<=0, neg */
        .word   .Lfd_c1, REG_T9, .Lfd_do_div   /* b was 0; jump     */

.Lfd_b_neg:
        .word   .Lfd_c1, REG_T9, .+4           /* restore T9        */
        .word   REG_T0, REG_T0, .+4
        .word   REG_T9, REG_T0, .+4            /* T0 = -T9 = |b|   */
        .word   REG_T9, REG_T9, .+4
        .word   REG_T0, REG_Z, .+4             /* Z = -|b|          Z: dirty */
        .word   REG_Z, REG_T9, .+4             /* T9 = |b|          Z: dirty */
        .word   .Lfd_cn1, REG_T13, .+4         /* toggle neg        */
        .word   REG_Z, REG_Z, .Lfd_do_div      /*                   Z: clean */

.Lfd_do_div:
        /* --- Z: clean. T8 = ua, T9 = ub, T13 = neg flag --- */

        /* === Call __subleq_udivrem(ua, ub) → R21=q, R22=r === */
        .word   REG_R21, REG_R21, .+4          /* R21 = 0           Z: clean */
        .word   REG_T8, REG_Z, .+4             /* Z = -ua           Z: dirty */
        .word   REG_Z, REG_R21, .+4            /* R21 = ua          Z: dirty */
        .word   REG_R22, REG_R22, .+4          /* R22 = 0           Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T9, REG_Z, .+4             /* Z = -ub           Z: dirty */
        .word   REG_Z, REG_R22, .+4            /* R22 = ub          Z: dirty */
        .word   REG_RA, REG_RA, .+4                   /* RA = 0 */
        .word   .Lfd_div_ret_neg, REG_RA, .+4         /* RA = ret */
        .word   REG_Z, REG_Z, __subleq_udivrem /*                   Z: clean */
.Lfd_div_ret:
        /* --- Z: clean. R21 = quotient, R22 = remainder --- */

        /* T10 = quotient (R21) */
        .word   REG_T10, REG_T10, .+4          /* T10 = 0           Z: clean */
        .word   REG_R21, REG_Z, .+4            /* Z = -q            Z: dirty */
        .word   REG_Z, REG_T10, .+4            /* T10 = q           Z: dirty */

        /* T11 = remainder (R22) */
        .word   REG_T11, REG_T11, .+4          /* T11 = 0           Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_R22, REG_Z, .+4            /* Z = -r            Z: dirty */
        .word   REG_Z, REG_T11, .+4            /* T11 = r           Z: dirty */

        /* T14 = 16 (loop counter) */
        .word   REG_T14, REG_T14, .+4          /* T14 = 0           Z: dirty */
        .word   .Lfd_cn16, REG_T14, .+4        /* T14 = 16          */

        /* === 16-step restoring division loop ===
         * Each iteration doubles T10 and shifts in one fractional bit.
         * After 16 iterations, T10 = (q << 16) + frac_bits.
         */
        .word   REG_Z, REG_Z, .+4              /* Z = 0 (clean for loop entry) */
.Lfd_loop:
        /* --- Z: clean (guaranteed) --- */

        /* Double r: T11 = 2r (2 insn using Z-clean trick) */
        .word   REG_T11, REG_Z, .+4            /* Z = -r            Z: dirty */
        .word   REG_Z, REG_T11, .+4            /* T11 = 2r          Z: dirty */

        /* Double T10: T10 = 2*T10 (shift quotient/result left 1) */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T10, REG_Z, .+4            /* Z = -T10          Z: dirty */
        .word   REG_Z, REG_T10, .+4            /* T10 = 2*T10       Z: dirty */

        /* Test: is 2r >= ub? Build T0 = ub, subtract 2r. */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T0, REG_T0, .+4            /* T0 = 0            Z: clean */
        .word   REG_T9, REG_Z, .+4             /* Z = -ub           Z: dirty */
        .word   REG_Z, REG_T0, .+4             /* T0 = ub           Z: dirty */
        .word   REG_T11, REG_T0, .Lfd_bit1     /* T0 = ub-2r; if<=0 → bit1 */

        /* Bit 0 (fall-through): 2r < ub. r and T10 already correct. */
        .word   REG_Z, REG_Z, .Lfd_next        /* jump over bit1    Z: clean */

.Lfd_bit1:
        /* Bit 1: 2r >= ub. r = 2r - ub = -(ub-2r) = -T0 */
        .word   REG_T11, REG_T11, .+4          /* T11 = 0           */
        .word   REG_T0, REG_T11, .+4           /* T11 = -T0 = 2r-ub */
        /* T10 += 1 (set lowest bit) */
        .word   .Lfd_cn1, REG_T10, .+4         /* T10 += 1          */
        /* fall through to .Lfd_next */

.Lfd_next:
        .word   .Lfd_c1, REG_T14, .Lfd_loop_done
        .word   REG_Z, REG_Z, .Lfd_loop        /* jump (Z clean)    */

.Lfd_loop_done:
        /* === Result is already in T10 = (q<<16) + frac === */
        .word   REG_R20, REG_R20, .+4          /* R20 = 0           Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T10, REG_Z, .+4            /* Z = -T10          Z: dirty */
        .word   REG_Z, REG_R20, .+4            /* R20 = T10         Z: dirty */

        /* === Negate if T13 is odd (T13 = 1) === */
        /* Check T13: subleq(.Lfd_c1, T13, ...) → T13 -= 1; if <= 0, was 0 or 1 */
        .word   .Lfd_c1, REG_T13, .Lfd_chk_neg /* T13 -= 1; if<=0   */
        /* T13 was > 1 (shouldn't happen with just two toggles, but safe): 
         * T13 was 2 → no negate needed */
        .word   REG_Z, REG_Z, .Lfd_ret         /* jump              Z: clean */

.Lfd_chk_neg:
        /* T13 was 0 or 1. If was 1 (now 0): negate. If was 0 (now -1): don't. */
        /* Check: T13 <= -1 means was 0 → no negate */
        .word   ZERO, REG_T13, .Lfd_t13_le0    /* if T13 <= 0       Z: clean */
        /* T13 > 0: impossible after -= 1 from 0 or 1, but safe */
        .word   REG_Z, REG_Z, .Lfd_ret

.Lfd_t13_le0:
        /* T13 = 0 (was 1) → negate R20. Or T13 = -1 (was 0) → no negate. */
        /* Disambiguate: add 1, if <= 0 then was -1 (no negate) */
        .word   .Lfd_cn1, REG_T13, .Lfd_ret    /* T13 += 1; if<=0, was <= -1, no negate */
        /* T13 was 0 (i.e., original was 1): negate R20 */
        .word   REG_T0, REG_T0, .+4            /* T0 = 0            */
        .word   REG_R20, REG_T0, .+4           /* T0 = -R20         */
        .word   REG_R20, REG_R20, .+4          /* R20 = 0           */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T0, REG_Z, .+4             /* Z = -T0 = R20_old Z: dirty */
        .word   REG_Z, REG_R20, .+4            /* R20 = -R20_old    Z: dirty */
        /* fall through to ret */

.Lfd_ret:
        /* === Return: restore saved RA, jump === */
        .word   REG_RA, REG_RA, .+4            /* RA = 0            Z: varies */
        .word   REG_SP | INDIRECT, REG_RA, .+4 /* RA = 0-(-ret)     Z: dirty */
        .word   .Lfd_cn4, REG_SP, .+4          /* SP += 4 (pop)     */
        .word   REG_Z, REG_Z, REG_RA | INDIRECT /* jump to RA       */

/* ---- FixedDiv2 Constants ---- */
.Lfd_c1:    .word 1
.Lfd_cn1:   .word -1
.Lfd_c4:    .word 4
.Lfd_cn4:   .word -4
.Lfd_cn16:  .word -16
.Lfd_div_ret_neg:  .word -.Lfd_div_ret

.size FixedDiv2, . - FixedDiv2

/*===========================================================================
 * RenderBlit: 2x2 pixel-doubling blit from source to framebuffer.
 *
 * void RenderBlit(uint32_t *sp, uint32_t *dp,
 *                 int width, int height, int fb_stride_words);
 *
 * Args: R21=sp, R22=dp, R23=width, R24=height
 *       5th arg (fb_stride_words) at [SP] (pushed by caller)
 *
 * For each source pixel, writes to 4 framebuffer locations:
 *   dp[0], dp[1], dp[stride], dp[stride+1]
 * After each row, advances by 2*stride_bytes from saved row start.
 *
 * Register plan (T8-T15):
 *   T8  = sp (source pointer, advances by 4)
 *   T9  = dp0 (dest row 0 pointer, advances 8 per pixel)
 *   T10 = dp1 (dest row 1 pointer = dp0 + stride_bytes)
 *   T11 = inner counter (counts down from width)
 *   T12 = width (constant, for resetting inner counter)
 *   T13 = stride_bytes (fb_stride_words * 4)
 *   T14 = outer counter (counts down from height)
 *   T15 = row_step (2*stride_bytes - width*8): added to T9/T10 after each row
 *   T0  = -px (negated pixel value, reused for all 4 stores)
 *
 * Inner loop: 17 insns per pixel (no Z clears between stores).
 *===========================================================================*/
        .globl  RenderBlit
        .type   RenderBlit, @function
        .balign 4
RenderBlit:
        /* --- Z: clean (entry convention) --- */
        /* Leaf function: no RA save needed. */

        /* === T8 = sp (R21) === */
        .word   REG_T8, REG_T8, .+4
        .word   REG_R21, REG_Z, .+4
        .word   REG_Z, REG_T8, .+4              /* T8 = sp            Z: dirty */

        /* === T12 = width (R23) === */
        .word   REG_T12, REG_T12, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_R23, REG_Z, .+4
        .word   REG_Z, REG_T12, .+4             /* T12 = width        Z: dirty */

        /* === T14 = height (R24) === */
        .word   REG_T14, REG_T14, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_R24, REG_Z, .+4
        .word   REG_Z, REG_T14, .+4             /* T14 = height       Z: dirty */

        /* === T13 = fb_stride_words * 4 from [SP] === */
        .word   REG_T13, REG_T13, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_SP | INDIRECT, REG_Z, .+4   /* Z = -fb_stride_words */
        .word   REG_Z, REG_T13, .+4             /* T13 = fb_stride_words Z: dirty */
        /* T13 *= 4 (two doublings) */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T13, REG_Z, .+4
        .word   REG_Z, REG_T13, .+4             /* T13 *= 2           Z: dirty */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T13, REG_Z, .+4
        .word   REG_Z, REG_T13, .+4             /* T13 = stride_bytes Z: dirty */

        /* === T9 = dp (R22) === */
        .word   REG_T9, REG_T9, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_R22, REG_Z, .+4
        .word   REG_Z, REG_T9, .+4              /* T9 = dp            Z: dirty */

        /* === T10 = dp + stride_bytes === */
        .word   REG_T10, REG_T10, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T9, REG_Z, .+4
        .word   REG_Z, REG_T10, .+4             /* T10 = dp           Z: dirty */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T13, REG_Z, .+4
        .word   REG_Z, REG_T10, .+4             /* T10 = dp+stride    Z: dirty */

        /* === T15 = 2*stride_bytes - width*8 (row advance delta) ===
         * After inner loop T9 advanced by width*8, so T9 + T15 = next row0 start.
         * width*8 = width*4*2. Build as: T15 = 2*stride - width*8.
         * Step 1: T15 = 2*stride (copy T13 twice into T15)
         */
        .word   REG_T15, REG_T15, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T13, REG_Z, .+4
        .word   REG_Z, REG_T15, .+4             /* T15 = stride_bytes Z: dirty */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T13, REG_Z, .+4
        .word   REG_Z, REG_T15, .+4             /* T15 = 2*stride     Z: dirty */
        /* Step 2: T15 -= width*8. Compute width*8 in T0, subtract from T15.
         * width*8 via 3 doublings of T12. */
        .word   REG_T0, REG_T0, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T12, REG_Z, .+4
        .word   REG_Z, REG_T0, .+4              /* T0 = width         Z: dirty */
        /* double T0 three times: width → width*8 */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T0, REG_Z, .+4
        .word   REG_Z, REG_T0, .+4              /* T0 = width*2       Z: dirty */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T0, REG_Z, .+4
        .word   REG_Z, REG_T0, .+4              /* T0 = width*4       Z: dirty */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T0, REG_Z, .+4
        .word   REG_Z, REG_T0, .+4              /* T0 = width*8       Z: dirty */
        /* T15 -= T0 */
        .word   REG_T0, REG_T15, .+4            /* T15 -= width*8     Z: dirty */
        /* (T15 will be negative in padding-free case: 2*stride - width*8
         *  = 2*(width*4) - width*8 = 0. Or positive if stride > width*4.) */

        /* === Outer loop: iterate over rows === */
.Lrb_row:
        /* T11 = width (reset inner counter) */
        .word   REG_T11, REG_T11, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T12, REG_Z, .+4
        .word   REG_Z, REG_T11, .+4             /* T11 = width        Z: dirty */

        /* === Inner loop: 17 insns / pixel ===
         * T0 = -px (negated); stores use: clear_indirect + subtract_T0.
         * subleq(T0, Tx|I) = m[m[Tx]] -= m[T0] = m[dp] -= (-px) = m[dp] += px.
         */
.Lrb_pixel:
        /* Load: T0 = -px = -(m[T8])                   2 insns */
        .word   REG_T0, REG_T0, .+4             /* T0 = 0             Z: dirty */
        .word   REG_T8 | INDIRECT, REG_T0, .+4  /* T0 -= m[sp] = -px  Z: dirty */

        /* Store to row0[0]: m[T9] = px              2 insns */
        .word   REG_T9 | INDIRECT, REG_T9 | INDIRECT, .+4  /* m[dp0] = 0 */
        .word   REG_T0, REG_T9 | INDIRECT, .+4  /* m[dp0] += px       Z: dirty */

        /* Advance T9 by 4                            1 insn */
        .word   .Lrb_cn4, REG_T9, .+4           /* T9 += 4            */

        /* Store to row0[1]: m[T9] = px              2 insns */
        .word   REG_T9 | INDIRECT, REG_T9 | INDIRECT, .+4  /* m[dp0+4] = 0 */
        .word   REG_T0, REG_T9 | INDIRECT, .+4  /* m[dp0+4] += px     Z: dirty */

        /* Advance T9 by 4                            1 insn */
        .word   .Lrb_cn4, REG_T9, .+4           /* T9 += 4            */

        /* Store to row1[0]: m[T10] = px             2 insns */
        .word   REG_T10 | INDIRECT, REG_T10 | INDIRECT, .+4  /* m[dp1] = 0 */
        .word   REG_T0, REG_T10 | INDIRECT, .+4 /* m[dp1] += px       Z: dirty */

        /* Advance T10 by 4                           1 insn */
        .word   .Lrb_cn4, REG_T10, .+4          /* T10 += 4           */

        /* Store to row1[1]: m[T10] = px             2 insns */
        .word   REG_T10 | INDIRECT, REG_T10 | INDIRECT, .+4  /* m[dp1+4] = 0 */
        .word   REG_T0, REG_T10 | INDIRECT, .+4 /* m[dp1+4] += px     Z: dirty */

        /* Advance T10 by 4                           1 insn */
        .word   .Lrb_cn4, REG_T10, .+4          /* T10 += 4           */

        /* Advance sp                                 1 insn */
        .word   .Lrb_cn4, REG_T8, .+4           /* T8 += 4 (sp++)     */

        /* Inner counter: T11 -= 1; if <= 0, done      2 insns */
        .word   .Lrb_c1, REG_T11, .Lrb_inner_done
        .word   REG_Z, REG_Z, .Lrb_pixel        /* loop               Z: clean */

.Lrb_inner_done:
        /* Row advance using precomputed T15.
         * T9 += T15: new row0 start = old_row0_start + 2*stride_bytes
         * (T15 = 2*stride - width*8, and T9 has advanced by width*8)
         */
        .word   REG_Z, REG_Z, .+4               /* Z = 0              Z: clean */
        .word   REG_T15, REG_Z, .+4             /* Z = -T15           Z: dirty */
        .word   REG_Z, REG_T9, .+4              /* T9 += T15          Z: dirty */

        /* T10 = T9 + stride_bytes (new row1 pointer) */
        .word   REG_T10, REG_T10, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T9, REG_Z, .+4
        .word   REG_Z, REG_T10, .+4             /* T10 = T9           Z: dirty */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T13, REG_Z, .+4
        .word   REG_Z, REG_T10, .+4             /* T10 = T9+stride    Z: dirty */

        /* Outer counter: T14 -= 1; if <= 0, done */
        .word   .Lrb_c1, REG_T14, .Lrb_done
        .word   REG_Z, REG_Z, .Lrb_row         /* loop               Z: clean */

.Lrb_done:
        /* Return (leaf function, RA still valid) */
        .word   REG_Z, REG_Z, REG_RA | INDIRECT /* jump to RA         */

/* ---- RenderBlit Constants ---- */
.Lrb_c1:       .word 1
.Lrb_cn4:      .word -4

.size RenderBlit, . - RenderBlit

/*===========================================================================
 * R_DrawColumn: Hand-optimized column renderer (no arguments — reads globals)
 *
 * Algorithm: Split-accumulator from r_draw.c. The inner loop uses ONLY
 * add/subtract/compare — zero runtime calls per pixel.
 *
 * Setup phase (uses runtime calls for mul/shift):
 *   1. Load globals: dc_yl, dc_yh, dc_x, dc_iscale, dc_texturemid,
 *      dc_source, dc_colormap, centery
 *   2. count = dc_yh - dc_yl; if < 0 return
 *   3. dest = ylookup[dc_yl] + columnofs[dc_x]
 *   4. frac = dc_texturemid + (dc_yl - centery) * fracstep
 *   5. Split frac into tex_y (int) and frac_lo (fractional)
 *   6. Split fracstep into step_int and step_lo
 *   7. Normalize tex_y to [0,127], step_int to [0,127]
 *
 * Inner loop register plan:
 *   T8  = dest pointer            T9  = tex_y [0,127]
 *   T10 = frac_lo [-0xFFFF,0]     T11 = step_lo (constant)
 *   T12 = step_int (constant)     T13 = dc_source base
 *   T14 = dc_colormap base        T0  = count
 *   T1-T3, T4-T7 = scratch
 *
 * Per-pixel inner loop body (all subleq, no calls):
 *   pixel = dc_colormap[dc_source[tex_y]]  (two indirect loads)
 *   m[dest] = pixel                         (indirect store)
 *   dest += SCREENWIDTH*4
 *   frac_lo += step_lo; if > 0: frac_lo -= 0x10000; tex_y++
 *   tex_y += step_int; if >= 128: tex_y -= 128
 *   count--; if >= 0 loop
 *===========================================================================*/
        .globl  R_DrawColumn
        .type   R_DrawColumn, @function
        .balign 4
R_DrawColumn:

        /* === Z: clean (entry convention) === */

        /* Save RA: SP -= 4; [SP] = -RA (non-leaf function) */
        .word   .Ldc_c4, REG_SP, .+4              /* SP -= 4           Z: clean */
        .word   REG_SP | INDIRECT, REG_SP | INDIRECT, .+4  /* [SP] = 0 */
        .word   REG_RA, REG_SP | INDIRECT, .+4    /* [SP] = -RA        */

        /* ---- Load dc_yl into T8, dc_yh into T9 ---- */
        .word   REG_T8, REG_T8, .+4            /* T8 = 0            Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   dc_yl, REG_Z, .+4              /* Z = -dc_yl        Z: dirty */
        .word   REG_Z, REG_T8, .+4             /* T8 = dc_yl        Z: dirty */

        .word   REG_T9, REG_T9, .+4            /* T9 = 0            Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   dc_yh, REG_Z, .+4              /* Z = -dc_yh        Z: dirty */
        .word   REG_Z, REG_T9, .+4             /* T9 = dc_yh        Z: dirty */

        /* ---- count = dc_yh - dc_yl; if < 0 return ---- */
        /* T0 = count = T9 - T8 */
        .word   REG_T0, REG_T0, .+4            /* T0 = 0            Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T9, REG_Z, .+4             /* Z = -dc_yh        Z: dirty */
        .word   REG_Z, REG_T0, .+4             /* T0 = dc_yh        Z: dirty */
        .word   REG_T8, REG_T0, .+4            /* T0 = dc_yh-dc_yl  Z: ? */
        /* if count <= 0 AND count != 0 (i.e., count < 0): return */
        /* subleq(ZERO, T0, le0) — but we need count < 0, not <= 0 */
        /* Actually: count = dc_yh - dc_yl. if count < 0, return. */
        /* The C code checks "if (count < 0) return" then uses count as a
         * do-while counter (count+1 pixels). Let's check: count < 0 means
         * dc_yh < dc_yl, nothing to draw. count = 0 means 1 pixel. */
        /* Test: is T0 < 0? Add 1, test <= 0 but that's wrong for 0.
         * Better: subtract 0 from T0 — subleq(ZERO, T0, .Ldc_neg_count)
         * branches if T0 <= 0. We want to return only if T0 < 0 (strictly).
         * T0 = 0 means draw 1 pixel. So we branch if T0 <= -1:
         * subleq(.Ldc_c1, T0, .Ldc_neg) → T0 -= 1; if <= 0 then original T0 <= 0.
         * But that burns T0. Let's just do: if T0 <= -1 return. 
         * Test with ZERO: subleq(ZERO, T0, .Ldc_maybe_ret) → T0 -= 0. 
         * Branches if T0 <= 0 (includes count=0 which should draw).
         * So: if T0 <= 0, check if T0 == 0 (draw 1 pixel) vs T0 < 0 (return).
         */
        .word   ZERO, REG_T0, .Ldc_maybe_neg   /* T0 -= 0; if <= 0  Z: clean */
        .word   REG_Z, REG_Z, .Ldc_count_ok    /* T0 > 0: continue  Z: clean */

.Ldc_maybe_neg:
        /* T0 <= 0. If T0 == 0, count is 0 (draw 1 pixel). If T0 < 0, return. */
        .word   .Ldc_cn1, REG_T0, .Ldc_early_ret /* T0 += 1; if <= 0 → was < 0 */
        /* T0 was 0 (now 1): restore T0 = 0 */
        .word   .Ldc_c1, REG_T0, .+4           /* T0 -= 1 = 0      */
        .word   REG_Z, REG_Z, .Ldc_count_ok

.Ldc_early_ret:
        /* count < 0: restore saved RA and return */
        .word   REG_RA, REG_RA, .+4
        .word   REG_SP | INDIRECT, REG_RA, .+4
        .word   .Ldc_cn4, REG_SP, .+4
        .word   REG_Z, REG_Z, REG_RA | INDIRECT

.Ldc_count_ok:
        /* --- T0 = count (>= 0), T8 = dc_yl. Z: clean (all paths clear Z) --- */
        /* Save count to scratch (runtime calls will clobber T0) */
        .word   REG_T0, REG_Z, .+4             /* Z = -count        Z: dirty */
        .word   REG_Z, .Ldc_save_count, .+4    /* save_count = count Z: dirty */

        /* ---- Load dc_iscale (fracstep) into T11 ---- */
        .word   REG_T11, REG_T11, .+4           /* T11 = 0           Z: dirty */
        .word   REG_Z, REG_Z, .+4               /* Z = 0             Z: clean */
        .word   dc_iscale, REG_Z, .+4           /* Z = -dc_iscale    Z: dirty */
        .word   REG_Z, REG_T11, .+4             /* T11 = dc_iscale   Z: dirty */

        /* ---- Load dc_texturemid into T12 ---- */
        .word   REG_T12, REG_T12, .+4           /* T12 = 0           Z: dirty */
        .word   REG_Z, REG_Z, .+4               /* Z = 0             Z: clean */
        .word   dc_texturemid, REG_Z, .+4       /* Z = -dc_texturemid Z: dirty */
        .word   REG_Z, REG_T12, .+4             /* T12 = dc_texturemid Z: dirty */

        /* ---- Load dc_source into T13 (single deref) ---- */
        .word   REG_T13, REG_T13, .+4           /* T13 = 0           Z: dirty */
        .word   REG_Z, REG_Z, .+4               /* Z = 0             Z: clean */
        .word   dc_source, REG_Z, .+4           /* Z = -dc_source    Z: dirty */
        .word   REG_Z, REG_T13, .+4             /* T13 = dc_source   Z: dirty */

        /* TRAP */
        /* .word   4, 4, 4 */

        /* ---- Load dc_colormap into T14 (single deref) ---- */
        .word   REG_T14, REG_T14, .+4           /* T14 = 0           Z: dirty */
        .word   REG_Z, REG_Z, .+4               /* Z = 0             Z: clean */
        .word   dc_colormap, REG_Z, .+4         /* Z = -dc_colormap  Z: dirty */
        .word   REG_Z, REG_T14, .+4             /* T14 = dc_colormap Z: dirty */

        /* ---- Load centery into T1 ---- */
        .word   REG_T1, REG_T1, .+4             /* T1 = 0            Z: dirty */
        .word   REG_Z, REG_Z, .+4               /* Z = 0             Z: clean */
        .word   centery, REG_Z, .+4             /* Z = -centery      Z: dirty */
        .word   REG_Z, REG_T1, .+4              /* T1 = centery      Z: dirty */

        /* ---- Compute frac = dc_texturemid + (dc_yl - centery) * fracstep ---- */
        /* R21 = dc_yl - centery */
        .word   REG_R21, REG_R21, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T8, REG_Z, .+4             /* Z = -dc_yl        */
        .word   REG_Z, REG_R21, .+4            /* R21 = dc_yl       */
        .word   REG_T1, REG_R21, .+4           /* R21 = dc_yl - centery */

        /* R22 = fracstep (T11) */
        .word   REG_R22, REG_R22, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T11, REG_Z, .+4
        .word   REG_Z, REG_R22, .+4            /* R22 = fracstep    */

        /* Call __subleq_mul: R20 = R21 * R22 = (dc_yl-centery)*fracstep */
        .word   REG_RA, REG_RA, .+4                   /* RA = 0 */
        .word   .Ldc_mul1_ret_neg, REG_RA, .+4         /* RA = ret */
        .word   REG_Z, REG_Z, __subleq_mul
.Ldc_mul1_ret:
        /* R20 = (dc_yl-centery)*fracstep. Z: clean */
        /* frac = dc_texturemid + R20. Store in T2 AND save to scratch
         * (sra_16 call will clobber T2). */
        .word   REG_T2, REG_T2, .+4            /* T2 = 0            Z: clean */
        .word   REG_T12, REG_Z, .+4            /* Z = -dc_texturemid Z: dirty */
        .word   REG_Z, REG_T2, .+4             /* T2 = dc_texturemid Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_R20, REG_Z, .+4            /* Z = -R20          Z: dirty */
        .word   REG_Z, REG_T2, .+4             /* T2 = frac         Z: dirty */
        /* Save frac to scratch location */
        .word   .Ldc_save_frac, .Ldc_save_frac, .+4  /* save_frac = 0 */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   REG_T2, REG_Z, .+4             /* Z = -frac         Z: dirty */
        .word   REG_Z, .Ldc_save_frac, .+4     /* save_frac = frac  Z: dirty */

        /* ---- Split frac: tex_y = frac >> 16 (sra_16) ---- */
        .word   REG_R21, REG_R21, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T2, REG_Z, .+4
        .word   REG_Z, REG_R21, .+4            /* R21 = frac        */
        .word   REG_RA, REG_RA, .+4                   /* RA = 0 */
        .word   .Ldc_sra1_ret_neg, REG_RA, .+4         /* RA = ret */
        .word   REG_Z, REG_Z, __subleq_sra_16
.Ldc_sra1_ret:
        /* R20 = frac >> 16 = tex_y (signed). Z: clean */
        /* Save tex_y to T9 */
        .word   REG_T9, REG_T9, .+4
        .word   REG_R20, REG_Z, .+4
        .word   REG_Z, REG_T9, .+4             /* T9 = tex_y        Z: dirty */

        /* ---- frac_lo = (frac & 0xFFFF) - 0xFFFF ---- */
        /* frac_lo = frac - (tex_y << 16) - 0xFFFF */
        /* First: tex_y << 16 via 16 doublings in T1 */
        .word   REG_T1, REG_T1, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T9, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4             /* T1 = tex_y        */
.irp i,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4
.endr
        /* T10 = frac - T1 - 0xFFFF */
        /* Restore frac from scratch (T2 was clobbered by sra_16) */
        .word   REG_T10, REG_T10, .+4
        .word   REG_Z, REG_Z, .+4
        .word   .Ldc_save_frac, REG_Z, .+4
        .word   REG_Z, REG_T10, .+4            /* T10 = frac        */
        .word   REG_T1, REG_T10, .+4           /* T10 = frac - (tex_y<<16) = frac&0xFFFF */
        .word   .Ldc_c_0xFFFF, REG_T10, .+4    /* T10 -= 0xFFFF = frac_lo */
        /* Reset save_frac for next call */
        .word   .Ldc_save_frac, .Ldc_save_frac, .+4

        /* ---- Split fracstep: step_int = fracstep >> 16 ---- */
        .word   REG_R21, REG_R21, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T11, REG_Z, .+4
        .word   REG_Z, REG_R21, .+4            /* R21 = fracstep    */
        .word   REG_RA, REG_RA, .+4                   /* RA = 0 */
        .word   .Ldc_sra2_ret_neg, REG_RA, .+4         /* RA = ret */
        .word   REG_Z, REG_Z, __subleq_sra_16
.Ldc_sra2_ret:
        /* R20 = step_int. Z: clean */
        /* step_lo = fracstep - (step_int << 16) */
        /* Compute step_int << 16 in T1 */
        .word   REG_T1, REG_T1, .+4
        .word   REG_R20, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4             /* T1 = step_int     */
.irp i,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4
.endr
        /* T12 (step_int) = R20 */
        .word   REG_T12, REG_T12, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_R20, REG_Z, .+4
        .word   REG_Z, REG_T12, .+4            /* T12 = step_int    Z: dirty */

        /* T11 (step_lo) = fracstep(T11) - T1 */
        /* T11 still has fracstep from before the sra call? No — T11 was set
         * to fracstep but __subleq_mul/sra trash T0-T7 only. T8-T14 survive.
         * T11 still = fracstep. Good. */
        .word   REG_T1, REG_T11, .+4           /* T11 = fracstep - (step_int<<16) = step_lo */

        /* ---- Normalize step_int to [0,127] ---- */
        /* while step_int >= 128: step_int -= 128 */
.Ldc_norm_si:
        .word   .Ldc_c128, REG_T12, .Ldc_si_le /* T12 -= 128; if <= 0 */
        /* T12 > 0 after subtracting 128: still >= 128+1, keep looping */
        .word   REG_Z, REG_Z, .Ldc_norm_si
.Ldc_si_le:
        /* T12 <= 0 after -= 128. Was T12 < 128 originally? Add 128 back. */
        .word   .Ldc_cn128, REG_T12, .+4       /* T12 += 128 (restore) */

        /* ---- ×4 pre-scale step_int for inner loop ---- */
        /* T12 = step_int * 4 via 2 doublings */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T12, REG_Z, .+4
        .word   REG_Z, REG_T12, .+4             /* T12 *= 2          */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T12, REG_Z, .+4
        .word   REG_Z, REG_T12, .+4             /* T12 = step_int*4  Z: dirty */

        /* ---- Normalize tex_y to [0,127] ---- */
.Ldc_norm_ty_pos:
        .word   ZERO, REG_T9, .Ldc_ty_le0      /* if T9 <= 0        */
        .word   REG_Z, REG_Z, .Ldc_ty_check_hi /* T9 > 0            */
.Ldc_ty_le0:
        .word   .Ldc_cn1, REG_T9, .Ldc_ty_neg  /* T9 += 1; if <= 0, negative */
        /* T9 was 0 (now 1): restore */
        .word   .Ldc_c1, REG_T9, .Ldc_ty_check_hi
.Ldc_ty_neg:
        .word   .Ldc_c1, REG_T9, .+4           /* restore T9        */
        .word   .Ldc_cn128, REG_T9, .+4        /* T9 += 128         */
        .word   REG_Z, REG_Z, .Ldc_norm_ty_pos /* re-check          */
.Ldc_ty_check_hi:
        .word   .Ldc_c128, REG_T9, .Ldc_ty_hi_le  /* T9 -= 128; if <= 0 */
        /* T9 was > 128: looped past, but -= 128 should bring it down */
        .word   REG_Z, REG_Z, .Ldc_ty_check_hi
.Ldc_ty_hi_le:
        .word   .Ldc_cn128, REG_T9, .+4        /* restore T9        */

        /* ---- ×4 pre-scale tex_y for inner loop ---- */
        /* T9 = tex_y * 4 via 2 doublings */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T9, REG_Z, .+4
        .word   REG_Z, REG_T9, .+4              /* T9 *= 2           */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T9, REG_Z, .+4
        .word   REG_Z, REG_T9, .+4              /* T9 = tex_y*4      Z: dirty */

        /* ---- Compute dest = ylookup[dc_yl] + columnofs[dc_x]*4 ---- */

        /* ylookup[dc_yl]: compute dc_yl*4 via 2 doublings (no call) */
        /* T1 = dc_yl (from T8) */
        .word   REG_T1, REG_T1, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T8, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4             /* T1 = dc_yl        */
        /* T1 *= 4 via 2 doublings */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4             /* T1 = dc_yl*2      */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4             /* T1 = dc_yl*4      */
        /* T2 = ylookup_addr + dc_yl*4 */
        .word   REG_T2, REG_T2, .+4
        .word   REG_Z, REG_Z, .+4
        .word   .Ldc_g_ylookup, REG_Z, .+4     /* Z = -&ylookup[0]  */
        .word   REG_Z, REG_T2, .+4             /* T2 = &ylookup[0]  */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T2, .+4             /* T2 = &ylookup[dc_yl] */
        /* T2 = m[T2] = ylookup[dc_yl] (a framebuffer byte pointer) */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T2 | INDIRECT, REG_Z, .+4
        .word   REG_T2, REG_T2, .+4
        .word   REG_Z, REG_T2, .+4             /* T2 = ylookup[dc_yl] */

        /* columnofs[dc_x]: load dc_x then compute dc_x*4 via doublings */
        .word   REG_T1, REG_T1, .+4            /* T1 = 0            Z: dirty */
        .word   REG_Z, REG_Z, .+4              /* Z = 0             Z: clean */
        .word   dc_x, REG_Z, .+4               /* Z = -dc_x         Z: dirty */
        .word   REG_Z, REG_T1, .+4             /* T1 = dc_x         Z: dirty */
        /* T1 *= 4 via 2 doublings */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4             /* T1 = dc_x*2       */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4             /* T1 = dc_x*4       */
        /* T3 = &columnofs[0] + dc_x*4 */
        .word   REG_T3, REG_T3, .+4
        .word   REG_Z, REG_Z, .+4
        .word   .Ldc_g_columnofs, REG_Z, .+4   /* Z = -&columnofs[0] */
        .word   REG_Z, REG_T3, .+4             /* T3 = &columnofs[0] */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T3, .+4             /* T3 = &columnofs[dc_x] */
        /* T3 = m[T3] = columnofs[dc_x] */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T3 | INDIRECT, REG_Z, .+4
        .word   REG_T3, REG_T3, .+4
        .word   REG_Z, REG_T3, .+4             /* T3 = columnofs[dc_x] */
        /* columnofs is an int index; C does pointer arith (×4 for uint32_t*) */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T3, REG_Z, .+4
        .word   REG_Z, REG_T3, .+4             /* T3 = columnofs[dc_x]*2 */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T3, REG_Z, .+4
        .word   REG_Z, REG_T3, .+4             /* T3 = columnofs[dc_x]*4 */

        /* T8 = dest = ylookup[dc_yl] + columnofs[dc_x]*4 = T2 + T3 */
        .word   REG_T8, REG_T8, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T2, REG_Z, .+4
        .word   REG_Z, REG_T8, .+4             /* T8 = ylookup[dc_yl] */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T3, REG_Z, .+4
        .word   REG_Z, REG_T8, .+4             /* T8 = dest         Z: dirty */

        /* ---- Restore count into T0, +1 for bottom-check loop ---- */
        .word   REG_T0, REG_T0, .+4
        .word   REG_Z, REG_Z, .+4
        .word   .Ldc_save_count, REG_Z, .+4
        .word   REG_Z, REG_T0, .+4             /* T0 = count        Z: dirty */
        .word   .Ldc_save_count, .Ldc_save_count, .+4
        .word   .Ldc_cn1, REG_T0, .+4          /* T0 = count + 1    Z: dirty */

        /* ---- Pre-negate loop constants for 1-insn adds in loop ---- */
        /* .Ldc_ns = -dc_source: T13 = dc_source currently */
        .word   .Ldc_ns, .Ldc_ns, .+4
        .word   REG_T13, .Ldc_ns, .+4          /* ns = -dc_source   Z: dirty */
        /* .Ldc_nc = -dc_colormap: T14 = dc_colormap */
        .word   .Ldc_nc, .Ldc_nc, .+4
        .word   REG_T14, .Ldc_nc, .+4          /* nc = -dc_colormap Z: dirty */
        /* .Ldc_nsl = -step_lo: T11 = step_lo */
        .word   .Ldc_nsl, .Ldc_nsl, .+4
        .word   REG_T11, .Ldc_nsl, .+4         /* nsl = -step_lo    Z: dirty */
        /* .Ldc_nsi = -(step_int*4): T12 = step_int*4 (already ×4 pre-scaled) */
        .word   .Ldc_nsi, .Ldc_nsi, .+4
        .word   REG_T12, .Ldc_nsi, .+4         /* nsi = -(step_int*4) Z: dirty */

        /* ============================================================
         * INNER LOOP — ×4 pre-scaled tex_y, ~24 insns/pixel common path
         *
         * Registers:
         *   T0  = count+1    T1  = scratch
         *   T8  = dest       T9  = 4*tex_y [0,508]
         *   T10 = frac_lo    T11 = step_lo (read only)
         *   T12 = 4*step_int T13 = dc_source (read only)
         *   T14 = dc_colormap
         * .Ldc_ns  = -dc_source  (loop const for 1-insn add)
         * .Ldc_nc  = -dc_colormap
         * .Ldc_nsl = -step_lo
         * .Ldc_nsi = -(4*step_int)
         *
         * Key optimization: T9 holds 4*tex_y, eliminating the per-pixel
         * tex_y*4 doubling block (saves 4 insns/pixel).
         * Wrap check is out-of-line (saves 1 insn/pixel on common path).
         * ============================================================ */
        .word   REG_Z, REG_Z, .Ldc_loop        /* Z-clear entry jump */
.Ldc_loop:
        /* --- Step 1: T1 = 4*tex_y (direct copy, no doubling needed) --- */
        .word   REG_T1, REG_T1, .+4            /* T1 = 0            Z: clean (from jump) */
        .word   REG_T9, REG_Z, .+4             /* Z = -4*tex_y      Z: dirty */
        .word   REG_Z, REG_T1, .+4             /* T1 = 4*tex_y      Z: dirty */

        /* --- Step 2: T1 = &dc_source[tex_y] (OPT-7: 1-insn add) --- */
        .word   .Ldc_ns, REG_T1, .+4           /* T1 += dc_source   Z: dirty */

        /* --- Step 3: color = m[T1] --- */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1 | INDIRECT, REG_Z, .+4  /* Z = -color        Z: dirty */
        .word   REG_T1, REG_T1, .+4
        .word   REG_Z, REG_T1, .+4             /* T1 = color        Z: dirty */

        /* --- Step 4: T1 = color*4 via 2 doublings ---
         * OPT-1: copy leaves Z = -color = -T1, fuse first doubling */
        /* first doubling: Z = -T1 already */
        .word   REG_Z, REG_T1, .+4             /* T1 = 2*color      Z: dirty */
        /* second doubling */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4             /* T1 = color*4      Z: dirty */

        /* --- Step 5: T1 = &dc_colormap[color] (OPT-7: 1-insn add) --- */
        .word   .Ldc_nc, REG_T1, .+4           /* T1 += dc_colormap Z: dirty */

        /* --- Step 6: pixel = m[T1] --- */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1 | INDIRECT, REG_Z, .+4  /* Z = -pixel        Z: dirty */

        /* --- Step 7: m[dest] = pixel; dest += stride --- */
        .word   REG_T8 | INDIRECT, REG_T8 | INDIRECT, .+4  /* [dest] = 0 */
        .word   REG_Z, REG_T8 | INDIRECT, .+4  /* [dest] = pixel    */
        .word   .Ldc_cn_stride, REG_T8, .+4    /* dest += 1280      */

        /* --- Step 8: frac_lo += step_lo --- */
        .word   .Ldc_nsl, REG_T10, .+4         /* T10 += step_lo    Z: dirty */
        /* if frac_lo > 0: frac_lo -= 0x10000; 4*tex_y += 4 */
        .word   ZERO, REG_T10, .Ldc_no_carry   /* T10 -= 0, branch if <=0   */
        .word   .Ldc_c_0x10000, REG_T10, .+4   /* T10 -= 0x10000    */
        .word   .Ldc_cn4, REG_T9, .+4          /* T9 += 4 (tex_y4++) */
.Ldc_no_carry:

        /* --- Step 9: 4*tex_y += 4*step_int --- */
        .word   .Ldc_nsi, REG_T9, .+4          /* T9 += 4*step_int  Z: dirty */

        /* --- Step 10: wrap 4*tex_y to [0,508] ---
         * Subtract 512. If T9 > 0: wrapped successfully, jump to count.
         * If T9 <= 0: was < 512 (common), out-of-line fixup restores. */
        .word   .Ldc_c512, REG_T9, .Ldc_wrap_fixup /* T9 -= 512; if <=0 → fixup */
        /* T9 > 0: successfully wrapped (T9 was >= 513). Fall through to count. */

.Ldc_wrap_done:
        /* --- Step 11: count--; loop or exit (bottom-check do-while) --- */
        .word   .Ldc_c1, REG_T0, .Ldc_loop_end /* count--; if ≤ 0 → done */
        .word   REG_Z, REG_Z, .Ldc_loop        /* loop (Z: clean)   */

.Ldc_loop_end:
        /* ---- Return: pop RA, jump ---- */
        .word   REG_RA, REG_RA, .+4
        .word   REG_SP | INDIRECT, REG_RA, .+4
        .word   .Ldc_cn4, REG_SP, .+4
        .word   REG_Z, REG_Z, REG_RA | INDIRECT

        /* ---- Out-of-line wrap fixup (rare path) ---- */
.Ldc_wrap_fixup:
        /* T9 <= 0 after subtracting 512.
         * T9 == 0: was exactly 512 → maps to 0. Keep.
         * T9 < 0: was < 512 → restore by adding 512. */
        .word   .Ldc_cn1, REG_T9, .Ldc_wrap_restore /* T9 += 1; if <= 0 → was < 0 */
        /* T9 was 0 (now 1): was 512, should be 0. Undo +1. */
        .word   .Ldc_c1, REG_T9, .+4               /* T9 = 0            */
        .word   REG_Z, REG_Z, .Ldc_wrap_done        /* back to count     */
.Ldc_wrap_restore:
        .word   .Ldc_c1, REG_T9, .+4               /* undo +1           */
        .word   .Ldc_cn512, REG_T9, .+4             /* T9 += 512 (restore) */
        .word   REG_Z, REG_Z, .Ldc_wrap_done        /* back to count     */

/* ---- R_DrawColumn Constants ---- */
.Ldc_c1:    .word 1
.Ldc_cn1:   .word -1
.Ldc_c4:    .word 4
.Ldc_cn4:   .word -4
.Ldc_c128:  .word 128
.Ldc_cn128: .word -128
.Ldc_c512:  .word 512
.Ldc_cn512: .word -512
.Ldc_c_0xFFFF:  .word 0xFFFF
.Ldc_c_0x10000: .word 0x10000
.Ldc_cn_stride: .word -(320*4)     /* -SCREENWIDTH*4 = -1280 */

/* Scratch storage for values across runtime calls */
.Ldc_save_count:    .word 0
.Ldc_save_frac:     .word 0

/* Pre-negated loop constants (filled during setup epilogue) */
.Ldc_ns:    .word 0    /* -dc_source        */
.Ldc_nc:    .word 0    /* -dc_colormap      */
.Ldc_nsl:   .word 0    /* -step_lo          */
.Ldc_nsi:   .word 0    /* -(4*step_int)     */

/* Negated return address constants */
.Ldc_mul1_ret_neg:  .word -.Ldc_mul1_ret
.Ldc_sra1_ret_neg:  .word -.Ldc_sra1_ret
.Ldc_sra2_ret_neg:  .word -.Ldc_sra2_ret

/* Global variable addresses (resolved at link time) */
.Ldc_g_dc_yl:        .word dc_yl
.Ldc_g_dc_yh:        .word dc_yh
.Ldc_g_dc_x:         .word dc_x
.Ldc_g_dc_iscale:    .word dc_iscale
.Ldc_g_dc_texturemid:.word dc_texturemid
.Ldc_g_dc_source:    .word dc_source
.Ldc_g_dc_colormap:  .word dc_colormap
.Ldc_g_centery:      .word centery
.Ldc_g_ylookup:      .word ylookup
.Ldc_g_columnofs:    .word columnofs

.size R_DrawColumn, . - R_DrawColumn

/*===========================================================================
 * R_DrawSpan: Hand-optimized horizontal span renderer (no args — reads globals)
 *
 * Algorithm: Split-accumulator from r_draw.c. The inner loop uses ONLY
 * add/subtract/compare — zero runtime calls per pixel.
 *
 * Setup phase (uses runtime calls for sra_16):
 *   1. Load globals: ds_x1, ds_x2, ds_y, ds_xfrac, ds_yfrac,
 *      ds_xstep, ds_ystep, ds_source, ds_colormap
 *   2. count = ds_x2 - ds_x1
 *   3. dest = ylookup[ds_y] + columnofs[ds_x1]
 *   4. Split xfrac/yfrac/xstep/ystep into integer and fractional parts
 *   5. Normalize integer parts, compute y_pos = y_int*64, ystep_scaled
 *
 * Inner loop register plan (no runtime calls → T0-T14 all safe):
 *   T0  = count                T1  = scratch (address computation)
 *   T2  = x_int [0,63]        T3  = x_lo [-0xFFFF,0]
 *   T4  = y_pos [0,4095]      T5  = y_lo [-0xFFFF,0]
 *   T6  = xstep_lo (const)    T7  = ystep_lo (const)
 *   T8  = dest pointer        T9  = xstep_int (const)
 *   T10 = ystep_scaled (const) T11 = ds_source base (const)
 *   T12 = ds_colormap base (const)
 *   T13, T14 = scratch
 *
 * Per-pixel inner loop body (all subleq, no calls):
 *   spot = y_pos + x_int
 *   pixel = ds_colormap[ds_source[spot]]  (two indirect loads)
 *   m[dest] = pixel                        (indirect store)
 *   dest += 4                              (next pixel in horizontal span)
 *   x_lo += xstep_lo; if > 0: x_lo -= 0x10000; x_int++
 *   x_int += xstep_int; wrap to [0,63]
 *   y_lo += ystep_lo; if > 0: y_lo -= 0x10000; y_pos += 64
 *   y_pos += ystep_scaled; wrap to [0,4095]
 *   count--; if >= 0 loop
 *===========================================================================*/
        .globl  R_DrawSpan
        .type   R_DrawSpan, @function
        .balign 4
R_DrawSpan:

        /* === Z: clean (entry convention) === */

        /* Save RA: SP -= 4; [SP] = -RA (non-leaf function) */
        .word   .Lds_c4, REG_SP, .+4              /* SP -= 4           Z: clean */
        .word   REG_SP | INDIRECT, REG_SP | INDIRECT, .+4  /* [SP] = 0 */
        .word   REG_RA, REG_SP | INDIRECT, .+4    /* [SP] = -RA        */

        /* ------------------------------------------------------------ */
        /* PHASE 1: Load globals, compute count and dest                */
        /* ------------------------------------------------------------ */

        /* ---- Load ds_x1 into T8, ds_x2 into T9 ---- */
        .word   REG_T8, REG_T8, .+4             /* T8 = 0            Z: clean */
        .word   ds_x1, REG_Z, .+4               /* Z = -ds_x1        Z: dirty */
        .word   REG_Z, REG_T8, .+4              /* T8 = ds_x1        Z: dirty */

        .word   REG_T9, REG_T9, .+4             /* T9 = 0            Z: dirty */
        .word   REG_Z, REG_Z, .+4               /* Z = 0             Z: clean */
        .word   ds_x2, REG_Z, .+4               /* Z = -ds_x2        Z: dirty */
        .word   REG_Z, REG_T9, .+4              /* T9 = ds_x2        Z: dirty */

        /* ---- count = ds_x2 - ds_x1 → save to scratch ---- */
        .word   REG_T0, REG_T0, .+4             /* T0 = 0            Z: dirty */
        .word   REG_Z, REG_Z, .+4               /* Z = 0             Z: clean */
        .word   REG_T9, REG_Z, .+4              /* Z = -ds_x2        Z: dirty */
        .word   REG_Z, REG_T0, .+4              /* T0 = ds_x2        Z: dirty */
        .word   REG_T8, REG_T0, .+4             /* T0 = ds_x2-ds_x1 = count */
        /* if count < 0: return immediately */
        .word   ZERO, REG_T0, .Lds_maybe_neg    /* T0 -= 0; if <= 0  Z: clean */
        .word   REG_Z, REG_Z, .Lds_count_ok     /* T0 > 0: continue  Z: clean */

.Lds_maybe_neg:
        .word   .Lds_cn1, REG_T0, .Lds_early_ret /* T0 += 1; if <= 0 → was < 0 */
        /* T0 was 0 (now 1): restore T0 = 0 */
        .word   .Lds_c1, REG_T0, .+4            /* T0 -= 1 = 0       */
        .word   REG_Z, REG_Z, .Lds_count_ok

.Lds_early_ret:
        /* count < 0: pop RA and jump */
        .word   REG_RA, REG_RA, .+4
        .word   REG_SP | INDIRECT, REG_RA, .+4
        .word   .Lds_cn4, REG_SP, .+4
        .word   REG_Z, REG_Z, REG_RA | INDIRECT

.Lds_count_ok:
        /* Save count to scratch — Z: clean (all paths clear Z) */
        .word   REG_T0, REG_Z, .+4              /* Z = -count        Z: dirty */
        .word   REG_Z, .Lds_save_count, .+4     /* save = count      Z: dirty */

        /* ---- Compute dest = ylookup[ds_y] + columnofs[ds_x1]*4 ---- */

        /* Load ds_y into T1 */
        .word   REG_T1, REG_T1, .+4
        .word   REG_Z, REG_Z, .+4
        .word   ds_y, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4              /* T1 = ds_y         Z: dirty */
        /* T1 *= 4 via 2 doublings */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4              /* T1 = ds_y*2       */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4              /* T1 = ds_y*4       */
        /* T2 = &ylookup + ds_y*4 */
        .word   REG_T2, REG_T2, .+4
        .word   REG_Z, REG_Z, .+4
        .word   .Lds_g_ylookup, REG_Z, .+4
        .word   REG_Z, REG_T2, .+4              /* T2 = &ylookup[0]  */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T2, .+4              /* T2 = &ylookup[ds_y] */
        /* T2 = m[T2] = ylookup[ds_y] */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T2 | INDIRECT, REG_Z, .+4
        .word   REG_T2, REG_T2, .+4
        .word   REG_Z, REG_T2, .+4              /* T2 = ylookup[ds_y] */

        /* columnofs[ds_x1]: T8 = ds_x1 from above. T1 = ds_x1*4 */
        .word   REG_T1, REG_T1, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T8, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4              /* T1 = ds_x1        */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4              /* T1 = ds_x1*2      */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4              /* T1 = ds_x1*4      */
        /* T3 = &columnofs + ds_x1*4 */
        .word   REG_T3, REG_T3, .+4
        .word   REG_Z, REG_Z, .+4
        .word   .Lds_g_columnofs, REG_Z, .+4
        .word   REG_Z, REG_T3, .+4              /* T3 = &columnofs[0] */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T3, .+4              /* T3 = &columnofs[ds_x1] */
        /* T3 = m[T3] = columnofs[ds_x1] */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T3 | INDIRECT, REG_Z, .+4
        .word   REG_T3, REG_T3, .+4
        .word   REG_Z, REG_T3, .+4              /* T3 = columnofs[ds_x1] */
        /* columnofs is int; pointer arith scales by sizeof(uint32_t)=4 */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T3, REG_Z, .+4
        .word   REG_Z, REG_T3, .+4              /* T3 *= 2           */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T3, REG_Z, .+4
        .word   REG_Z, REG_T3, .+4              /* T3 *= 4           */

        /* dest = T2 + T3 → save to scratch */
        .word   REG_T1, REG_T1, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T2, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4              /* T1 = ylookup[ds_y] */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T3, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4              /* T1 = dest         Z: dirty */
        /* Save dest to scratch */
        .word   .Lds_save_dest, .Lds_save_dest, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, .Lds_save_dest, .+4      /* save_dest = dest  Z: dirty */

        /* ------------------------------------------------------------ */
        /* PHASE 2: Load frac/step globals into T8-T13 (survive calls)  */
        /* ------------------------------------------------------------ */

        /* T8 = ds_xfrac */
        .word   REG_T8, REG_T8, .+4
        .word   REG_Z, REG_Z, .+4
        .word   ds_xfrac, REG_Z, .+4
        .word   REG_Z, REG_T8, .+4              /* T8 = ds_xfrac     Z: dirty */

        /* T9 = ds_xstep */
        .word   REG_T9, REG_T9, .+4
        .word   REG_Z, REG_Z, .+4
        .word   ds_xstep, REG_Z, .+4
        .word   REG_Z, REG_T9, .+4              /* T9 = ds_xstep     Z: dirty */

        /* T10 = ds_yfrac */
        .word   REG_T10, REG_T10, .+4
        .word   REG_Z, REG_Z, .+4
        .word   ds_yfrac, REG_Z, .+4
        .word   REG_Z, REG_T10, .+4             /* T10 = ds_yfrac    Z: dirty */

        /* T11 = ds_ystep */
        .word   REG_T11, REG_T11, .+4
        .word   REG_Z, REG_Z, .+4
        .word   ds_ystep, REG_Z, .+4
        .word   REG_Z, REG_T11, .+4             /* T11 = ds_ystep    Z: dirty */

        /* T12 = ds_source */
        .word   REG_T12, REG_T12, .+4
        .word   REG_Z, REG_Z, .+4
        .word   ds_source, REG_Z, .+4
        .word   REG_Z, REG_T12, .+4             /* T12 = ds_source   Z: dirty */

        /* T13 = ds_colormap */
        .word   REG_T13, REG_T13, .+4
        .word   REG_Z, REG_Z, .+4
        .word   ds_colormap, REG_Z, .+4
        .word   REG_Z, REG_T13, .+4             /* T13 = ds_colormap Z: dirty */

        /* ------------------------------------------------------------ */
        /* PHASE 3: Split ds_xfrac → x_int, x_lo (sra_16 call)         */
        /* ------------------------------------------------------------ */

        /* R21 = ds_xfrac (T8) */
        .word   REG_R21, REG_R21, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T8, REG_Z, .+4
        .word   REG_Z, REG_R21, .+4             /* R21 = ds_xfrac    */
        /* Call sra_16 */
        .word   REG_RA, REG_RA, .+4                   /* RA = 0 */
        .word   .Lds_sra1_ret_neg, REG_RA, .+4         /* RA = ret */
        .word   REG_Z, REG_Z, __subleq_sra_16
.Lds_sra1_ret:
        /* R20 = x_int = ds_xfrac >> 16. Z: clean */

        /* Save x_int to T14 */
        .word   REG_T14, REG_T14, .+4
        .word   REG_R20, REG_Z, .+4
        .word   REG_Z, REG_T14, .+4             /* T14 = x_int       Z: dirty */

        /* Compute x_lo = ds_xfrac - (x_int << 16) - 0xFFFF */
        /* First: x_int << 16 in T1 via 16 doublings */
        .word   REG_T1, REG_T1, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T14, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4              /* T1 = x_int        */
.irp i,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4
.endr
        /* T8 = ds_xfrac - (x_int << 16) - 0xFFFF = x_lo */
        .word   REG_T1, REG_T8, .+4             /* T8 -= (x_int<<16) */
        .word   .Lds_c_0xFFFF, REG_T8, .+4      /* T8 -= 0xFFFF      */
        /* T8 = x_lo now */

        /* Save x_int (T14) to scratch so we can reuse T14 */
        .word   .Lds_save_x_int, .Lds_save_x_int, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T14, REG_Z, .+4
        .word   REG_Z, .Lds_save_x_int, .+4     /* save = x_int      */
        /* Save x_lo (T8) to scratch so T8 is free for next split */
        .word   .Lds_save_x_lo, .Lds_save_x_lo, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T8, REG_Z, .+4
        .word   REG_Z, .Lds_save_x_lo, .+4      /* save = x_lo       */

        /* ------------------------------------------------------------ */
        /* PHASE 4: Split ds_xstep → xstep_int, xstep_lo (sra_16 call) */
        /* ------------------------------------------------------------ */

        .word   REG_R21, REG_R21, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T9, REG_Z, .+4
        .word   REG_Z, REG_R21, .+4             /* R21 = ds_xstep    */
        .word   REG_RA, REG_RA, .+4                   /* RA = 0 */
        .word   .Lds_sra2_ret_neg, REG_RA, .+4         /* RA = ret */
        .word   REG_Z, REG_Z, __subleq_sra_16
.Lds_sra2_ret:
        /* R20 = xstep_int. Z: clean */
        .word   REG_T14, REG_T14, .+4
        .word   REG_R20, REG_Z, .+4
        .word   REG_Z, REG_T14, .+4             /* T14 = xstep_int   */

        /* xstep_lo = ds_xstep - (xstep_int << 16) */
        .word   REG_T1, REG_T1, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T14, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4              /* T1 = xstep_int    */
.irp i,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4
.endr
        .word   REG_T1, REG_T9, .+4             /* T9 -= (xstep_int<<16) = xstep_lo */

        /* Save xstep_int (T14) and xstep_lo (T9) to scratch */
        .word   .Lds_save_xsi, .Lds_save_xsi, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T14, REG_Z, .+4
        .word   REG_Z, .Lds_save_xsi, .+4
        .word   .Lds_save_xsl, .Lds_save_xsl, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T9, REG_Z, .+4
        .word   REG_Z, .Lds_save_xsl, .+4

        /* ------------------------------------------------------------ */
        /* PHASE 5: Split ds_yfrac → y_int, y_lo (sra_16 call)         */
        /* ------------------------------------------------------------ */

        .word   REG_R21, REG_R21, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T10, REG_Z, .+4
        .word   REG_Z, REG_R21, .+4             /* R21 = ds_yfrac    */
        .word   REG_RA, REG_RA, .+4                   /* RA = 0 */
        .word   .Lds_sra3_ret_neg, REG_RA, .+4         /* RA = ret */
        .word   REG_Z, REG_Z, __subleq_sra_16
.Lds_sra3_ret:
        /* R20 = y_int. Z: clean */
        .word   REG_T14, REG_T14, .+4
        .word   REG_R20, REG_Z, .+4
        .word   REG_Z, REG_T14, .+4             /* T14 = y_int       */

        /* y_lo = ds_yfrac - (y_int << 16) - 0xFFFF */
        .word   REG_T1, REG_T1, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T14, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4              /* T1 = y_int        */
.irp i,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4
.endr
        .word   REG_T1, REG_T10, .+4            /* T10 -= (y_int<<16) */
        .word   .Lds_c_0xFFFF, REG_T10, .+4     /* T10 -= 0xFFFF = y_lo */

        /* Save y_int (T14) and y_lo (T10) */
        .word   .Lds_save_y_int, .Lds_save_y_int, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T14, REG_Z, .+4
        .word   REG_Z, .Lds_save_y_int, .+4
        .word   .Lds_save_y_lo, .Lds_save_y_lo, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T10, REG_Z, .+4
        .word   REG_Z, .Lds_save_y_lo, .+4

        /* ------------------------------------------------------------ */
        /* PHASE 6: Split ds_ystep → ystep_int, ystep_lo (sra_16 call) */
        /* ------------------------------------------------------------ */

        .word   REG_R21, REG_R21, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T11, REG_Z, .+4
        .word   REG_Z, REG_R21, .+4             /* R21 = ds_ystep    */
        .word   REG_RA, REG_RA, .+4                   /* RA = 0 */
        .word   .Lds_sra4_ret_neg, REG_RA, .+4         /* RA = ret */
        .word   REG_Z, REG_Z, __subleq_sra_16
.Lds_sra4_ret:
        /* R20 = ystep_int. Z: clean */
        .word   REG_T14, REG_T14, .+4
        .word   REG_R20, REG_Z, .+4
        .word   REG_Z, REG_T14, .+4             /* T14 = ystep_int   */

        /* ystep_lo = ds_ystep - (ystep_int << 16) */
        .word   REG_T1, REG_T1, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T14, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4              /* T1 = ystep_int    */
.irp i,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1, REG_Z, .+4
        .word   REG_Z, REG_T1, .+4
.endr
        .word   REG_T1, REG_T11, .+4            /* T11 -= (ystep_int<<16) = ystep_lo */

        /* Save ystep_int (T14) and ystep_lo (T11) */
        .word   .Lds_save_ysi, .Lds_save_ysi, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T14, REG_Z, .+4
        .word   REG_Z, .Lds_save_ysi, .+4
        .word   .Lds_save_ysl, .Lds_save_ysl, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T11, REG_Z, .+4
        .word   REG_Z, .Lds_save_ysl, .+4

        /* ------------------------------------------------------------ */
        /* PHASE 7: Normalize and assign final registers                */
        /* No more runtime calls — T0-T7 are now safe permanently.      */
        /* ------------------------------------------------------------ */

        /* ---- Load x_int into T2 and normalize to [0,63] ---- */
        .word   REG_T2, REG_T2, .+4
        .word   REG_Z, REG_Z, .+4
        .word   .Lds_save_x_int, REG_Z, .+4
        .word   REG_Z, REG_T2, .+4              /* T2 = x_int        */
        .word   .Lds_save_x_int, .Lds_save_x_int, .+4  /* reset scratch */
        /* while x_int < 0: x_int += 64 */
.Lds_norm_xi_neg:
        .word   ZERO, REG_T2, .Lds_xi_le0       /* if T2 <= 0        */
        .word   REG_Z, REG_Z, .Lds_norm_xi_pos  /* T2 > 0            */
.Lds_xi_le0:
        .word   .Lds_cn1, REG_T2, .Lds_xi_neg   /* T2 += 1; if <= 0 → negative */
        .word   .Lds_c1, REG_T2, .Lds_norm_xi_pos /* was 0, restore  */
.Lds_xi_neg:
        .word   .Lds_c1, REG_T2, .+4            /* restore           */
        .word   .Lds_cn64, REG_T2, .+4          /* T2 += 64          */
        .word   REG_Z, REG_Z, .Lds_norm_xi_neg
        /* while x_int >= 64: x_int -= 64 */
.Lds_norm_xi_pos:
        .word   .Lds_c64, REG_T2, .Lds_xi_hi_le /* T2 -= 64; if <= 0 */
        .word   REG_Z, REG_Z, .Lds_norm_xi_pos  /* still > 0, loop   */
.Lds_xi_hi_le:
        /* T2 <= 0: was <= 64. Restore unless exactly 64 (T2 == 0). */
        .word   .Lds_cn1, REG_T2, .Lds_xi_restore /* T2 += 1; if <= 0 → was < 0 → restore */
        .word   .Lds_c1, REG_T2, .Lds_xi_done     /* was 0 (now 1): undo +1, keep at 0 */
.Lds_xi_restore:
        .word   .Lds_c1, REG_T2, .+4            /* undo +1           */
        .word   .Lds_cn64, REG_T2, .+4          /* T2 += 64 restore  */
.Lds_xi_done:

        /* ---- ×4 pre-scale x_int for inner loop ---- */
        /* T2 = x_int * 4 via 2 doublings */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T2, REG_Z, .+4
        .word   REG_Z, REG_T2, .+4              /* T2 *= 2           */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T2, REG_Z, .+4
        .word   REG_Z, REG_T2, .+4              /* T2 = x_int*4      Z: dirty */

        /* ---- Load y_int into T4 and normalize to [0,63] ---- */
        .word   REG_T4, REG_T4, .+4
        .word   REG_Z, REG_Z, .+4
        .word   .Lds_save_y_int, REG_Z, .+4
        .word   REG_Z, REG_T4, .+4              /* T4 = y_int        */
        .word   .Lds_save_y_int, .Lds_save_y_int, .+4
        /* while y_int < 0: y_int += 64 */
.Lds_norm_yi_neg:
        .word   ZERO, REG_T4, .Lds_yi_le0
        .word   REG_Z, REG_Z, .Lds_norm_yi_pos
.Lds_yi_le0:
        .word   .Lds_cn1, REG_T4, .Lds_yi_neg
        .word   .Lds_c1, REG_T4, .Lds_norm_yi_pos
.Lds_yi_neg:
        .word   .Lds_c1, REG_T4, .+4
        .word   .Lds_cn64, REG_T4, .+4
        .word   REG_Z, REG_Z, .Lds_norm_yi_neg
        /* while y_int >= 64: y_int -= 64 */
.Lds_norm_yi_pos:
        .word   .Lds_c64, REG_T4, .Lds_yi_hi_le
        .word   REG_Z, REG_Z, .Lds_norm_yi_pos
.Lds_yi_hi_le:
        .word   .Lds_cn1, REG_T4, .Lds_yi_restore
        .word   .Lds_c1, REG_T4, .Lds_yi_norm_done
.Lds_yi_restore:
        .word   .Lds_c1, REG_T4, .+4
        .word   .Lds_cn64, REG_T4, .+4
.Lds_yi_norm_done:

        /* ---- Compute y_pos = y_int * 64 in T4 via 6 doublings ---- */
.irp i,0,1,2,3,4,5
        .word   REG_Z, REG_Z, .+4
        .word   REG_T4, REG_Z, .+4
        .word   REG_Z, REG_T4, .+4
.endr
        /* T4 = y_pos = y_int * 64 */

        /* ---- ×4 pre-scale y_pos for inner loop ---- */
        /* T4 = y_pos * 4 via 2 doublings */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T4, REG_Z, .+4
        .word   REG_Z, REG_T4, .+4              /* T4 *= 2           */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T4, REG_Z, .+4
        .word   REG_Z, REG_T4, .+4              /* T4 = y_pos*4 = y_int*256  Z: dirty */

        /* ---- Load xstep_int into T9 and normalize to [-63,63] ---- */
        .word   REG_T9, REG_T9, .+4
        .word   REG_Z, REG_Z, .+4
        .word   .Lds_save_xsi, REG_Z, .+4
        .word   REG_Z, REG_T9, .+4              /* T9 = xstep_int    */
        .word   .Lds_save_xsi, .Lds_save_xsi, .+4
        /* while xstep_int >= 64: xstep_int -= 64 */
.Lds_norm_xsi_pos:
        .word   .Lds_c64, REG_T9, .Lds_xsi_hi_le
        .word   REG_Z, REG_Z, .Lds_norm_xsi_pos
.Lds_xsi_hi_le:
        .word   .Lds_cn1, REG_T9, .Lds_xsi_restore1
        .word   .Lds_c1, REG_T9, .Lds_norm_xsi_neg
.Lds_xsi_restore1:
        .word   .Lds_c1, REG_T9, .+4
        .word   .Lds_cn64, REG_T9, .+4
        /* while xstep_int < -64: xstep_int += 64 */
.Lds_norm_xsi_neg:
        /* Check if T9 < -64: add 65, check if <= 0 → T9 <= -65 → T9 < -64 */
        /* Simpler: add 64, check if still < 0 */
        .word   .Lds_cn64, REG_T9, .+4          /* T9 += 64          */
        .word   ZERO, REG_T9, .Lds_xsi_still_neg /* if <= 0           */
        /* T9 > 0 after +64: was > -64, restore and done */
        .word   .Lds_c64, REG_T9, .Lds_xsi_done /* T9 -= 64 restore  */
.Lds_xsi_still_neg:
        /* T9 <= 0 after +64: could be == 0 (was -64, acceptable) or < 0 */
        .word   .Lds_cn1, REG_T9, .Lds_xsi_very_neg /* +1; if <= 0 → was < 0 → still < -64 */
        /* was 0 (now 1): was exactly -64 — undo the loop's +64 to restore -64 */
        .word   .Lds_c1, REG_T9, .+4               /* T9 -= 1 = 0           */
        .word   .Lds_c64, REG_T9, .Lds_xsi_done    /* T9 -= 64 → -64; done  */
.Lds_xsi_very_neg:
        .word   .Lds_c1, REG_T9, .+4            /* undo +1           */
        /* T9 is still < -64, loop (already added 64 once) */
        .word   REG_Z, REG_Z, .Lds_norm_xsi_neg
.Lds_xsi_done:

        /* ---- ×4 pre-scale xstep_int for inner loop ---- */
        /* T9 = xstep_int * 4 via 2 doublings */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T9, REG_Z, .+4
        .word   REG_Z, REG_T9, .+4              /* T9 *= 2           */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T9, REG_Z, .+4
        .word   REG_Z, REG_T9, .+4              /* T9 = xstep_int*4  Z: dirty */

        /* ---- Load ystep_int into T14 and normalize to [-63,63] ---- */
        .word   REG_T14, REG_T14, .+4
        .word   REG_Z, REG_Z, .+4
        .word   .Lds_save_ysi, REG_Z, .+4
        .word   REG_Z, REG_T14, .+4             /* T14 = ystep_int   */
        .word   .Lds_save_ysi, .Lds_save_ysi, .+4
        /* while ystep_int >= 64: ystep_int -= 64 */
.Lds_norm_ysi_pos:
        .word   .Lds_c64, REG_T14, .Lds_ysi_hi_le
        .word   REG_Z, REG_Z, .Lds_norm_ysi_pos
.Lds_ysi_hi_le:
        .word   .Lds_cn1, REG_T14, .Lds_ysi_restore1
        .word   .Lds_c1, REG_T14, .Lds_norm_ysi_neg
.Lds_ysi_restore1:
        .word   .Lds_c1, REG_T14, .+4
        .word   .Lds_cn64, REG_T14, .+4
        /* while ystep_int < -64: ystep_int += 64 */
.Lds_norm_ysi_neg:
        .word   .Lds_cn64, REG_T14, .+4
        .word   ZERO, REG_T14, .Lds_ysi_still_neg
        .word   .Lds_c64, REG_T14, .Lds_ysi_done
.Lds_ysi_still_neg:
        /* T14 <= 0 after +64: could be == 0 (was -64, acceptable) or < 0 */
        .word   .Lds_cn1, REG_T14, .Lds_ysi_very_neg /* +1; if <= 0 → was < 0 → still < -64 */
        /* was 0 (now 1): was exactly -64 — undo the loop's +64 to restore -64 */
        .word   .Lds_c1, REG_T14, .+4               /* T14 -= 1 = 0          */
        .word   .Lds_c64, REG_T14, .Lds_ysi_done    /* T14 -= 64 → -64; done */
.Lds_ysi_very_neg:
        .word   .Lds_c1, REG_T14, .+4
        .word   REG_Z, REG_Z, .Lds_norm_ysi_neg
.Lds_ysi_done:

        /* ---- Compute ystep_scaled = ystep_int * 64 in T10 ---- */
        .word   REG_T10, REG_T10, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T14, REG_Z, .+4
        .word   REG_Z, REG_T10, .+4             /* T10 = ystep_int   */
.irp i,0,1,2,3,4,5
        .word   REG_Z, REG_Z, .+4
        .word   REG_T10, REG_Z, .+4
        .word   REG_Z, REG_T10, .+4
.endr
        /* T10 = ystep_scaled = ystep_int * 64 */

        /* ---- ×4 pre-scale ystep_scaled for inner loop ---- */
        /* T10 = ystep_scaled * 4 via 2 doublings */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T10, REG_Z, .+4
        .word   REG_Z, REG_T10, .+4             /* T10 *= 2          */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T10, REG_Z, .+4
        .word   REG_Z, REG_T10, .+4             /* T10 = ystep_int*256  Z: dirty */

        /* ---- Load remaining values from scratch into final regs ---- */

        /* T0 = count, +1 for bottom-check loop */
        .word   REG_T0, REG_T0, .+4
        .word   REG_Z, REG_Z, .+4
        .word   .Lds_save_count, REG_Z, .+4
        .word   REG_Z, REG_T0, .+4
        .word   .Lds_save_count, .Lds_save_count, .+4
        .word   .Lds_cn1, REG_T0, .+4          /* T0 = count + 1    */

        /* T3 = x_lo */
        .word   REG_T3, REG_T3, .+4
        .word   REG_Z, REG_Z, .+4
        .word   .Lds_save_x_lo, REG_Z, .+4
        .word   REG_Z, REG_T3, .+4
        .word   .Lds_save_x_lo, .Lds_save_x_lo, .+4

        /* T5 = y_lo */
        .word   REG_T5, REG_T5, .+4
        .word   REG_Z, REG_Z, .+4
        .word   .Lds_save_y_lo, REG_Z, .+4
        .word   REG_Z, REG_T5, .+4
        .word   .Lds_save_y_lo, .Lds_save_y_lo, .+4

        /* T6 = xstep_lo */
        .word   REG_T6, REG_T6, .+4
        .word   REG_Z, REG_Z, .+4
        .word   .Lds_save_xsl, REG_Z, .+4
        .word   REG_Z, REG_T6, .+4
        .word   .Lds_save_xsl, .Lds_save_xsl, .+4

        /* T7 = ystep_lo */
        .word   REG_T7, REG_T7, .+4
        .word   REG_Z, REG_Z, .+4
        .word   .Lds_save_ysl, REG_Z, .+4
        .word   REG_Z, REG_T7, .+4
        .word   .Lds_save_ysl, .Lds_save_ysl, .+4

        /* T8 = dest */
        .word   REG_T8, REG_T8, .+4
        .word   REG_Z, REG_Z, .+4
        .word   .Lds_save_dest, REG_Z, .+4
        .word   REG_Z, REG_T8, .+4
        .word   .Lds_save_dest, .Lds_save_dest, .+4

        /* T11 = ds_source (still in T12 from phase 2) */
        .word   REG_T11, REG_T11, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T12, REG_Z, .+4
        .word   REG_Z, REG_T11, .+4             /* T11 = ds_source   */

        /* T12 = ds_colormap (was T13). Read T13 before overwriting T12. */
        .word   REG_T12, REG_T12, .+4
        .word   REG_Z, REG_Z, .+4
        .word   REG_T13, REG_Z, .+4
        .word   REG_Z, REG_T12, .+4             /* T12 = ds_colormap */

        /* ---- Pre-negate 6 loop constants for 1-insn adds in inner loop ---- */
        /* .Lds_ns = -ds_source (T11) */
        .word   .Lds_ns, .Lds_ns, .+4
        .word   REG_T11, .Lds_ns, .+4           /* ns = -ds_source   */
        /* .Lds_nc = -ds_colormap (T12) */
        .word   .Lds_nc, .Lds_nc, .+4
        .word   REG_T12, .Lds_nc, .+4           /* nc = -ds_colormap */
        /* .Lds_nxsl = -xstep_lo (T6) */
        .word   .Lds_nxsl, .Lds_nxsl, .+4
        .word   REG_T6, .Lds_nxsl, .+4          /* nxsl = -xstep_lo  */
        /* .Lds_nysl = -ystep_lo (T7) */
        .word   .Lds_nysl, .Lds_nysl, .+4
        .word   REG_T7, .Lds_nysl, .+4          /* nysl = -ystep_lo  */
        /* .Lds_nxsi = -(4*xstep_int) (T9 already ×4 pre-scaled) */
        .word   .Lds_nxsi, .Lds_nxsi, .+4
        .word   REG_T9, .Lds_nxsi, .+4          /* nxsi = -(4*xstep_int) */
        /* .Lds_nys = -(4*ystep_scaled) (T10 already ×4 pre-scaled) */
        .word   .Lds_nys, .Lds_nys, .+4
        .word   REG_T10, .Lds_nys, .+4          /* nys = -(4*ystep_scaled) */

        /* ============================================================
         * INNER LOOP — ×4 pre-scaled, ~33 insns/pixel common path
         *
         * Registers:
         *   T0  = count+1           T1  = scratch (address)
         *   T2  = 4*x_int [0,252]   T3  = x_lo
         *   T4  = 4*y_pos [0,16128] T5  = y_lo
         *   T6  = xstep_lo      T7  = ystep_lo      (kept for carry logic)
         *   T8  = dest          T9  = 4*xstep_int
         *   T10 = 4*ystep_scaled  T11 = ds_source
         *   T12 = ds_colormap   T13, T14 = scratch
         * .Lds_ns   = -ds_source       .Lds_nc   = -ds_colormap
         * .Lds_nxsl = -xstep_lo        .Lds_nysl = -ystep_lo
         * .Lds_nxsi = -(4*xstep_int)   .Lds_nys  = -(4*ystep_scaled)
         *
         * Key optimization: T2 holds 4*x_int and T4 holds 4*y_pos,
         * so T1 = T4 + T2 directly gives 4*spot without doubling.
         * Wrap checks are out-of-line (saves insns on common path).
         * ============================================================ */
        .word   REG_Z, REG_Z, .Lds_loop        /* Z-clear entry jump */
.Lds_loop:
        /* --- Step 1: T1 = 4*y_pos + 4*x_int = 4*spot (direct) ---
         * Z is clean from loop-back jump. */
        .word   REG_T1, REG_T1, .+4             /* T1 = 0            Z: clean */
        .word   REG_T4, REG_Z, .+4              /* Z = -4*y_pos      Z: dirty */
        .word   REG_T2, REG_Z, .+4              /* Z = -(4*y_pos+4*x_int) */
        .word   REG_Z, REG_T1, .+4              /* T1 = 4*spot       Z: dirty */

        /* --- Step 2: T1 = &ds_source[spot] (1-insn add) --- */
        .word   .Lds_ns, REG_T1, .+4            /* T1 += ds_source   */

        /* --- Step 3: T13 = color index = m[T1] --- */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T1 | INDIRECT, REG_Z, .+4   /* Z = -color        */
        .word   REG_T13, REG_T13, .+4
        .word   REG_Z, REG_T13, .+4             /* T13 = color; Z = -color = -T13 */

        /* --- Step 4: T13 *= 4 (fuse — Z = -T13 after copy) --- */
        /* first doubling: Z = -T13 already */
        .word   REG_Z, REG_T13, .+4             /* T13 *= 2          */
        /* second doubling */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T13, REG_Z, .+4
        .word   REG_Z, REG_T13, .+4             /* T13 *= 4          */

        /* --- Step 5: T13 = &ds_colormap[color] (1-insn add) --- */
        .word   .Lds_nc, REG_T13, .+4           /* T13 += ds_colormap */

        /* --- Step 6: pixel = m[T13] --- */
        .word   REG_Z, REG_Z, .+4
        .word   REG_T13 | INDIRECT, REG_Z, .+4  /* Z = -pixel        */

        /* --- Step 7: m[dest] = pixel; dest += 4 --- */
        .word   REG_T8 | INDIRECT, REG_T8 | INDIRECT, .+4
        .word   REG_Z, REG_T8 | INDIRECT, .+4   /* [dest] = pixel    */
        .word   .Lds_cn4, REG_T8, .+4           /* dest += 4         */

        /* --- Step 8: x_lo += xstep_lo --- */
        .word   .Lds_nxsl, REG_T3, .+4          /* T3 += xstep_lo    */
        .word   ZERO, REG_T3, .Lds_no_xcarry    /* if T3 <= 0, skip  */
        .word   .Lds_c_0x10000, REG_T3, .+4     /* T3 -= 0x10000     */
        .word   .Lds_cn4, REG_T2, .+4           /* x_int4 += 4       */
.Lds_no_xcarry:

        /* --- Step 9: 4*x_int += 4*xstep_int --- */
        .word   .Lds_nxsi, REG_T2, .+4          /* T2 += 4*xstep_int */

        /* --- Step 10: wrap 4*x_int to [0,252] ---
         * Subtract 256. If T2 > 0: wrapped, fall through to neg check.
         * If T2 <= 0: common (was < 256), out-of-line fixup restores. */
        .word   .Lds_c256, REG_T2, .Lds_xw_fixup  /* T2 -= 256; if <=0 → fixup */
        /* T2 > 0: successfully wrapped. Check negative: */
.Lds_xw_check_neg:
        /* if 4*x_int < 0: 4*x_int += 256 */
        .word   .Lds_cn1, REG_T2, .Lds_xw_is_neg  /* T2+=1; if <=0 → was <0 */
        .word   .Lds_c1, REG_T2, .+4               /* T2 -= 1 (undo)   */
.Lds_xw_done:

        /* --- Step 11: y_lo += ystep_lo --- */
        .word   .Lds_nysl, REG_T5, .+4          /* T5 += ystep_lo    */
        .word   ZERO, REG_T5, .Lds_no_ycarry    /* if T5 <= 0, skip  */
        .word   .Lds_c_0x10000, REG_T5, .+4     /* T5 -= 0x10000     */
        .word   .Lds_cn256, REG_T4, .+4         /* y_pos4 += 256 (=64*4) */
.Lds_no_ycarry:

        /* --- Step 12: 4*y_pos += 4*ystep_scaled --- */
        .word   .Lds_nys, REG_T4, .+4           /* T4 += 4*ystep_scaled */

        /* --- Step 13: wrap 4*y_pos to [0,16128] ---
         * Subtract 16384. If T4 > 0: wrapped, fall through to neg check.
         * If T4 <= 0: common (was < 16384), out-of-line fixup restores. */
        .word   .Lds_c16384, REG_T4, .Lds_yw_fixup  /* T4 -= 16384; if <=0 → fixup */
        /* T4 > 0: successfully wrapped. Check negative: */
.Lds_yw_check_neg:
        /* if 4*y_pos < 0: 4*y_pos += 16384 */
        .word   .Lds_cn1, REG_T4, .Lds_yw_is_neg
        .word   .Lds_c1, REG_T4, .+4
.Lds_yw_done:

        /* --- Step 14: count--; loop or exit (bottom-check do-while) --- */
        .word   .Lds_c1, REG_T0, .Lds_loop_end /* count--; if ≤ 0 → done */
        .word   REG_Z, REG_Z, .Lds_loop        /* loop (Z: clean)   */

.Lds_loop_end:
        /* ---- Return: pop RA, jump ---- */
        .word   REG_RA, REG_RA, .+4
        .word   REG_SP | INDIRECT, REG_RA, .+4
        .word   .Lds_cn4, REG_SP, .+4
        .word   REG_Z, REG_Z, REG_RA | INDIRECT

        /* ---- Out-of-line wrap fixups (rare paths) ---- */

        /* X-wrap fixup: T2 <= 0 after subtracting 256 */
.Lds_xw_fixup:
        /* T2 == 0: was exactly 256 → maps to 0. Keep.
         * T2 < 0: was < 256 → restore by adding 256. */
        .word   .Lds_cn1, REG_T2, .Lds_xw_restore /* T2 += 1; if <= 0 → was < 0 */
        /* T2 was 0 (now 1): was 256, should be 0. Undo +1. */
        .word   .Lds_c1, REG_T2, .Lds_xw_check_neg  /* T2 = 0; go check neg */
.Lds_xw_restore:
        .word   .Lds_c1, REG_T2, .+4               /* undo +1           */
        .word   .Lds_cn256, REG_T2, .+4             /* T2 += 256 (restore) */
        .word   REG_Z, REG_Z, .Lds_xw_check_neg     /* back to neg check */

        /* X negative fixup */
.Lds_xw_is_neg:
        /* T2 was < 0. Undo +1 then add 256. */
        .word   .Lds_c1, REG_T2, .+4               /* T2 -= 1 (undo)    */
        .word   .Lds_cn256, REG_T2, .+4             /* T2 += 256         */
        .word   REG_Z, REG_Z, .Lds_xw_done          /* back to main loop */

        /* Y-wrap fixup: T4 <= 0 after subtracting 16384 */
.Lds_yw_fixup:
        .word   .Lds_cn1, REG_T4, .Lds_yw_restore
        .word   .Lds_c1, REG_T4, .Lds_yw_check_neg
.Lds_yw_restore:
        .word   .Lds_c1, REG_T4, .+4
        .word   .Lds_cn16384, REG_T4, .+4           /* T4 += 16384 (restore) */
        .word   REG_Z, REG_Z, .Lds_yw_check_neg

        /* Y negative fixup */
.Lds_yw_is_neg:
        .word   .Lds_c1, REG_T4, .+4
        .word   .Lds_cn16384, REG_T4, .+4           /* T4 += 16384       */
        .word   REG_Z, REG_Z, .Lds_yw_done

/* ---- R_DrawSpan Constants ---- */
.Lds_c1:        .word 1
.Lds_cn1:       .word -1
.Lds_c4:        .word 4
.Lds_cn4:       .word -4
.Lds_c64:       .word 64
.Lds_cn64:      .word -64
.Lds_c256:      .word 256
.Lds_cn256:     .word -256
.Lds_c4096:     .word 4096
.Lds_cn4096:    .word -4096
.Lds_c16384:    .word 16384
.Lds_cn16384:   .word -16384
.Lds_c_0xFFFF:  .word 0xFFFF
.Lds_c_0x10000: .word 0x10000

/* Scratch storage for values across runtime calls */
.Lds_save_count:    .word 0
.Lds_save_dest:     .word 0
.Lds_save_x_int:    .word 0
.Lds_save_x_lo:     .word 0
.Lds_save_xsi:      .word 0
.Lds_save_xsl:      .word 0
.Lds_save_y_int:    .word 0
.Lds_save_y_lo:     .word 0
.Lds_save_ysi:      .word 0
.Lds_save_ysl:      .word 0

/* Pre-negated loop constants (filled during setup epilogue) */
.Lds_ns:    .word 0    /* -ds_source          */
.Lds_nc:    .word 0    /* -ds_colormap        */
.Lds_nxsl:  .word 0    /* -xstep_lo           */
.Lds_nysl:  .word 0    /* -ystep_lo           */
.Lds_nxsi:  .word 0    /* -(4*xstep_int)      */
.Lds_nys:   .word 0    /* -(4*ystep_scaled)   */

/* Negated return address constants */
.Lds_sra1_ret_neg:  .word -.Lds_sra1_ret
.Lds_sra2_ret_neg:  .word -.Lds_sra2_ret
.Lds_sra3_ret_neg:  .word -.Lds_sra3_ret
.Lds_sra4_ret_neg:  .word -.Lds_sra4_ret

/* Global variable addresses */
.Lds_g_ylookup:     .word ylookup
.Lds_g_columnofs:   .word columnofs

.size R_DrawSpan, . - R_DrawSpan

