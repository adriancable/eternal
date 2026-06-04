// ============================================================================
// Subleq Soft Float Runtime
// Extracted from LLVM compiler-rt lib/builtins
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// ============================================================================
//
// This file provides IEEE 754 soft float implementations for the Subleq
// target. It is a freestanding library with no external dependencies.
//
// Provides: Single-precision (float) and double-precision (double)
// - Arithmetic: add, sub, mul, div
// - Comparison: eq, ne, lt, le, gt, ge, unord
// - Float-to-int: fixsfsi, fixsfdi, fixunssfsi, fixunssfdi, fixdfsi, fixdfdi, fixunsdfsi, fixunsdfdi
// - Int-to-float: floatsisf, floatdisf, floatunsisf, floatundisf, floatsidf, floatdidf, floatunsidf, floatundidf
// - Precision conversion: extendsfdf2, truncdfsf2
// - Complex arithmetic: mulsc3, divsc3, muldc3, divdc3
// ============================================================================

// Freestanding type definitions (no headers required)
typedef signed char int8_t;
typedef unsigned char uint8_t;
typedef signed short int16_t;
typedef unsigned short uint16_t;
typedef signed int int32_t;
typedef unsigned int uint32_t;
typedef signed long long int64_t;
typedef unsigned long long uint64_t;

typedef _Bool bool;
#define true 1
#define false 0

#define CHAR_BIT 8
#define INT_MAX 0x7FFFFFFF
#define INT_MIN (-INT_MAX - 1)
#define UINT_MAX 0xFFFFFFFFU

// Constant suffix macros
#define UINT16_C(x) ((uint16_t)(x))
#define UINT32_C(x) ((uint32_t)(x ## U))
#define UINT64_C(x) ((uint64_t)(x ## ULL))


// ============================================================================
// int_endianness.h - Endianness detection
// ============================================================================

#if defined(__BYTE_ORDER__) && defined(__ORDER_BIG_ENDIAN__) && \
    defined(__ORDER_LITTLE_ENDIAN__)
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
#define _YUGA_LITTLE_ENDIAN 0
#define _YUGA_BIG_ENDIAN 1
#elif __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
#define _YUGA_LITTLE_ENDIAN 1
#define _YUGA_BIG_ENDIAN 0
#endif
#else
// Default to little endian for Subleq
#define _YUGA_LITTLE_ENDIAN 1
#define _YUGA_BIG_ENDIAN 0
#endif

// ============================================================================
// int_types.h - Type definitions
// ============================================================================

typedef int32_t si_int;
typedef uint32_t su_int;
typedef int64_t di_int;
typedef uint64_t du_int;

typedef union {
  di_int all;
  struct {
#if _YUGA_LITTLE_ENDIAN
    su_int low;
    si_int high;
#else
    si_int high;
    su_int low;
#endif
  } s;
} dwords;

typedef union {
  du_int all;
  struct {
#if _YUGA_LITTLE_ENDIAN
    su_int low;
    su_int high;
#else
    su_int high;
    su_int low;
#endif
  } s;
} udwords;

typedef union {
  su_int u;
  float f;
} float_bits;

typedef union {
  udwords u;
  double f;
} double_bits;

// ============================================================================
// int_lib.h - ABI macro
// ============================================================================

#define COMPILER_RT_ABI

// ============================================================================
// Forward declarations for exported functions (fixes -Wmissing-prototypes)
// ============================================================================

typedef int CMP_RESULT;

// Single-precision arithmetic
COMPILER_RT_ABI float __addsf3(float a, float b);
COMPILER_RT_ABI float __subsf3(float a, float b);
COMPILER_RT_ABI float __mulsf3(float a, float b);
COMPILER_RT_ABI float __divsf3(float a, float b);

// Single-precision comparisons
COMPILER_RT_ABI CMP_RESULT __lesf2(float a, float b);
COMPILER_RT_ABI CMP_RESULT __eqsf2(float a, float b);
COMPILER_RT_ABI CMP_RESULT __ltsf2(float a, float b);
COMPILER_RT_ABI CMP_RESULT __nesf2(float a, float b);
COMPILER_RT_ABI CMP_RESULT __gesf2(float a, float b);
COMPILER_RT_ABI CMP_RESULT __gtsf2(float a, float b);
COMPILER_RT_ABI CMP_RESULT __unordsf2(float a, float b);

// Single-precision to int conversions
COMPILER_RT_ABI si_int __fixsfsi(float a);
COMPILER_RT_ABI di_int __fixsfdi(float a);
COMPILER_RT_ABI su_int __fixunssfsi(float a);
COMPILER_RT_ABI du_int __fixunssfdi(float a);

// Int to single-precision conversions
COMPILER_RT_ABI float __floatsisf(si_int a);
COMPILER_RT_ABI float __floatunsisf(su_int a);
COMPILER_RT_ABI float __floatdisf(di_int a);
COMPILER_RT_ABI float __floatundisf(du_int a);

// Double-precision arithmetic
COMPILER_RT_ABI double __adddf3(double a, double b);
COMPILER_RT_ABI double __subdf3(double a, double b);
COMPILER_RT_ABI double __muldf3(double a, double b);
COMPILER_RT_ABI double __divdf3(double a, double b);

// Double-precision comparisons
COMPILER_RT_ABI CMP_RESULT __ledf2(double a, double b);
COMPILER_RT_ABI CMP_RESULT __gedf2(double a, double b);
COMPILER_RT_ABI CMP_RESULT __eqdf2(double a, double b);
COMPILER_RT_ABI CMP_RESULT __ltdf2(double a, double b);
COMPILER_RT_ABI CMP_RESULT __nedf2(double a, double b);
COMPILER_RT_ABI CMP_RESULT __gtdf2(double a, double b);
COMPILER_RT_ABI CMP_RESULT __unorddf2(double a, double b);

// Double-precision to int conversions
COMPILER_RT_ABI si_int __fixdfsi(double a);
COMPILER_RT_ABI di_int __fixdfdi(double a);
COMPILER_RT_ABI su_int __fixunsdfsi(double a);
COMPILER_RT_ABI du_int __fixunsdfdi(double a);

// Int to double-precision conversions
COMPILER_RT_ABI double __floatsidf(si_int a);
COMPILER_RT_ABI double __floatunsidf(su_int a);
COMPILER_RT_ABI double __floatdidf(di_int a);
COMPILER_RT_ABI double __floatundidf(du_int a);

// Precision conversions
COMPILER_RT_ABI double __extendsfdf2(float a);
COMPILER_RT_ABI float __truncdfsf2(double a);

// ============================================================================
// Utility macros and functions
// ============================================================================

// Count leading zeros for 32-bit integer
static __inline int __clzsi2(si_int a) {
  su_int x = (su_int)a;
  si_int t = ((x & 0xFFFF0000) == 0) << 4;
  x >>= 16 - t;
  su_int r = t;
  t = ((x & 0xFF00) == 0) << 3;
  x >>= 8 - t;
  r += t;
  t = ((x & 0xF0) == 0) << 2;
  x >>= 4 - t;
  r += t;
  t = ((x & 0xC) == 0) << 1;
  x >>= 2 - t;
  r += t;
  return r + ((2 - x) & -((x & 2) == 0));
}

#define clzsi __clzsi2

// ============================================================================
// int_math.h - Math utilities (freestanding)
// ============================================================================

#define CRT_INFINITY __builtin_huge_valf()
#define crt_isfinite(x) __builtin_isfinite((x))
#define crt_isinf(x) __builtin_isinf((x))
#define crt_isnan(x) __builtin_isnan((x))
#define crt_copysign(x, y) __builtin_copysign((x), (y))
#define crt_copysignf(x, y) __builtin_copysignf((x), (y))
#define crt_fabs(x) __builtin_fabs((x))
#define crt_fabsf(x) __builtin_fabsf((x))

// ============================================================================
// fp_mode.h / fp_mode.c - Floating-point rounding mode
// ============================================================================

typedef enum {
  CRT_FE_TONEAREST,
  CRT_FE_DOWNWARD,
  CRT_FE_UPWARD,
  CRT_FE_TOWARDZERO
} CRT_FE_ROUND_MODE;

// Default: IEEE-754 round-to-nearest, ties-to-even
static __inline CRT_FE_ROUND_MODE __fe_getround(void) { return CRT_FE_TONEAREST; }
static __inline int __fe_raise_inexact(void) { return 0; }

// ============================================================================
// SINGLE PRECISION (float) - fp_lib.h configuration
// ============================================================================

#define SINGLE_PRECISION

typedef uint16_t half_rep_t;
typedef uint32_t rep_t;
typedef uint64_t twice_rep_t;
typedef int32_t srep_t;
typedef float fp_t;
#define HALF_REP_C UINT16_C
#define REP_C UINT32_C
#define significandBits 23

