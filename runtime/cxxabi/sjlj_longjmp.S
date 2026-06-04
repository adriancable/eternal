/* sjlj_longjmp for Subleq SJLJ exception handling
 *
 * Arguments (standard Subleq calling convention):
 *   R21 = jbuf pointer
 *   R22 = return value (ignored for SJLJ)
 *
 * jbuf layout:
 *   jbuf[0] (offset 0) = frame pointer
 *   jbuf[1] (offset 4) = dispatch address
 *   jbuf[2] (offset 8) = stack pointer
 *
 * Register byte addresses:
 *   Z = REG_Z, SP = REG_SP, RA = 20, FP = REG_FP
 *   R21 = REG_R21, T0 = REG_T0, T1 = REG_T1
 *   Indirect flag = 2 (add to address for indirect mode)
 *   T0+I = REG_T0 | INDIRECT
 */

.text
.globl sjlj_longjmp
.type sjlj_longjmp, @function
.align 4

.set REG_Z, 12
.set REG_SP, 16
.set REG_R21, 100
.set REG_FP, 148
.set REG_T0, 160
.set REG_T1, 164
.set REG_T2, 168
.set INDIRECT, 1

sjlj_longjmp:

	/* ===== Load dispatch address from jbuf[1] (offset 4) ===== */
	/* T0 = R21 */
	.word REG_T0, REG_T0, .+4		/* T0 = 0 */
	.word REG_Z, REG_Z, .+4		/* Z = 0 */
	.word REG_R21, REG_Z, .+4		/* Z = -R21 */
	.word REG_Z, REG_T0, .+4		/* T0 = R21 */
	.word REG_Z, REG_Z, .+4		/* Z = 0 */
	/* T0 = T0 + 4 */
	.word .Lneg4a, REG_T0, .+4		/* T0 = T0 - (-4) = T0 + 4 */
	
	/* T1 = m[T0] (indirect load) */
	.word REG_T1, REG_T1, .+4		/* T1 = 0 */
	.word REG_T0 | INDIRECT, REG_T1, .+4		/* T1 = T1 - m[T0] = -m[T0] */
	
	/* Store dispatch in a safe scratch register (T2 = byte REG_T2) */
	/* T2 is caller-saved so it's safe to clobber */
	.word REG_T2, REG_T2, .+4		/* T2 = 0 */
	.word REG_T1, REG_T2, .+4		/* T2 = -T1 = dispatch */

	/* ===== Load new SP from jbuf[2] (offset 8) ===== */
	/* T0 = R21 + 8 */
	.word REG_T0, REG_T0, .+4
	.word REG_Z, REG_Z, .+4
	.word REG_R21, REG_Z, .+4
	.word REG_Z, REG_T0, .+4
	.word REG_Z, REG_Z, .+4
	.word .Lneg8a, REG_T0, .+4

	/* T1 = m[T0] */
	.word REG_T1, REG_T1, .+4
	.word REG_T0 | INDIRECT, REG_T1, .+4
	
	/* SP = -T1 = new_sp */
	.word REG_SP, REG_SP, .+4
	.word REG_T1, REG_SP, .+4

	/* ===== Load new FP from jbuf[0] (offset 0) ===== */
	/* T0 = R21 (no offset needed) */
	.word REG_T0, REG_T0, .+4
	.word REG_Z, REG_Z, .+4
	.word REG_R21, REG_Z, .+4
	.word REG_Z, REG_T0, .+4
	.word REG_Z, REG_Z, .+4

	/* T1 = m[T0] */
	.word REG_T1, REG_T1, .+4
	.word REG_T0 | INDIRECT, REG_T1, .+4
	
	/* FP = -T1 = new_fp */
	.word REG_FP, REG_FP, .+4
	.word REG_T1, REG_FP, .+4

	/* ===== Jump to dispatch address (stored in T2) ===== */
	/* Clear Z and jump using T2's value (indirect on C operand) */
	.word REG_Z, REG_Z, REG_T2 | INDIRECT		/* subleq(Z, Z, [T2]) */

.size sjlj_longjmp, .-sjlj_longjmp

/* Inline constants (-4 and -8) */
.align 4
.Lneg4a:
	.word -4
.Lneg8a:
	.word -8
