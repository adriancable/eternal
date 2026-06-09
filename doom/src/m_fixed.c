// Emacs style mode select   -*- C++ -*- 
//-----------------------------------------------------------------------------
//
// $Id:$
//
// Copyright (C) 1993-1996 by id Software, Inc.
//
// This source is available for distribution and/or modification
// only under the terms of the DOOM Source Code License as
// published by id Software. All rights reserved.
//
// The source is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// FITNESS FOR A PARTICULAR PURPOSE. See the DOOM Source Code License
// for more details.
//
// $Log:$
//
// DESCRIPTION:
//	Fixed point implementation.
//
//-----------------------------------------------------------------------------


static const char
rcsid[] = "$Id: m_bbox.c,v 1.1 1997/02/03 22:45:10 b1 Exp $";

#include "stdlib.h"

#include "doomtype.h"
#include "i_system.h"

#ifdef __GNUG__
#pragma implementation "m_fixed.h"
#endif
#include "m_fixed.h"




// FixedMul uses 64-bit multiply + shift. This calls __subleq_mul and
// __lshrdi3, which are expensive on Subleq but required for correctness.
// The (a>>8)*(b>>8) optimization was attempted but breaks rendering because
// it zeroes out any operand smaller than 256, destroying sub-pixel precision.

#ifndef USE_ASM_FIXED
fixed_t
FixedMul
( fixed_t	a,
  fixed_t	b )
{
    return ((long long) a * (long long) b) >> FRACBITS;
}
#endif



//
// FixedDiv, C version.
//

fixed_t
FixedDiv
( fixed_t	a,
  fixed_t	b )
{
    if ( (abs(a)>>14) >= abs(b))
	return (a < 0) != (b < 0) ? MININT : MAXINT;
    return FixedDiv2 (a,b);
}



// Subleq optimization: integer-only fixed-point division.
// Computes (a << 16) / b using only 32-bit operations.
// Eliminates __divdf3 (1.75% of profile) entirely.

#ifndef USE_ASM_FIXED
fixed_t
FixedDiv2
( fixed_t	a,
  fixed_t	b )
{
    int neg = 0;
    unsigned ua, ub, q, r, frac;
    int i;

    if (a < 0) { neg = !neg; ua = (unsigned)(-a); } else { ua = (unsigned)a; }
    if (b < 0) { neg = !neg; ub = (unsigned)(-b); } else { ub = (unsigned)b; }

    q = ua / ub;
    r = ua - q * ub;

    // 16-step restoring division for the fractional part.
    // Extremely fast on Subleq because:
    // 1. All variables are 32-bit unsigned integer.
    // 2. Both << 1 operations are implemented as Add (x + x).
    // 3. r + r cannot overflow a 32-bit uint because r < ub <= 2^31.
    frac = 0;
    for (i = 0; i < 16; i++) {
        r += r;
        frac += frac;
        if (r >= ub) {
            r -= ub;
            frac |= 1;
        }
    }

    {
	fixed_t result = (fixed_t)((q << 16) | frac);
	return neg ? -result : result;
    }
}
#endif