static __inline int rep_clz(rep_t a) { return clzsi(a); }

// 32x32 --> 64 bit multiply
static __inline void wideMultiply(rep_t a, rep_t b, rep_t *hi, rep_t *lo) {
  const uint64_t product = (uint64_t)a * b;
  *hi = (rep_t)(product >> 32);
  *lo = (rep_t)product;
}

#define typeWidth (sizeof(rep_t) * CHAR_BIT)

static __inline rep_t toRep(fp_t x) {
  const union { fp_t f; rep_t i; } rep = {.f = x};
  return rep.i;
}

static __inline fp_t fromRep(rep_t x) {
  const union { fp_t f; rep_t i; } rep = {.i = x};
  return rep.f;
}

#define exponentBits (typeWidth - significandBits - 1)
#define maxExponent ((1 << exponentBits) - 1)
#define exponentBias (maxExponent >> 1)

#define implicitBit (REP_C(1) << significandBits)
#define significandMask (implicitBit - 1U)
#define signBit (REP_C(1) << (significandBits + exponentBits))
#define absMask (signBit - 1U)
#define exponentMask (absMask ^ significandMask)
#define oneRep ((rep_t)exponentBias << significandBits)
#define infRep exponentMask
#define quietBit (implicitBit >> 1)
#define qnanRep (exponentMask | quietBit)

static __inline int normalize(rep_t *significand) {
  const int shift = rep_clz(*significand) - rep_clz(implicitBit);
  *significand <<= shift;
  return 1 - shift;
}

static __inline void wideLeftShift(rep_t *hi, rep_t *lo, unsigned int count) {
  *hi = *hi << count | *lo >> (typeWidth - count);
  *lo = *lo << count;
}

static __inline void wideRightShiftWithSticky(rep_t *hi, rep_t *lo, unsigned int count) {
  if (count < typeWidth) {
    const bool sticky = (*lo << (typeWidth - count)) != 0;
    *lo = *hi << (typeWidth - count) | *lo >> count | sticky;
    *hi = *hi >> count;
  } else if (count < 2 * typeWidth) {
    const bool sticky = *hi << (2 * typeWidth - count) | *lo;
    *lo = *hi >> (count - typeWidth) | sticky;
    *hi = 0;
  } else {
    const bool sticky = *hi | *lo;
    *lo = sticky;
    *hi = 0;
  }
}

// ============================================================================
// Single-precision addition: __addsf3
// ============================================================================

static __inline fp_t __addXf3__(fp_t a, fp_t b) {
  rep_t aRep = toRep(a);
  rep_t bRep = toRep(b);
  const rep_t aAbs = aRep & absMask;
  const rep_t bAbs = bRep & absMask;

  if (aAbs - REP_C(1) >= infRep - REP_C(1) ||
      bAbs - REP_C(1) >= infRep - REP_C(1)) {
    if (aAbs > infRep) return fromRep(toRep(a) | quietBit);
    if (bAbs > infRep) return fromRep(toRep(b) | quietBit);
    if (aAbs == infRep) {
      if ((toRep(a) ^ toRep(b)) == signBit) return fromRep(qnanRep);
      else return a;
    }
    if (bAbs == infRep) return b;
    if (!aAbs) {
      if (!bAbs) return fromRep(toRep(a) & toRep(b));
      else return b;
    }
    if (!bAbs) return a;
  }

  if (bAbs > aAbs) {
    const rep_t temp = aRep;
    aRep = bRep;
    bRep = temp;
  }

  int aExponent = aRep >> significandBits & maxExponent;
  int bExponent = bRep >> significandBits & maxExponent;
  rep_t aSignificand = aRep & significandMask;
  rep_t bSignificand = bRep & significandMask;

  if (aExponent == 0) aExponent = normalize(&aSignificand);
  if (bExponent == 0) bExponent = normalize(&bSignificand);

  const rep_t resultSign = aRep & signBit;
  const bool subtraction = (aRep ^ bRep) & signBit;

  aSignificand = (aSignificand | implicitBit) << 3;
  bSignificand = (bSignificand | implicitBit) << 3;

  const unsigned int align = (unsigned int)(aExponent - bExponent);
  if (align) {
    if (align < typeWidth) {
      const bool sticky = (bSignificand << (typeWidth - align)) != 0;
      bSignificand = bSignificand >> align | sticky;
    } else {
      bSignificand = 1;
    }
  }

  if (subtraction) {
    aSignificand -= bSignificand;
    if (aSignificand == 0) return fromRep(0);
    if (aSignificand < implicitBit << 3) {
      const int shift = rep_clz(aSignificand) - rep_clz(implicitBit << 3);
      aSignificand <<= shift;
      aExponent -= shift;
    }
  } else {
    aSignificand += bSignificand;
    if (aSignificand & implicitBit << 4) {
      const bool sticky = aSignificand & 1;
      aSignificand = aSignificand >> 1 | sticky;
      aExponent += 1;
    }
  }

  if (aExponent >= maxExponent) return fromRep(infRep | resultSign);

  if (aExponent <= 0) {
    const int shift = 1 - aExponent;
    const bool sticky = (aSignificand << (typeWidth - shift)) != 0;
    aSignificand = aSignificand >> shift | sticky;
    aExponent = 0;
  }

  const int roundGuardSticky = aSignificand & 0x7;
  rep_t result = aSignificand >> 3 & significandMask;
  result |= (rep_t)aExponent << significandBits;
  result |= resultSign;

  switch (__fe_getround()) {
  case CRT_FE_TONEAREST:
    if (roundGuardSticky > 0x4) result++;
    if (roundGuardSticky == 0x4) result += result & 1;
    break;
  case CRT_FE_DOWNWARD:
    if (resultSign && roundGuardSticky) result++;
    break;
  case CRT_FE_UPWARD:
    if (!resultSign && roundGuardSticky) result++;
    break;
  case CRT_FE_TOWARDZERO:
    break;
  }
  if (roundGuardSticky) __fe_raise_inexact();
  return fromRep(result);
}

COMPILER_RT_ABI float __addsf3(float a, float b) { return __addXf3__(a, b); }

// ============================================================================
// Single-precision subtraction: __subsf3
// ============================================================================

COMPILER_RT_ABI float __subsf3(float a, float b) {
  return __addsf3(a, fromRep(toRep(b) ^ signBit));
}


// ============================================================================
// Single-precision multiplication: __mulsf3
// ============================================================================

static __inline fp_t __mulXf3__(fp_t a, fp_t b) {
  const unsigned int aExponent = toRep(a) >> significandBits & maxExponent;
  const unsigned int bExponent = toRep(b) >> significandBits & maxExponent;
  const rep_t productSign = (toRep(a) ^ toRep(b)) & signBit;

  rep_t aSignificand = toRep(a) & significandMask;
  rep_t bSignificand = toRep(b) & significandMask;
  int scale = 0;

  if (aExponent - 1U >= maxExponent - 1U || bExponent - 1U >= maxExponent - 1U) {
    const rep_t aAbs = toRep(a) & absMask;
    const rep_t bAbs = toRep(b) & absMask;

    if (aAbs > infRep) return fromRep(toRep(a) | quietBit);
    if (bAbs > infRep) return fromRep(toRep(b) | quietBit);

    if (aAbs == infRep) {
      if (bAbs) return fromRep(aAbs | productSign);
      else return fromRep(qnanRep);
    }
    if (bAbs == infRep) {
      if (aAbs) return fromRep(bAbs | productSign);
      else return fromRep(qnanRep);
    }
    if (!aAbs) return fromRep(productSign);
    if (!bAbs) return fromRep(productSign);

    if (aAbs < implicitBit) scale += normalize(&aSignificand);
    if (bAbs < implicitBit) scale += normalize(&bSignificand);
  }

  aSignificand |= implicitBit;
  bSignificand |= implicitBit;

  rep_t productHi, productLo;
  wideMultiply(aSignificand, bSignificand << exponentBits, &productHi, &productLo);

  int productExponent = aExponent + bExponent - exponentBias + scale;

  if (productHi & implicitBit) productExponent++;
  else wideLeftShift(&productHi, &productLo, 1);

  if (productExponent >= maxExponent) return fromRep(infRep | productSign);

  if (productExponent <= 0) {
    const unsigned int shift = REP_C(1) - (unsigned int)productExponent;
    if (shift >= typeWidth) return fromRep(productSign);
    wideRightShiftWithSticky(&productHi, &productLo, shift);
  } else {
    productHi &= significandMask;
    productHi |= (rep_t)productExponent << significandBits;
  }

  productHi |= productSign;

  if (productLo > signBit) productHi++;
  if (productLo == signBit) productHi += productHi & 1;
  return fromRep(productHi);
}

COMPILER_RT_ABI float __mulsf3(float a, float b) { return __mulXf3__(a, b); }

// ============================================================================
// Single-precision division: __divsf3
// ============================================================================

#define NUMBER_OF_HALF_ITERATIONS 0
#define NUMBER_OF_FULL_ITERATIONS 3

#define HW (typeWidth / 2)
#define loMask (REP_C(-1) >> HW)

#define REPEAT_1_TIMES(code) code
#define REPEAT_2_TIMES(code) code code
#define REPEAT_3_TIMES(code) code code code
#define REPEAT_N_TIMES(n, code) REPEAT_##n##_TIMES(code)

static __inline fp_t __divXf3__(fp_t a, fp_t b) {
  const unsigned int aExponent = toRep(a) >> significandBits & maxExponent;
  const unsigned int bExponent = toRep(b) >> significandBits & maxExponent;
  const rep_t quotientSign = (toRep(a) ^ toRep(b)) & signBit;

  rep_t aSignificand = toRep(a) & significandMask;
  rep_t bSignificand = toRep(b) & significandMask;
  int scale = 0;

  if (aExponent - 1U >= maxExponent - 1U || bExponent - 1U >= maxExponent - 1U) {
    const rep_t aAbs = toRep(a) & absMask;
    const rep_t bAbs = toRep(b) & absMask;

    if (aAbs > infRep) return fromRep(toRep(a) | quietBit);
    if (bAbs > infRep) return fromRep(toRep(b) | quietBit);

    if (aAbs == infRep) {
      if (bAbs == infRep) return fromRep(qnanRep);
      else return fromRep(aAbs | quotientSign);
    }
    if (bAbs == infRep) return fromRep(quotientSign);

    if (!aAbs) {
      if (!bAbs) return fromRep(qnanRep);
      else return fromRep(quotientSign);
    }
    if (!bAbs) return fromRep(infRep | quotientSign);

    if (aAbs < implicitBit) scale += normalize(&aSignificand);
    if (bAbs < implicitBit) scale -= normalize(&bSignificand);
  }

  aSignificand |= implicitBit;
  bSignificand |= implicitBit;

  int writtenExponent = (aExponent - bExponent + scale) + exponentBias;
  const rep_t b_UQ1 = bSignificand << (typeWidth - significandBits - 1);

  // Newton-Raphson: x0 = 3/4 + 1/sqrt(2) - b/2
  const rep_t C = REP_C(0x7504F333) << (typeWidth - 32);
  rep_t x_UQ0 = C - b_UQ1;

  // Three full-width iterations (unrolled)
  {
    rep_t corr_UQ1 = 0 - ((twice_rep_t)x_UQ0 * b_UQ1 >> typeWidth);
    x_UQ0 = (twice_rep_t)x_UQ0 * corr_UQ1 >> (typeWidth - 1);
  }
  {
    rep_t corr_UQ1 = 0 - ((twice_rep_t)x_UQ0 * b_UQ1 >> typeWidth);
    x_UQ0 = (twice_rep_t)x_UQ0 * corr_UQ1 >> (typeWidth - 1);
  }
  {
    rep_t corr_UQ1 = 0 - ((twice_rep_t)x_UQ0 * b_UQ1 >> typeWidth);
    x_UQ0 = (twice_rep_t)x_UQ0 * corr_UQ1 >> (typeWidth - 1);
  }

  x_UQ0 -= 2U;
  x_UQ0 -= REP_C(10);  // RECIPROCAL_PRECISION for 0+3 iterations

  rep_t quotient_UQ1, dummy;
  wideMultiply(x_UQ0, aSignificand << 1, &quotient_UQ1, &dummy);

  rep_t residualLo;
  if (quotient_UQ1 < (implicitBit << 1)) {
    if (quotient_UQ1 < implicitBit) {
      quotient_UQ1 <<= 1;
      writtenExponent -= 1;
    }
    residualLo = (aSignificand << (significandBits + 1)) - quotient_UQ1 * bSignificand;
    writtenExponent -= 1;
    aSignificand <<= 1;
  } else {
    quotient_UQ1 >>= 1;
    residualLo = (aSignificand << significandBits) - quotient_UQ1 * bSignificand;
  }

  if (writtenExponent >= maxExponent) return fromRep(infRep | quotientSign);

  rep_t absResult;
  if (writtenExponent > 0) {
    absResult = quotient_UQ1 & significandMask;
    absResult |= (rep_t)writtenExponent << significandBits;
    residualLo <<= 1;
  } else {
    if (significandBits + writtenExponent < 0) return fromRep(quotientSign);
    absResult = quotient_UQ1 >> (-writtenExponent + 1);
    residualLo = (aSignificand << (significandBits + writtenExponent)) - (absResult * bSignificand << 1);
  }

  residualLo += absResult & 1;
  absResult += residualLo > bSignificand;
  return fromRep(absResult | quotientSign);
}

COMPILER_RT_ABI float __divsf3(float a, float b) { return __divXf3__(a, b); }

#undef NUMBER_OF_HALF_ITERATIONS
#undef NUMBER_OF_FULL_ITERATIONS
#undef HW
#undef loMask

// ============================================================================
// Single-precision comparison functions
// ============================================================================

static inline CMP_RESULT __leXf2__(fp_t a, fp_t b) {
  const srep_t aInt = toRep(a);
  const srep_t bInt = toRep(b);
  const rep_t aAbs = aInt & absMask;
  const rep_t bAbs = bInt & absMask;

  if (aAbs > infRep || bAbs > infRep) return 1;
  if ((aAbs | bAbs) == 0) return 0;

  if ((aInt & bInt) >= 0) {
    if (aInt < bInt) return -1;
    else if (aInt == bInt) return 0;
    else return 1;
  } else {
    if (aInt > bInt) return -1;
    else if (aInt == bInt) return 0;
    else return 1;
  }
}

static inline CMP_RESULT __geXf2__(fp_t a, fp_t b) {
  const srep_t aInt = toRep(a);
  const srep_t bInt = toRep(b);
  const rep_t aAbs = aInt & absMask;
  const rep_t bAbs = bInt & absMask;

  if (aAbs > infRep || bAbs > infRep) return -1;
  if ((aAbs | bAbs) == 0) return 0;

  if ((aInt & bInt) >= 0) {
    if (aInt < bInt) return -1;
    else if (aInt == bInt) return 0;
    else return 1;
  } else {
    if (aInt > bInt) return -1;
    else if (aInt == bInt) return 0;
    else return 1;
  }
}

COMPILER_RT_ABI CMP_RESULT __lesf2(float a, float b) { return __leXf2__(a, b); }
COMPILER_RT_ABI CMP_RESULT __eqsf2(float a, float b) { return __leXf2__(a, b); }
COMPILER_RT_ABI CMP_RESULT __ltsf2(float a, float b) { return __leXf2__(a, b); }
COMPILER_RT_ABI CMP_RESULT __nesf2(float a, float b) { return __leXf2__(a, b); }
COMPILER_RT_ABI CMP_RESULT __gesf2(float a, float b) { return __geXf2__(a, b); }
COMPILER_RT_ABI CMP_RESULT __gtsf2(float a, float b) { return __geXf2__(a, b); }
COMPILER_RT_ABI CMP_RESULT __unordsf2(float a, float b) {
  return (toRep(a) & absMask) > infRep || (toRep(b) & absMask) > infRep;
}

// ============================================================================
// Float to int conversions
// ============================================================================

COMPILER_RT_ABI si_int __fixsfsi(float a) {
  const rep_t aRep = toRep(a);
  const rep_t aAbs = aRep & absMask;
  const si_int sign = aRep & signBit ? -1 : 1;
  const int exponent = (aAbs >> significandBits) - exponentBias;
  const rep_t significand = (aAbs & significandMask) | implicitBit;

  if (exponent < 0) return 0;
  if ((unsigned)exponent >= 31) return sign == 1 ? 0x7FFFFFFF : (si_int)0x80000000;
  if (exponent < significandBits)
    return (si_int)(sign * (significand >> (significandBits - exponent)));
  return (si_int)(sign * ((su_int)significand << (exponent - significandBits)));
}

COMPILER_RT_ABI di_int __fixsfdi(float a) {
  const rep_t aRep = toRep(a);
  const rep_t aAbs = aRep & absMask;
  const di_int sign = aRep & signBit ? -1 : 1;
  const int exponent = (aAbs >> significandBits) - exponentBias;
  const rep_t significand = (aAbs & significandMask) | implicitBit;

  if (exponent < 0) return 0;
  if ((unsigned)exponent >= 63) return sign == 1 ? 0x7FFFFFFFFFFFFFFFLL : (di_int)0x8000000000000000LL;
  if (exponent < significandBits)
    return (di_int)(sign * (significand >> (significandBits - exponent)));
  return (di_int)(sign * ((du_int)significand << (exponent - significandBits)));
}

COMPILER_RT_ABI su_int __fixunssfsi(float a) {
  const rep_t aRep = toRep(a);
  const rep_t aAbs = aRep & absMask;
  if (aRep & signBit) return 0;
  const int exponent = (aAbs >> significandBits) - exponentBias;
  const rep_t significand = (aAbs & significandMask) | implicitBit;

  if (exponent < 0) return 0;
  if ((unsigned)exponent >= 32) return ~(su_int)0;
  if (exponent < significandBits)
    return significand >> (significandBits - exponent);
  return (su_int)significand << (exponent - significandBits);
}

COMPILER_RT_ABI du_int __fixunssfdi(float a) {
  const rep_t aRep = toRep(a);
  const rep_t aAbs = aRep & absMask;
  if (aRep & signBit) return 0;
  const int exponent = (aAbs >> significandBits) - exponentBias;
  const rep_t significand = (aAbs & significandMask) | implicitBit;

  if (exponent < 0) return 0;
  if ((unsigned)exponent >= 64) return ~(du_int)0;
  if (exponent < significandBits)
    return significand >> (significandBits - exponent);
  return (du_int)significand << (exponent - significandBits);
}

// ============================================================================
// Int to float conversions
// ============================================================================

COMPILER_RT_ABI float __floatsisf(si_int a) {
  if (a == 0) return fromRep(0);
  const su_int sign = a < 0 ? signBit : 0;
  su_int aAbs = a < 0 ? -(su_int)a : (su_int)a;
  int e = 31 - __clzsi2(aAbs);
  if (e <= significandBits) {
    return fromRep(sign | ((rep_t)(e + exponentBias) << significandBits) |
                   ((aAbs << (significandBits - e)) & significandMask));
  }
  int shift = e - significandBits;
  rep_t result = (aAbs >> shift) & significandMask;
  result |= (rep_t)(e + exponentBias) << significandBits;
  result |= sign;
  su_int round = (aAbs >> (shift - 1)) & 1;
  su_int sticky = (aAbs & ((1U << (shift - 1)) - 1)) != 0;
  if (round && (sticky || (result & 1))) result++;
  return fromRep(result);
}

COMPILER_RT_ABI float __floatunsisf(su_int a) {
  if (a == 0) return fromRep(0);
  int e = 31 - __clzsi2(a);
  if (e <= significandBits) {
    return fromRep(((rep_t)(e + exponentBias) << significandBits) |
                   ((a << (significandBits - e)) & significandMask));
  }
  int shift = e - significandBits;
  rep_t result = (a >> shift) & significandMask;
  result |= (rep_t)(e + exponentBias) << significandBits;
  su_int round = (a >> (shift - 1)) & 1;
  su_int sticky = (a & ((1U << (shift - 1)) - 1)) != 0;
  if (round && (sticky || (result & 1))) result++;
  return fromRep(result);
}

COMPILER_RT_ABI float __floatdisf(di_int a) {
  if (a == 0) return fromRep(0);
  const rep_t sign = a < 0 ? signBit : 0;
  du_int aAbs = a < 0 ? -(du_int)a : (du_int)a;
  int e = 63 - __builtin_clzll(aAbs);
  if (e <= significandBits) {
    return fromRep(sign | ((rep_t)(e + exponentBias) << significandBits) |
                   (((rep_t)aAbs << (significandBits - e)) & significandMask));
  }
  int shift = e - significandBits;
  rep_t result = ((rep_t)(aAbs >> shift)) & significandMask;
  result |= (rep_t)(e + exponentBias) << significandBits;
  result |= sign;
  du_int round = (aAbs >> (shift - 1)) & 1;
  du_int sticky = (aAbs & ((1ULL << (shift - 1)) - 1)) != 0;
  if (round && (sticky || (result & 1))) result++;
  return fromRep(result);
}

COMPILER_RT_ABI float __floatundisf(du_int a) {
  if (a == 0) return fromRep(0);
  int e = 63 - __builtin_clzll(a);
  if (e <= significandBits) {
    return fromRep(((rep_t)(e + exponentBias) << significandBits) |
                   (((rep_t)a << (significandBits - e)) & significandMask));
  }
  int shift = e - significandBits;
  rep_t result = ((rep_t)(a >> shift)) & significandMask;
  result |= (rep_t)(e + exponentBias) << significandBits;
  du_int round = (a >> (shift - 1)) & 1;
  du_int sticky = (a & ((1ULL << (shift - 1)) - 1)) != 0;
  if (round && (sticky || (result & 1))) result++;
  return fromRep(result);
}

// ============================================================================
// DOUBLE PRECISION (double) SECTION
// ============================================================================

#undef SINGLE_PRECISION

#define DOUBLE_PRECISION

typedef uint32_t df_half_rep_t;
typedef uint64_t df_rep_t;
typedef int64_t df_srep_t;
typedef double df_fp_t;
#define DF_REP_C UINT64_C
#define df_significandBits 52
#define df_typeWidth 64
#define df_exponentBits 11
#define df_maxExponent ((1 << df_exponentBits) - 1)
#define df_exponentBias (df_maxExponent >> 1)
#define df_implicitBit (DF_REP_C(1) << df_significandBits)
#define df_significandMask (df_implicitBit - 1U)
#define df_signBit (DF_REP_C(1) << (df_significandBits + df_exponentBits))
#define df_absMask (df_signBit - 1U)
#define df_exponentMask (df_absMask ^ df_significandMask)
#define df_infRep df_exponentMask
#define df_quietBit (df_implicitBit >> 1)
#define df_qnanRep (df_exponentMask | df_quietBit)

static __inline int df_rep_clz(df_rep_t a) { return __builtin_clzll(a); }

static __inline df_rep_t df_toRep(df_fp_t x) {
  const union { df_fp_t f; df_rep_t i; } rep = {.f = x};
  return rep.i;
}

static __inline df_fp_t df_fromRep(df_rep_t x) {
  const union { df_fp_t f; df_rep_t i; } rep = {.i = x};
  return rep.f;
}

static __inline int df_normalize(df_rep_t *significand) {
  const int shift = df_rep_clz(*significand) - df_rep_clz(df_implicitBit);
  *significand <<= shift;
  return 1 - shift;
}

#define df_loWord(a) ((a) & 0xffffffffU)
#define df_hiWord(a) ((a) >> 32)

static __inline void df_wideMultiply(df_rep_t a, df_rep_t b, df_rep_t *hi, df_rep_t *lo) {
  const uint64_t plolo = df_loWord(a) * df_loWord(b);
  const uint64_t plohi = df_loWord(a) * df_hiWord(b);
  const uint64_t philo = df_hiWord(a) * df_loWord(b);
  const uint64_t phihi = df_hiWord(a) * df_hiWord(b);
  const uint64_t r0 = df_loWord(plolo);
  const uint64_t r1 = df_hiWord(plolo) + df_loWord(plohi) + df_loWord(philo);
  *lo = r0 + (r1 << 32);
  *hi = df_hiWord(plohi) + df_hiWord(philo) + df_hiWord(r1) + phihi;
}

static __inline void df_wideLeftShift(df_rep_t *hi, df_rep_t *lo, unsigned int count) {
  *hi = *hi << count | *lo >> (df_typeWidth - count);
  *lo = *lo << count;
}

static __inline void df_wideRightShiftWithSticky(df_rep_t *hi, df_rep_t *lo, unsigned int count) {
  if (count < df_typeWidth) {
    const bool sticky = (*lo << (df_typeWidth - count)) != 0;
    *lo = *hi << (df_typeWidth - count) | *lo >> count | sticky;
    *hi = *hi >> count;
  } else if (count < 2 * df_typeWidth) {
    const bool sticky = *hi << (2 * df_typeWidth - count) | *lo;
    *lo = *hi >> (count - df_typeWidth) | sticky;
    *hi = 0;
  } else {
    const bool sticky = *hi | *lo;
    *lo = sticky;
    *hi = 0;
  }
}

// ============================================================================
// Double-precision addition: __adddf3
// ============================================================================

COMPILER_RT_ABI double __adddf3(double a, double b) {
  df_rep_t aRep = df_toRep(a);
  df_rep_t bRep = df_toRep(b);
  const df_rep_t aAbs = aRep & df_absMask;
  const df_rep_t bAbs = bRep & df_absMask;

  if (aAbs - DF_REP_C(1) >= df_infRep - DF_REP_C(1) ||
      bAbs - DF_REP_C(1) >= df_infRep - DF_REP_C(1)) {
    if (aAbs > df_infRep) return df_fromRep(df_toRep(a) | df_quietBit);
    if (bAbs > df_infRep) return df_fromRep(df_toRep(b) | df_quietBit);
    if (aAbs == df_infRep) {
      if ((df_toRep(a) ^ df_toRep(b)) == df_signBit) return df_fromRep(df_qnanRep);
      else return a;
    }
    if (bAbs == df_infRep) return b;
    if (!aAbs) { if (!bAbs) return df_fromRep(df_toRep(a) & df_toRep(b)); else return b; }
    if (!bAbs) return a;
  }

  if (bAbs > aAbs) { df_rep_t temp = aRep; aRep = bRep; bRep = temp; }

  int aExponent = aRep >> df_significandBits & df_maxExponent;
  int bExponent = bRep >> df_significandBits & df_maxExponent;
  df_rep_t aSignificand = aRep & df_significandMask;
  df_rep_t bSignificand = bRep & df_significandMask;

  if (aExponent == 0) aExponent = df_normalize(&aSignificand);
  if (bExponent == 0) bExponent = df_normalize(&bSignificand);

  const df_rep_t resultSign = aRep & df_signBit;
  const bool subtraction = (aRep ^ bRep) & df_signBit;

  aSignificand = (aSignificand | df_implicitBit) << 3;
  bSignificand = (bSignificand | df_implicitBit) << 3;

  const unsigned int align = (unsigned int)(aExponent - bExponent);
  if (align) {
    if (align < df_typeWidth) {
      const bool sticky = (bSignificand << (df_typeWidth - align)) != 0;
      bSignificand = bSignificand >> align | sticky;
    } else {
      bSignificand = 1;
    }
  }

  if (subtraction) {
    aSignificand -= bSignificand;
    if (aSignificand == 0) return df_fromRep(0);
    if (aSignificand < df_implicitBit << 3) {
      const int shift = df_rep_clz(aSignificand) - df_rep_clz(df_implicitBit << 3);
      aSignificand <<= shift;
      aExponent -= shift;
    }
  } else {
    aSignificand += bSignificand;
    if (aSignificand & df_implicitBit << 4) {
      const bool sticky = aSignificand & 1;
      aSignificand = aSignificand >> 1 | sticky;
      aExponent += 1;
    }
  }

  if (aExponent >= df_maxExponent) return df_fromRep(df_infRep | resultSign);

  if (aExponent <= 0) {
    const int shift = 1 - aExponent;
    const bool sticky = (aSignificand << (df_typeWidth - shift)) != 0;
    aSignificand = aSignificand >> shift | sticky;
    aExponent = 0;
  }

  const int roundGuardSticky = aSignificand & 0x7;
  df_rep_t result = aSignificand >> 3 & df_significandMask;
  result |= (df_rep_t)aExponent << df_significandBits;
  result |= resultSign;

  if (roundGuardSticky > 0x4) result++;
  if (roundGuardSticky == 0x4) result += result & 1;
  return df_fromRep(result);
}

COMPILER_RT_ABI double __subdf3(double a, double b) {
  return __adddf3(a, df_fromRep(df_toRep(b) ^ df_signBit));
}



// ============================================================================
// Double-precision multiplication: __muldf3
// ============================================================================

COMPILER_RT_ABI double __muldf3(double a, double b) {
  const unsigned int aExponent = df_toRep(a) >> df_significandBits & df_maxExponent;
  const unsigned int bExponent = df_toRep(b) >> df_significandBits & df_maxExponent;
  const df_rep_t productSign = (df_toRep(a) ^ df_toRep(b)) & df_signBit;

  df_rep_t aSignificand = df_toRep(a) & df_significandMask;
  df_rep_t bSignificand = df_toRep(b) & df_significandMask;
  int scale = 0;

  if (aExponent - 1U >= df_maxExponent - 1U || bExponent - 1U >= df_maxExponent - 1U) {
    const df_rep_t aAbs = df_toRep(a) & df_absMask;
    const df_rep_t bAbs = df_toRep(b) & df_absMask;

    if (aAbs > df_infRep) return df_fromRep(df_toRep(a) | df_quietBit);
    if (bAbs > df_infRep) return df_fromRep(df_toRep(b) | df_quietBit);
    if (aAbs == df_infRep) return bAbs ? df_fromRep(aAbs | productSign) : df_fromRep(df_qnanRep);
    if (bAbs == df_infRep) return aAbs ? df_fromRep(bAbs | productSign) : df_fromRep(df_qnanRep);
    if (!aAbs) return df_fromRep(productSign);
    if (!bAbs) return df_fromRep(productSign);
    if (aAbs < df_implicitBit) scale += df_normalize(&aSignificand);
    if (bAbs < df_implicitBit) scale += df_normalize(&bSignificand);
  }

  aSignificand |= df_implicitBit;
  bSignificand |= df_implicitBit;

  df_rep_t productHi, productLo;
  df_wideMultiply(aSignificand, bSignificand << df_exponentBits, &productHi, &productLo);

  int productExponent = aExponent + bExponent - df_exponentBias + scale;

  if (productHi & df_implicitBit) productExponent++;
  else df_wideLeftShift(&productHi, &productLo, 1);

  if (productExponent >= df_maxExponent) return df_fromRep(df_infRep | productSign);

  if (productExponent <= 0) {
    const unsigned int shift = DF_REP_C(1) - (unsigned int)productExponent;
    if (shift >= df_typeWidth) return df_fromRep(productSign);
    df_wideRightShiftWithSticky(&productHi, &productLo, shift);
  } else {
    productHi &= df_significandMask;
    productHi |= (df_rep_t)productExponent << df_significandBits;
  }

  productHi |= productSign;
  if (productLo > df_signBit) productHi++;
  if (productLo == df_signBit) productHi += productHi & 1;
  return df_fromRep(productHi);
}

// ============================================================================
// Double-precision division: __divdf3 (simplified)
// ============================================================================

COMPILER_RT_ABI double __divdf3(double a, double b) {
  const unsigned int aExponent = df_toRep(a) >> df_significandBits & df_maxExponent;
  const unsigned int bExponent = df_toRep(b) >> df_significandBits & df_maxExponent;
  const df_rep_t quotientSign = (df_toRep(a) ^ df_toRep(b)) & df_signBit;

  df_rep_t aSignificand = df_toRep(a) & df_significandMask;
  df_rep_t bSignificand = df_toRep(b) & df_significandMask;
  int scale = 0;

  if (aExponent - 1U >= df_maxExponent - 1U || bExponent - 1U >= df_maxExponent - 1U) {
    const df_rep_t aAbs = df_toRep(a) & df_absMask;
    const df_rep_t bAbs = df_toRep(b) & df_absMask;

    if (aAbs > df_infRep) return df_fromRep(df_toRep(a) | df_quietBit);
    if (bAbs > df_infRep) return df_fromRep(df_toRep(b) | df_quietBit);
    if (aAbs == df_infRep) return bAbs == df_infRep ? df_fromRep(df_qnanRep) : df_fromRep(aAbs | quotientSign);
    if (bAbs == df_infRep) return df_fromRep(quotientSign);
    if (!aAbs) return !bAbs ? df_fromRep(df_qnanRep) : df_fromRep(quotientSign);
    if (!bAbs) return df_fromRep(df_infRep | quotientSign);
    if (aAbs < df_implicitBit) scale += df_normalize(&aSignificand);
    if (bAbs < df_implicitBit) scale -= df_normalize(&bSignificand);
  }

  aSignificand |= df_implicitBit;
  bSignificand |= df_implicitBit;

  int writtenExponent = (aExponent - bExponent + scale) + df_exponentBias;
  const df_rep_t b_UQ1 = bSignificand << (df_typeWidth - df_significandBits - 1);
  const df_half_rep_t b_UQ1_hw = bSignificand >> (df_significandBits + 1 - 32);
  const df_half_rep_t C_hw = UINT32_C(0x7504F333);
  df_half_rep_t x_UQ0_hw = C_hw - b_UQ1_hw;

  // 3 half-width iterations
  { df_half_rep_t corr = 0 - ((df_rep_t)x_UQ0_hw * b_UQ1_hw >> 32); x_UQ0_hw = (df_rep_t)x_UQ0_hw * corr >> 31; }
  { df_half_rep_t corr = 0 - ((df_rep_t)x_UQ0_hw * b_UQ1_hw >> 32); x_UQ0_hw = (df_rep_t)x_UQ0_hw * corr >> 31; }
  { df_half_rep_t corr = 0 - ((df_rep_t)x_UQ0_hw * b_UQ1_hw >> 32); x_UQ0_hw = (df_rep_t)x_UQ0_hw * corr >> 31; }
  x_UQ0_hw -= 1U;
  df_rep_t x_UQ0 = (df_rep_t)x_UQ0_hw << 32;
  x_UQ0 -= 1U;

  // 1 full-width iteration
  df_rep_t blo = b_UQ1 & 0xFFFFFFFFU;
  df_rep_t corr_UQ1 = 0U - ((df_rep_t)x_UQ0_hw * b_UQ1_hw + ((df_rep_t)x_UQ0_hw * blo >> 32) - DF_REP_C(1));
  df_rep_t lo_corr = corr_UQ1 & 0xFFFFFFFFU;
  df_rep_t hi_corr = corr_UQ1 >> 32;
  x_UQ0 = ((df_rep_t)x_UQ0_hw * hi_corr << 1) + ((df_rep_t)x_UQ0_hw * lo_corr >> 31) - DF_REP_C(2);
  x_UQ0 -= 1U;
  x_UQ0 -= 2U;
  x_UQ0 -= DF_REP_C(220);

  df_rep_t quotient_UQ1, dummy;
  df_wideMultiply(x_UQ0, aSignificand << 1, &quotient_UQ1, &dummy);

  df_rep_t residualLo;
  if (quotient_UQ1 < (df_implicitBit << 1)) {
    if (quotient_UQ1 < df_implicitBit) { quotient_UQ1 <<= 1; writtenExponent -= 1; }
    residualLo = (aSignificand << (df_significandBits + 1)) - quotient_UQ1 * bSignificand;
    writtenExponent -= 1;
    aSignificand <<= 1;
  } else {
    quotient_UQ1 >>= 1;
    residualLo = (aSignificand << df_significandBits) - quotient_UQ1 * bSignificand;
  }

  if (writtenExponent >= df_maxExponent) return df_fromRep(df_infRep | quotientSign);

  df_rep_t absResult;
  if (writtenExponent > 0) {
    absResult = quotient_UQ1 & df_significandMask;
    absResult |= (df_rep_t)writtenExponent << df_significandBits;
    residualLo <<= 1;
  } else {
    if (df_significandBits + writtenExponent < 0) return df_fromRep(quotientSign);
    absResult = quotient_UQ1 >> (-writtenExponent + 1);
    residualLo = (aSignificand << (df_significandBits + writtenExponent)) - (absResult * bSignificand << 1);
  }

  residualLo += absResult & 1;
  absResult += residualLo > bSignificand;
  return df_fromRep(absResult | quotientSign);
}

// ============================================================================
// Double-precision comparisons
// ============================================================================

COMPILER_RT_ABI CMP_RESULT __ledf2(double a, double b) {
  const df_srep_t aInt = df_toRep(a);
  const df_srep_t bInt = df_toRep(b);
  const df_rep_t aAbs = aInt & df_absMask;
  const df_rep_t bAbs = bInt & df_absMask;
  if (aAbs > df_infRep || bAbs > df_infRep) return 1;
  if ((aAbs | bAbs) == 0) return 0;
  if ((aInt & bInt) >= 0) { if (aInt < bInt) return -1; else if (aInt == bInt) return 0; else return 1; }
  else { if (aInt > bInt) return -1; else if (aInt == bInt) return 0; else return 1; }
}

COMPILER_RT_ABI CMP_RESULT __gedf2(double a, double b) {
  const df_srep_t aInt = df_toRep(a);
  const df_srep_t bInt = df_toRep(b);
  const df_rep_t aAbs = aInt & df_absMask;
  const df_rep_t bAbs = bInt & df_absMask;
  if (aAbs > df_infRep || bAbs > df_infRep) return -1;
  if ((aAbs | bAbs) == 0) return 0;
  if ((aInt & bInt) >= 0) { if (aInt < bInt) return -1; else if (aInt == bInt) return 0; else return 1; }
  else { if (aInt > bInt) return -1; else if (aInt == bInt) return 0; else return 1; }
}

COMPILER_RT_ABI CMP_RESULT __eqdf2(double a, double b) { return __ledf2(a, b); }
COMPILER_RT_ABI CMP_RESULT __ltdf2(double a, double b) { return __ledf2(a, b); }
COMPILER_RT_ABI CMP_RESULT __nedf2(double a, double b) { return __ledf2(a, b); }
COMPILER_RT_ABI CMP_RESULT __gtdf2(double a, double b) { return __gedf2(a, b); }
COMPILER_RT_ABI CMP_RESULT __unorddf2(double a, double b) {
  return (df_toRep(a) & df_absMask) > df_infRep || (df_toRep(b) & df_absMask) > df_infRep;
}

// ============================================================================
// Double to int conversions
// ============================================================================

COMPILER_RT_ABI si_int __fixdfsi(double a) {
  const df_rep_t aRep = df_toRep(a);
  const df_rep_t aAbs = aRep & df_absMask;
  const si_int sign = aRep & df_signBit ? -1 : 1;
  const int exponent = (aAbs >> df_significandBits) - df_exponentBias;
  const df_rep_t significand = (aAbs & df_significandMask) | df_implicitBit;
  if (exponent < 0) return 0;
  if ((unsigned)exponent >= 31) return sign == 1 ? 0x7FFFFFFF : (si_int)0x80000000;
  if (exponent < df_significandBits) return (si_int)(sign * (significand >> (df_significandBits - exponent)));
  return (si_int)(sign * ((su_int)significand << (exponent - df_significandBits)));
}

COMPILER_RT_ABI di_int __fixdfdi(double a) {
  const df_rep_t aRep = df_toRep(a);
  const df_rep_t aAbs = aRep & df_absMask;
  const di_int sign = aRep & df_signBit ? -1 : 1;
  const int exponent = (aAbs >> df_significandBits) - df_exponentBias;
  const df_rep_t significand = (aAbs & df_significandMask) | df_implicitBit;
  if (exponent < 0) return 0;
  if ((unsigned)exponent >= 63) return sign == 1 ? 0x7FFFFFFFFFFFFFFFLL : (di_int)0x8000000000000000LL;
  if (exponent < df_significandBits) return (di_int)(sign * (significand >> (df_significandBits - exponent)));
  return (di_int)(sign * ((du_int)significand << (exponent - df_significandBits)));
}

COMPILER_RT_ABI su_int __fixunsdfsi(double a) {
  const df_rep_t aRep = df_toRep(a);
  const df_rep_t aAbs = aRep & df_absMask;
  if (aRep & df_signBit) return 0;
  const int exponent = (aAbs >> df_significandBits) - df_exponentBias;
  const df_rep_t significand = (aAbs & df_significandMask) | df_implicitBit;
  if (exponent < 0) return 0;
  if ((unsigned)exponent >= 32) return ~(su_int)0;
  if (exponent < df_significandBits) return significand >> (df_significandBits - exponent);
  return (su_int)significand << (exponent - df_significandBits);
}

COMPILER_RT_ABI du_int __fixunsdfdi(double a) {
  const df_rep_t aRep = df_toRep(a);
  const df_rep_t aAbs = aRep & df_absMask;
  if (aRep & df_signBit) return 0;
  const int exponent = (aAbs >> df_significandBits) - df_exponentBias;
  const df_rep_t significand = (aAbs & df_significandMask) | df_implicitBit;
  if (exponent < 0) return 0;
  if ((unsigned)exponent >= 64) return ~(du_int)0;
  if (exponent < df_significandBits) return significand >> (df_significandBits - exponent);
  return (du_int)significand << (exponent - df_significandBits);
}

// ============================================================================
// Int to double conversions
// ============================================================================

COMPILER_RT_ABI double __floatsidf(si_int a) {
  if (a == 0) return df_fromRep(0);
  const df_rep_t sign = a < 0 ? df_signBit : 0;
  du_int aAbs = a < 0 ? -(su_int)a : (su_int)a;
  int e = 31 - __clzsi2(aAbs);
  df_rep_t result = (df_rep_t)aAbs << (df_significandBits - e);
  result &= df_significandMask;
  result |= (df_rep_t)(e + df_exponentBias) << df_significandBits;
  result |= sign;
  return df_fromRep(result);
}

COMPILER_RT_ABI double __floatunsidf(su_int a) {
  if (a == 0) return df_fromRep(0);
  int e = 31 - __clzsi2(a);
  df_rep_t result = (df_rep_t)a << (df_significandBits - e);
  result &= df_significandMask;
  result |= (df_rep_t)(e + df_exponentBias) << df_significandBits;
  return df_fromRep(result);
}

COMPILER_RT_ABI double __floatdidf(di_int a) {
  if (a == 0) return df_fromRep(0);
  const df_rep_t sign = a < 0 ? df_signBit : 0;
  du_int aAbs = a < 0 ? -(du_int)a : (du_int)a;
  int e = 63 - __builtin_clzll(aAbs);
  df_rep_t result;
  if (e <= df_significandBits) {
    result = aAbs << (df_significandBits - e);
  } else {
    int shift = e - df_significandBits;
    result = aAbs >> shift;
    du_int round = (aAbs >> (shift - 1)) & 1;
    du_int sticky = (aAbs & ((1ULL << (shift - 1)) - 1)) != 0;
    if (round && (sticky || (result & 1))) result++;
  }
  result &= df_significandMask;
  result |= (df_rep_t)(e + df_exponentBias) << df_significandBits;
  result |= sign;
  return df_fromRep(result);
}

COMPILER_RT_ABI double __floatundidf(du_int a) {
  if (a == 0) return df_fromRep(0);
  int e = 63 - __builtin_clzll(a);
  df_rep_t result;
  if (e <= df_significandBits) {
    result = a << (df_significandBits - e);
  } else {
    int shift = e - df_significandBits;
    result = a >> shift;
    du_int round = (a >> (shift - 1)) & 1;
    du_int sticky = (a & ((1ULL << (shift - 1)) - 1)) != 0;
    if (round && (sticky || (result & 1))) result++;
  }
  result &= df_significandMask;
  result |= (df_rep_t)(e + df_exponentBias) << df_significandBits;
  return df_fromRep(result);
}

// ============================================================================
// Precision conversions: float <-> double
// ============================================================================

// float -> double (extend)
COMPILER_RT_ABI double __extendsfdf2(float a) {
  const uint32_t aRep = toRep(a);
  const uint32_t aAbs = aRep & 0x7FFFFFFF;
  const uint32_t sign = aRep & 0x80000000;
  const int srcExp = (aAbs >> 23) & 0xFF;
  const uint32_t srcSig = aAbs & 0x7FFFFF;

  df_rep_t dstSign = (df_rep_t)sign << 32;
  df_rep_t dstExp;
  df_rep_t dstSig;

  if (srcExp >= 1 && srcExp < 255) {
    // Normal number
    dstExp = (df_rep_t)srcExp + (1023 - 127);
    dstSig = (df_rep_t)srcSig << (52 - 23);
  } else if (srcExp == 255) {
    // Inf or NaN
    dstExp = 2047;
    dstSig = (df_rep_t)srcSig << (52 - 23);
  } else if (srcSig) {
    // Denormal - normalize
    int shift = __clzsi2(srcSig) - 8;
    dstExp = (1023 - 127) - shift;
    dstSig = ((df_rep_t)srcSig << (shift + 52 - 23 + 1)) & df_significandMask;
  } else {
    // Zero
    dstExp = 0;
    dstSig = 0;
  }

  return df_fromRep(dstSign | (dstExp << 52) | dstSig);
}

// double -> float (truncate)
COMPILER_RT_ABI float __truncdfsf2(double a) {
  const df_rep_t aRep = df_toRep(a);
  const df_rep_t aAbs = aRep & df_absMask;
  const df_rep_t sign = aRep & df_signBit;
  const int srcExp = (aAbs >> 52) & 0x7FF;
  const df_rep_t srcSig = aAbs & df_significandMask;

  uint32_t dstSign = (uint32_t)(sign >> 32);
  uint32_t dstExp;
  uint32_t dstSig;

  const int dstExpCandidate = srcExp - 1023 + 127;

  if (dstExpCandidate >= 1 && dstExpCandidate < 255) {
    // Normal result
    dstExp = dstExpCandidate;
    dstSig = (uint32_t)(srcSig >> (52 - 23));
    df_rep_t roundBits = srcSig & ((DF_REP_C(1) << (52 - 23)) - 1);
    df_rep_t halfway = DF_REP_C(1) << (52 - 23 - 1);
    if (roundBits > halfway) dstSig++;
    else if (roundBits == halfway) dstSig += dstSig & 1;
    if (dstSig >= (1U << 23)) { dstExp++; dstSig &= 0x7FFFFF; }
  } else if (srcExp == 2047 && srcSig) {
    // NaN
    dstExp = 255;
    dstSig = (1U << 22) | ((uint32_t)(srcSig >> (52 - 23)) & 0x3FFFFF);
  } else if (srcExp >= 1023 + 128) {
    // Overflow to infinity
    dstExp = 255;
    dstSig = 0;
  } else {
    // Underflow to zero or denormal
    dstExp = 0;
    dstSig = 0;
  }

  return fromRep(dstSign | (dstExp << 23) | dstSig);
}

// ============================================================================
// Power-of-integer: __powisf2, __powidf2
// ============================================================================
// Returns: a ^ b (float/double raised to integer power)

// Forward declarations
COMPILER_RT_ABI float __powisf2(float a, int b);
COMPILER_RT_ABI double __powidf2(double a, int b);

COMPILER_RT_ABI float __powisf2(float a, int b) {
  const int recip = b < 0;
  float r = 1;
  while (1) {
    if (b & 1)
      r *= a;
    b /= 2;
    if (b == 0)
      break;
    a *= a;
  }
  return recip ? 1 / r : r;
}

COMPILER_RT_ABI double __powidf2(double a, int b) {
  const int recip = b < 0;
  double r = 1;
  while (1) {
    if (b & 1)
      r *= a;
    b /= 2;
    if (b == 0)
      break;
    a *= a;
  }
  return recip ? 1 / r : r;
}

// ============================================================================
// COMPLEX NUMBER ARITHMETIC
// ============================================================================
//
// Provides: __mulsc3, __divsc3 (single-precision complex)
//           __muldc3, __divdc3 (double-precision complex)
//
// These implement C99 _Complex multiplication and division.
// ============================================================================

// Complex type definitions using C99 _Complex
typedef float _Complex Fcomplex;
typedef double _Complex Dcomplex;

#define COMPLEX_REAL(x) __real__(x)
#define COMPLEX_IMAGINARY(x) __imag__(x)

// Forward declarations
COMPILER_RT_ABI Fcomplex __mulsc3(float a, float b, float c, float d);
COMPILER_RT_ABI Fcomplex __divsc3(float a, float b, float c, float d);
COMPILER_RT_ABI Dcomplex __muldc3(double a, double b, double c, double d);
COMPILER_RT_ABI Dcomplex __divdc3(double a, double b, double c, double d);

// ============================================================================
// Single-precision complex multiplication: __mulsc3
// Returns: (a + bi) * (c + di)
// ============================================================================

COMPILER_RT_ABI Fcomplex __mulsc3(float __a, float __b, float __c, float __d) {
  float __ac = __a * __c;
  float __bd = __b * __d;
  float __ad = __a * __d;
  float __bc = __b * __c;
  Fcomplex z;
  COMPLEX_REAL(z) = __ac - __bd;
  COMPLEX_IMAGINARY(z) = __ad + __bc;
  
  if (crt_isnan(COMPLEX_REAL(z)) && crt_isnan(COMPLEX_IMAGINARY(z))) {
    int __recalc = 0;
    if (crt_isinf(__a) || crt_isinf(__b)) {
      // (inf + i inf) * (c + i d)
      __a = crt_copysignf(crt_isinf(__a) ? 1.0f : 0.0f, __a);
      __b = crt_copysignf(crt_isinf(__b) ? 1.0f : 0.0f, __b);
      if (crt_isnan(__c))
        __c = crt_copysignf(0.0f, __c);
      if (crt_isnan(__d))
        __d = crt_copysignf(0.0f, __d);
      __recalc = 1;
    }
    if (crt_isinf(__c) || crt_isinf(__d)) {
      // (a + i b) * (inf + i inf)
      __c = crt_copysignf(crt_isinf(__c) ? 1.0f : 0.0f, __c);
      __d = crt_copysignf(crt_isinf(__d) ? 1.0f : 0.0f, __d);
      if (crt_isnan(__a))
        __a = crt_copysignf(0.0f, __a);
      if (crt_isnan(__b))
        __b = crt_copysignf(0.0f, __b);
      __recalc = 1;
    }
    if (!__recalc && (crt_isinf(__ac) || crt_isinf(__bd) ||
                      crt_isinf(__ad) || crt_isinf(__bc))) {
      // Recover infinities from overflow
      if (crt_isnan(__a))
        __a = crt_copysignf(0.0f, __a);
      if (crt_isnan(__b))
        __b = crt_copysignf(0.0f, __b);
      if (crt_isnan(__c))
        __c = crt_copysignf(0.0f, __c);
      if (crt_isnan(__d))
        __d = crt_copysignf(0.0f, __d);
      __recalc = 1;
    }
    if (__recalc) {
      COMPLEX_REAL(z) = CRT_INFINITY * (__a * __c - __b * __d);
      COMPLEX_IMAGINARY(z) = CRT_INFINITY * (__a * __d + __b * __c);
    }
  }
  return z;
}

// ============================================================================
// Single-precision complex division: __divsc3
// Returns: (a + bi) / (c + di)
// 
// Uses Smith's algorithm for numerical stability:
// if |d| <= |c|:
//   r = d/c, denom = c + d*r
//   real = (a + b*r) / denom, imag = (b - a*r) / denom
// else:
//   r = c/d, denom = d + c*r
//   real = (a*r + b) / denom, imag = (b*r - a) / denom
// ============================================================================

COMPILER_RT_ABI Fcomplex __divsc3(float __a, float __b, float __c, float __d) {
  float __abs_c = crt_fabsf(__c);
  float __abs_d = crt_fabsf(__d);
  Fcomplex z;
  
  if (__abs_d <= __abs_c) {
    // |d| <= |c|: use r = d/c
    if (__abs_c == 0.0f) {
      // Division by zero
      COMPLEX_REAL(z) = __a / __abs_c;  // Will produce inf or nan
      COMPLEX_IMAGINARY(z) = __b / __abs_c;
    } else {
      float __r = __d / __c;
      float __denom = __c + __d * __r;
      COMPLEX_REAL(z) = (__a + __b * __r) / __denom;
      COMPLEX_IMAGINARY(z) = (__b - __a * __r) / __denom;
    }
  } else {
    // |d| > |c|: use r = c/d
    float __r = __c / __d;
    float __denom = __d + __c * __r;
    COMPLEX_REAL(z) = (__a * __r + __b) / __denom;
    COMPLEX_IMAGINARY(z) = (__b * __r - __a) / __denom;
  }
  
  // Handle special cases (inf/nan)
  if (crt_isnan(COMPLEX_REAL(z)) && crt_isnan(COMPLEX_IMAGINARY(z))) {
    float __denom = __c * __c + __d * __d;
    if (__denom == 0.0f && (!crt_isnan(__a) || !crt_isnan(__b))) {
      // (finite) / 0 -> inf
      COMPLEX_REAL(z) = crt_copysignf(CRT_INFINITY, __c) * __a;
      COMPLEX_IMAGINARY(z) = crt_copysignf(CRT_INFINITY, __c) * __b;
    } else if ((crt_isinf(__a) || crt_isinf(__b)) &&
               crt_isfinite(__c) && crt_isfinite(__d)) {
      // (inf) / (finite) -> inf
      __a = crt_copysignf(crt_isinf(__a) ? 1.0f : 0.0f, __a);
      __b = crt_copysignf(crt_isinf(__b) ? 1.0f : 0.0f, __b);
      COMPLEX_REAL(z) = CRT_INFINITY * (__a * __c + __b * __d);
      COMPLEX_IMAGINARY(z) = CRT_INFINITY * (__b * __c - __a * __d);
    } else if ((crt_isinf(__c) || crt_isinf(__d)) &&
               crt_isfinite(__a) && crt_isfinite(__b)) {
      // (finite) / (inf) -> 0
      __c = crt_copysignf(crt_isinf(__c) ? 1.0f : 0.0f, __c);
      __d = crt_copysignf(crt_isinf(__d) ? 1.0f : 0.0f, __d);
      COMPLEX_REAL(z) = 0.0f * (__a * __c + __b * __d);
      COMPLEX_IMAGINARY(z) = 0.0f * (__b * __c - __a * __d);
    }
  }
  return z;
}

// ============================================================================
// Double-precision complex multiplication: __muldc3
// Returns: (a + bi) * (c + di)
// ============================================================================

COMPILER_RT_ABI Dcomplex __muldc3(double __a, double __b, double __c, double __d) {
  double __ac = __a * __c;
  double __bd = __b * __d;
  double __ad = __a * __d;
  double __bc = __b * __c;
  Dcomplex z;
  COMPLEX_REAL(z) = __ac - __bd;
  COMPLEX_IMAGINARY(z) = __ad + __bc;
  
  if (crt_isnan(COMPLEX_REAL(z)) && crt_isnan(COMPLEX_IMAGINARY(z))) {
    int __recalc = 0;
    if (crt_isinf(__a) || crt_isinf(__b)) {
      __a = crt_copysign(crt_isinf(__a) ? 1.0 : 0.0, __a);
      __b = crt_copysign(crt_isinf(__b) ? 1.0 : 0.0, __b);
      if (crt_isnan(__c))
        __c = crt_copysign(0.0, __c);
      if (crt_isnan(__d))
        __d = crt_copysign(0.0, __d);
      __recalc = 1;
    }
    if (crt_isinf(__c) || crt_isinf(__d)) {
      __c = crt_copysign(crt_isinf(__c) ? 1.0 : 0.0, __c);
      __d = crt_copysign(crt_isinf(__d) ? 1.0 : 0.0, __d);
      if (crt_isnan(__a))
        __a = crt_copysign(0.0, __a);
      if (crt_isnan(__b))
        __b = crt_copysign(0.0, __b);
      __recalc = 1;
    }
    if (!__recalc && (crt_isinf(__ac) || crt_isinf(__bd) ||
                      crt_isinf(__ad) || crt_isinf(__bc))) {
      if (crt_isnan(__a))
        __a = crt_copysign(0.0, __a);
      if (crt_isnan(__b))
        __b = crt_copysign(0.0, __b);
      if (crt_isnan(__c))
        __c = crt_copysign(0.0, __c);
      if (crt_isnan(__d))
        __d = crt_copysign(0.0, __d);
      __recalc = 1;
    }
    if (__recalc) {
      COMPLEX_REAL(z) = CRT_INFINITY * (__a * __c - __b * __d);
      COMPLEX_IMAGINARY(z) = CRT_INFINITY * (__a * __d + __b * __c);
    }
  }
  return z;
}

// ============================================================================
// Double-precision complex division: __divdc3
// Returns: (a + bi) / (c + di)
// Uses Smith's algorithm for numerical stability.
// ============================================================================

COMPILER_RT_ABI Dcomplex __divdc3(double __a, double __b, double __c, double __d) {
  double __abs_c = crt_fabs(__c);
  double __abs_d = crt_fabs(__d);
  Dcomplex z;
  
  if (__abs_d <= __abs_c) {
    if (__abs_c == 0.0) {
      COMPLEX_REAL(z) = __a / __abs_c;
      COMPLEX_IMAGINARY(z) = __b / __abs_c;
    } else {
      double __r = __d / __c;
      double __denom = __c + __d * __r;
      COMPLEX_REAL(z) = (__a + __b * __r) / __denom;
      COMPLEX_IMAGINARY(z) = (__b - __a * __r) / __denom;
    }
  } else {
    double __r = __c / __d;
    double __denom = __d + __c * __r;
    COMPLEX_REAL(z) = (__a * __r + __b) / __denom;
    COMPLEX_IMAGINARY(z) = (__b * __r - __a) / __denom;
  }
  
  if (crt_isnan(COMPLEX_REAL(z)) && crt_isnan(COMPLEX_IMAGINARY(z))) {
    double __denom = __c * __c + __d * __d;
    if (__denom == 0.0 && (!crt_isnan(__a) || !crt_isnan(__b))) {
      COMPLEX_REAL(z) = crt_copysign(CRT_INFINITY, __c) * __a;
      COMPLEX_IMAGINARY(z) = crt_copysign(CRT_INFINITY, __c) * __b;
    } else if ((crt_isinf(__a) || crt_isinf(__b)) &&
               crt_isfinite(__c) && crt_isfinite(__d)) {
      __a = crt_copysign(crt_isinf(__a) ? 1.0 : 0.0, __a);
      __b = crt_copysign(crt_isinf(__b) ? 1.0 : 0.0, __b);
      COMPLEX_REAL(z) = CRT_INFINITY * (__a * __c + __b * __d);
      COMPLEX_IMAGINARY(z) = CRT_INFINITY * (__b * __c - __a * __d);
    } else if ((crt_isinf(__c) || crt_isinf(__d)) &&
               crt_isfinite(__a) && crt_isfinite(__b)) {
      __c = crt_copysign(crt_isinf(__c) ? 1.0 : 0.0, __c);
      __d = crt_copysign(crt_isinf(__d) ? 1.0 : 0.0, __d);
      COMPLEX_REAL(z) = 0.0 * (__a * __c + __b * __d);
      COMPLEX_IMAGINARY(z) = 0.0 * (__b * __c - __a * __d);
    }
  }
  return z;
}
