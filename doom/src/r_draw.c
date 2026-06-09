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
//	The actual span/column drawing functions.
//	Here find the main potential for optimization,
//	 e.g. inline assembly, different algorithms.
//
//-----------------------------------------------------------------------------


static const char
rcsid[] = "$Id: r_draw.c,v 1.4 1997/02/03 16:47:55 b1 Exp $";


#include "doomdef.h"

#include "i_system.h"
#include "z_zone.h"
#include "w_wad.h"

#include "r_local.h"

// Needs access to LFB (guess what).
#include "v_video.h"

// State.
#include "doomstat.h"


// ?
#define MAXWIDTH			1120
#define MAXHEIGHT			832

// status bar height at bottom of screen
#define SBARHEIGHT		32

//
// All drawing to the view buffer is accomplished in this file.
// The other refresh files only know about ccordinates,
//  not the architecture of the frame buffer.
// Conveniently, the frame buffer is a linear one,
//  and we need only the base address,
//  and the total size == width*height*depth/8.,
//


byte*		viewimage; 
int		viewwidth;
int		scaledviewwidth;
int		viewheight;
int		viewwindowx;
int		viewwindowy; 
uint32_t*		ylookup[MAXHEIGHT]; 
int		columnofs[MAXWIDTH]; 

// Color tables for different players,
//  translate a limited part to another
//  (color ramps used for  suit colors).
//
byte		translations[3][256];	
 
 


//
// R_DrawColumn
// Source is the top of the column to scale.
//
lighttable_t*		dc_colormap; 
int			dc_x; 
int			dc_yl; 
int			dc_yh; 
fixed_t			dc_iscale; 
fixed_t			dc_texturemid;

// first pixel in a column (possibly virtual) 
uint32_t*			dc_source;

// Static buffer for widening byte column data to uint32_t.
// Max texture height is 128 pixels, but allocate 256 for safety.
static uint32_t			dc_source_buf[256];

// Widen byte column data to uint32_t and set dc_source.
void R_SetColumnSource(const byte* src, int count)
{
    int i;
    for (i = 0; i < count; i++)
        dc_source_buf[i] = src[i];
    // Zero-fill remainder up to 128 so R_DrawColumn's tex_y
    // mod-128 wrap never reads stale garbage as a color index.
    for ( ; i < 128; i++)
        dc_source_buf[i] = 0;
    dc_source = dc_source_buf;
}

// just for profiling 
int			dccount;

//
// A column is a vertical slice/span from a wall texture that,
//  given the DOOM style restrictions on the view orientation,
//  will always have constant z depth.
// Thus a special case loop for very fast rendering can
//  be used. It has also been used with Wolfenstein 3D.
// 
#if !defined(USE_ASM_RDRAW) && !defined(USE_ASM_RDRAW_COL)
void R_DrawColumn (void) 
{ 
    int			count; 
    uint32_t*		dest; 
    fixed_t		frac;
    fixed_t		fracstep;	 
 
    count = dc_yh - dc_yl; 

    // Zero length, column does not exceed a pixel.
    if (count < 0) 
	return; 
				 
#ifdef RANGECHECK 
    if ((unsigned)dc_x >= SCREENWIDTH
	|| dc_yl < 0
	|| dc_yh >= SCREENHEIGHT) 
	I_Error ("R_DrawColumn: %i to %i at %i", dc_yl, dc_yh, dc_x); 
#endif 

    // Framebuffer destination address.
    // Use ylookup LUT to avoid multiply with ScreenWidth.
    // Use columnofs LUT for subwindows? 
    dest = ylookup[dc_yl] + columnofs[dc_x];  

    // Determine scaling,
    //  which is the only mapping to be done.
    fracstep = dc_iscale; 
    frac = dc_texturemid + (dc_yl-centery)*fracstep; 

    // Subleq optimization: split fixed-point into integer and
    // fractional accumulators. Eliminates per-pixel >>16 and &127,
    // replacing them with cheap additions/comparisons.
    {
	int tex_y = frac >> FRACBITS;
	int frac_lo = (int)(frac & 0xFFFF) - 0xFFFF;
	int step_int = fracstep >> FRACBITS;
	int step_lo = fracstep & 0xFFFF;

	// Pre-normalize step_int to [0,127] so inner loop
	// wrap needs at most one subtraction.
	while (step_int >= 128) step_int -= 128;

	// Normalize tex_y to [0,127] (one-time).
	while (tex_y < 0) tex_y += 128;
	while (tex_y >= 128) tex_y -= 128;

	// Loop unrolled 4x.
	while (count >= 3)
	{
	    *dest = dc_colormap[dc_source[tex_y]]; dest += SCREENWIDTH;
	    frac_lo += step_lo;
	    if (frac_lo > 0) { frac_lo -= 0x10000; tex_y++; }
	    tex_y += step_int; if (tex_y >= 128) tex_y -= 128;

	    *dest = dc_colormap[dc_source[tex_y]]; dest += SCREENWIDTH;
	    frac_lo += step_lo;
	    if (frac_lo > 0) { frac_lo -= 0x10000; tex_y++; }
	    tex_y += step_int; if (tex_y >= 128) tex_y -= 128;

	    *dest = dc_colormap[dc_source[tex_y]]; dest += SCREENWIDTH;
	    frac_lo += step_lo;
	    if (frac_lo > 0) { frac_lo -= 0x10000; tex_y++; }
	    tex_y += step_int; if (tex_y >= 128) tex_y -= 128;

	    *dest = dc_colormap[dc_source[tex_y]]; dest += SCREENWIDTH;
	    frac_lo += step_lo;
	    if (frac_lo > 0) { frac_lo -= 0x10000; tex_y++; }
	    tex_y += step_int; if (tex_y >= 128) tex_y -= 128;

	    count -= 4;
	}
	while (count >= 0)
	{
	    *dest = dc_colormap[dc_source[tex_y]]; dest += SCREENWIDTH;
	    frac_lo += step_lo;
	    if (frac_lo > 0) { frac_lo -= 0x10000; tex_y++; }
	    tex_y += step_int; if (tex_y >= 128) tex_y -= 128;
	    count--;
	}
    }
} 
#endif /* USE_ASM_RDRAW_COL */




// UNUSED.
// Loop unrolled.
#if 0
void R_DrawColumn (void) 
{ 
    int			count; 
    byte*		source;
    byte*		dest;
    byte*		colormap;
    
    unsigned		frac;
    unsigned		fracstep;
    unsigned		fracstep2;
    unsigned		fracstep3;
    unsigned		fracstep4;	 
 
    count = dc_yh - dc_yl + 1; 

    source = dc_source;
    colormap = dc_colormap;		 
    dest = ylookup[dc_yl] + columnofs[dc_x];  
	 
    fracstep = dc_iscale<<9; 
    frac = (dc_texturemid + (dc_yl-centery)*dc_iscale)<<9; 
 
    fracstep2 = fracstep+fracstep;
    fracstep3 = fracstep2+fracstep;
    fracstep4 = fracstep3+fracstep;
	
    while (count >= 8) 
    { 
	dest[0] = colormap[source[frac>>25]]; 
	dest[SCREENWIDTH] = colormap[source[(frac+fracstep)>>25]]; 
	dest[SCREENWIDTH*2] = colormap[source[(frac+fracstep2)>>25]]; 
	dest[SCREENWIDTH*3] = colormap[source[(frac+fracstep3)>>25]];
	
	frac += fracstep4; 

	dest[SCREENWIDTH*4] = colormap[source[frac>>25]]; 
	dest[SCREENWIDTH*5] = colormap[source[(frac+fracstep)>>25]]; 
	dest[SCREENWIDTH*6] = colormap[source[(frac+fracstep2)>>25]]; 
	dest[SCREENWIDTH*7] = colormap[source[(frac+fracstep3)>>25]]; 

	frac += fracstep4; 
	dest += SCREENWIDTH*8; 
	count -= 8;
    } 
	
    while (count > 0)
    { 
	*dest = colormap[source[frac>>25]]; 
	dest += SCREENWIDTH; 
	frac += fracstep; 
	count--;
    } 
}
#endif


void R_DrawColumnLow (void) 
{ 
    int			count; 
    uint32_t*		dest; 
    uint32_t*		dest2;
    fixed_t		frac;
    fixed_t		fracstep;	 
 
    count = dc_yh - dc_yl; 

    // Zero length.
    if (count < 0) 
	return; 
				 
#ifdef RANGECHECK 
    if ((unsigned)dc_x >= SCREENWIDTH
	|| dc_yl < 0
	|| dc_yh >= SCREENHEIGHT)
    {
	
	I_Error ("R_DrawColumn: %i to %i at %i", dc_yl, dc_yh, dc_x);
    }
    //	dccount++; 
#endif 
    // Blocky mode, need to multiply by 2.
    dc_x <<= 1;
    
    dest = ylookup[dc_yl] + columnofs[dc_x];
    dest2 = ylookup[dc_yl] + columnofs[dc_x+1];
    
    fracstep = dc_iscale; 
    frac = dc_texturemid + (dc_yl-centery)*fracstep;
    
    // Subleq optimization: split accumulator (same as R_DrawColumn).
    {
	int tex_y = frac >> FRACBITS;
	int frac_lo = (int)(frac & 0xFFFF) - 0xFFFF;
	int step_int = fracstep >> FRACBITS;
	int step_lo = fracstep & 0xFFFF;

	while (step_int >= 128) step_int -= 128;
	while (tex_y < 0) tex_y += 128;
	while (tex_y >= 128) tex_y -= 128;

	while (count >= 3)
	{
	    *dest2 = *dest = dc_colormap[dc_source[tex_y]]; dest += SCREENWIDTH; dest2 += SCREENWIDTH;
	    frac_lo += step_lo; if (frac_lo > 0) { frac_lo -= 0x10000; tex_y++; }
	    tex_y += step_int; if (tex_y >= 128) tex_y -= 128;

	    *dest2 = *dest = dc_colormap[dc_source[tex_y]]; dest += SCREENWIDTH; dest2 += SCREENWIDTH;
	    frac_lo += step_lo; if (frac_lo > 0) { frac_lo -= 0x10000; tex_y++; }
	    tex_y += step_int; if (tex_y >= 128) tex_y -= 128;

	    *dest2 = *dest = dc_colormap[dc_source[tex_y]]; dest += SCREENWIDTH; dest2 += SCREENWIDTH;
	    frac_lo += step_lo; if (frac_lo > 0) { frac_lo -= 0x10000; tex_y++; }
	    tex_y += step_int; if (tex_y >= 128) tex_y -= 128;

	    *dest2 = *dest = dc_colormap[dc_source[tex_y]]; dest += SCREENWIDTH; dest2 += SCREENWIDTH;
	    frac_lo += step_lo; if (frac_lo > 0) { frac_lo -= 0x10000; tex_y++; }
	    tex_y += step_int; if (tex_y >= 128) tex_y -= 128;

	    count -= 4;
	}
	while (count >= 0)
	{
	    *dest2 = *dest = dc_colormap[dc_source[tex_y]]; dest += SCREENWIDTH; dest2 += SCREENWIDTH;
	    frac_lo += step_lo; if (frac_lo > 0) { frac_lo -= 0x10000; tex_y++; }
	    tex_y += step_int; if (tex_y >= 128) tex_y -= 128;
	    count--;
	}
    }
}


//
// Spectre/Invisibility.
//
#define FUZZTABLE		50 
#define FUZZOFF	(SCREENWIDTH)


int	fuzzoffset[FUZZTABLE] =
{
    FUZZOFF,-FUZZOFF,FUZZOFF,-FUZZOFF,FUZZOFF,FUZZOFF,-FUZZOFF,
    FUZZOFF,FUZZOFF,-FUZZOFF,FUZZOFF,FUZZOFF,FUZZOFF,-FUZZOFF,
    FUZZOFF,FUZZOFF,FUZZOFF,-FUZZOFF,-FUZZOFF,-FUZZOFF,-FUZZOFF,
    FUZZOFF,-FUZZOFF,-FUZZOFF,FUZZOFF,FUZZOFF,FUZZOFF,FUZZOFF,-FUZZOFF,
    FUZZOFF,-FUZZOFF,FUZZOFF,FUZZOFF,-FUZZOFF,-FUZZOFF,FUZZOFF,
    FUZZOFF,-FUZZOFF,-FUZZOFF,-FUZZOFF,-FUZZOFF,FUZZOFF,FUZZOFF,
    FUZZOFF,FUZZOFF,-FUZZOFF,FUZZOFF,FUZZOFF,-FUZZOFF,FUZZOFF 
}; 

int	fuzzpos = 0; 


//
// Framebuffer postprocessing.
// Creates a fuzzy image by copying pixels
//  from adjacent ones to left and right.
// Used with an all black colormap, this
//  could create the SHADOW effect,
//  i.e. spectres and invisible players.
//
void R_DrawFuzzColumn (void) 
{ 
    int			count; 
    uint32_t*		dest; 
    fixed_t		frac;
    fixed_t		fracstep;	 

    // Adjust borders. Low... 
    if (!dc_yl) 
	dc_yl = 1;

    // .. and high.
    if (dc_yh == viewheight-1) 
	dc_yh = viewheight - 2; 
		 
    count = dc_yh - dc_yl; 

    // Zero length.
    if (count < 0) 
	return; 

    
#ifdef RANGECHECK 
    if ((unsigned)dc_x >= SCREENWIDTH
	|| dc_yl < 0 || dc_yh >= SCREENHEIGHT)
    {
	I_Error ("R_DrawFuzzColumn: %i to %i at %i",
		 dc_yl, dc_yh, dc_x);
    }
#endif


    // Keep till detailshift bug in blocky mode fixed,
    //  or blocky mode removed.
    /* WATCOM code 
    if (detailshift)
    {
	if (dc_x & 1)
	{
	    outpw (GC_INDEX,GC_READMAP+(2<<8) ); 
	    outp (SC_INDEX+1,12); 
	}
	else
	{
	    outpw (GC_INDEX,GC_READMAP); 
	    outp (SC_INDEX+1,3); 
	}
	dest = destview + dc_yl*80 + (dc_x>>1); 
    }
    else
    {
	outpw (GC_INDEX,GC_READMAP+((dc_x&3)<<8) ); 
	outp (SC_INDEX+1,1<<(dc_x&3)); 
	dest = destview + dc_yl*80 + (dc_x>>2); 
    }*/

    
    // Does not work with blocky mode.
    dest = ylookup[dc_yl] + columnofs[dc_x];

    // Looks familiar.
    fracstep = dc_iscale; 
    frac = dc_texturemid + (dc_yl-centery)*fracstep; 

    // Pixels are XRGB values (not palette indices), so colormap lookup
    // is not possible. Apply ~6/32 dimming directly: 75% brightness.
    // Subleq optimization: decompose XRGB to R,G,B channels using
    // division by powers of 2 (→ srl shifts) and subtraction.
    // Avoids the expensive 0x003F3F3F AND mask from the original code.
    do 
    {
	uint32_t existing = dest[fuzzoffset[fuzzpos]];
	{
	    // Extract channels: /65536 → srl_16, /256 → srl_8
	    unsigned r = existing / 65536;          // R (bits 16-23)
	    unsigned g = (existing - r * 65536) / 256;  // G (bits 8-15)
	    unsigned b = existing - r * 65536 - g * 256; // B (bits 0-7)
	    // 75% brightness: subtract quarter via /4 (→ srl_2)
	    r = r - r / 4;
	    g = g - g / 4;
	    b = b - b / 4;
	    // Repack: r*65536 + g*256 + b
	    // *256 = 8 doublings (sll_8), *65536 = 16 doublings (sll_16)
	    // Optimize: (r*256 + g)*256 + b — two sll_8 instead of sll_16
	    *dest = (r * 256 + g) * 256 + b;
	}

	// Clamp table lookup index.
	if (++fuzzpos == FUZZTABLE) 
	    fuzzpos = 0;
	
	dest += SCREENWIDTH;

	frac += fracstep; 
    } while (count--); 
} 
 
  
 

//
// R_DrawTranslatedColumn
// Used to draw player sprites
//  with the green colorramp mapped to others.
// Could be used with different translation
//  tables, e.g. the lighter colored version
//  of the BaronOfHell, the HellKnight, uses
//  identical sprites, kinda brightened up.
//
uint32_t*	dc_translation;
uint32_t*	translationtables;

void R_DrawTranslatedColumn (void) 
{ 
    int			count; 
    uint32_t*		dest; 
    fixed_t		frac;
    fixed_t		fracstep;	 
 
    count = dc_yh - dc_yl; 
    if (count < 0) 
	return; 
				 
#ifdef RANGECHECK 
    if ((unsigned)dc_x >= SCREENWIDTH
	|| dc_yl < 0
	|| dc_yh >= SCREENHEIGHT)
    {
	I_Error ( "R_DrawColumn: %i to %i at %i",
		  dc_yl, dc_yh, dc_x);
    }
    
#endif 


    // WATCOM VGA specific.
    /* Keep for fixing.
    if (detailshift)
    {
	if (dc_x & 1)
	    outp (SC_INDEX+1,12); 
	else
	    outp (SC_INDEX+1,3);
	
	dest = destview + dc_yl*80 + (dc_x>>1); 
    }
    else
    {
	outp (SC_INDEX+1,1<<(dc_x&3)); 

	dest = destview + dc_yl*80 + (dc_x>>2); 
    }*/

    
    // FIXME. As above.
    dest = ylookup[dc_yl] + columnofs[dc_x]; 

    // Looks familiar.
    fracstep = dc_iscale; 
    frac = dc_texturemid + (dc_yl-centery)*fracstep; 

    // Subleq optimization: split accumulator (same as R_DrawColumn)
    // No wrapping needed for translated columns (sprite posts).
    {
	int tex_y = frac >> FRACBITS;
	int frac_lo = (int)(frac & 0xFFFF) - 0xFFFF;
	int step_int = fracstep >> FRACBITS;
	int step_lo = fracstep & 0xFFFF;

	while (count >= 3)
	{
	    *dest = dc_colormap[dc_translation[dc_source[tex_y]]]; dest += SCREENWIDTH;
	    frac_lo += step_lo; if (frac_lo > 0) { frac_lo -= 0x10000; tex_y++; }
	    tex_y += step_int;

	    *dest = dc_colormap[dc_translation[dc_source[tex_y]]]; dest += SCREENWIDTH;
	    frac_lo += step_lo; if (frac_lo > 0) { frac_lo -= 0x10000; tex_y++; }
	    tex_y += step_int;

	    *dest = dc_colormap[dc_translation[dc_source[tex_y]]]; dest += SCREENWIDTH;
	    frac_lo += step_lo; if (frac_lo > 0) { frac_lo -= 0x10000; tex_y++; }
	    tex_y += step_int;

	    *dest = dc_colormap[dc_translation[dc_source[tex_y]]]; dest += SCREENWIDTH;
	    frac_lo += step_lo; if (frac_lo > 0) { frac_lo -= 0x10000; tex_y++; }
	    tex_y += step_int;

	    count -= 4;
	}
	while (count >= 0)
	{
	    *dest = dc_colormap[dc_translation[dc_source[tex_y]]]; dest += SCREENWIDTH;
	    frac_lo += step_lo; if (frac_lo > 0) { frac_lo -= 0x10000; tex_y++; }
	    tex_y += step_int;
	    count--;
	}
    }
} 




//
// R_InitTranslationTables
// Creates the translation tables to map
//  the green color ramp to gray, brown, red.
// Assumes a given structure of the PLAYPAL.
// Could be read from a lump instead.
//
void R_InitTranslationTables (void)
{
    int		i;
	
    // 3 tables of 256 uint32_t entries each
    translationtables = Z_Malloc (256*3*sizeof(uint32_t), PU_STATIC, 0);
    
    // translate just the 16 green colors
    for (i=0 ; i<256 ; i++)
    {
	if (i >= 0x70 && i<= 0x7f)
	{
	    // map green ramp to gray, brown, red
	    translationtables[i] = 0x60 + (i&0xf);
	    translationtables [i+256] = 0x40 + (i&0xf);
	    translationtables [i+512] = 0x20 + (i&0xf);
	}
	else
	{
	    // Keep all other colors as is.
	    translationtables[i] = translationtables[i+256] 
		= translationtables[i+512] = i;
	}
    }
}




//
// R_DrawSpan 
// With DOOM style restrictions on view orientation,
//  the floors and ceilings consist of horizontal slices
//  or spans with constant z depth.
// However, rotation around the world z axis is possible,
//  thus this mapping, while simpler and faster than
//  perspective correct texture mapping, has to traverse
//  the texture at an angle in all but a few cases.
// In consequence, flats are not stored by column (like walls),
//  and the inner loop has to step in texture space u and v.
//
int			ds_y; 
int			ds_x1; 
int			ds_x2;

lighttable_t*		ds_colormap; 

fixed_t			ds_xfrac; 
fixed_t			ds_yfrac; 
fixed_t			ds_xstep; 
fixed_t			ds_ystep;

// start of a 64*64 tile image 
uint32_t*			ds_source;

// just for profiling
int			dscount;


//
// Draws the actual span.
#if !defined(USE_ASM_RDRAW) && !defined(USE_ASM_RDRAW_SPAN)
void R_DrawSpan (void) 
{ 
    fixed_t		xfrac;
    fixed_t		yfrac; 
    uint32_t*		dest; 
    int			count;
    int			spot; 
	 
#ifdef RANGECHECK 
    if (ds_x2 < ds_x1
	|| ds_x1<0
	|| ds_x2>=SCREENWIDTH  
	|| (unsigned)ds_y>SCREENHEIGHT)
    {
	I_Error( "R_DrawSpan: %i to %i at %i",
		 ds_x1,ds_x2,ds_y);
    }
//	dscount++; 
#endif 

    
    xfrac = ds_xfrac; 
    yfrac = ds_yfrac; 
	 
    dest = ylookup[ds_y] + columnofs[ds_x1];

    // We do not check for zero spans here?
    count = ds_x2 - ds_x1; 

    // Subleq optimization: split xfrac/yfrac into integer and
    // fractional accumulators. Eliminates per-pixel >>16, >>10,
    // &63, and &(63*64). All per-pixel ops are add/subtract/compare.
    {
	// Split x into integer [0,63] and fractional [-0xFFFF, 0]
	int x_int = ds_xfrac >> 16;
	int x_lo = (int)(ds_xfrac & 0xFFFF) - 0xFFFF;
	int xstep_int = ds_xstep >> 16;
	int xstep_lo = ds_xstep & 0xFFFF;

	// Split y into integer [0,63] and fractional [-0xFFFF, 0]
	int y_int = ds_yfrac >> 16;
	int y_lo = (int)(ds_yfrac & 0xFFFF) - 0xFFFF;
	int ystep_int = ds_ystep >> 16;
	int ystep_lo = ds_ystep & 0xFFFF;

	// Pre-scaled y position: y_pos = y_int * 64
	// Updated by ±64 per y_int change, avoiding per-pixel multiply.
	int y_pos;
	int ystep_scaled;

	// Normalize x_int to [0,63]
	while (x_int < 0) x_int += 64;
	while (x_int >= 64) x_int -= 64;

	// Normalize y_int to [0,63] and compute y_pos = y_int * 64
	// using only additions (6 doublings)
	while (y_int < 0) y_int += 64;
	while (y_int >= 64) y_int -= 64;
	y_pos = y_int + y_int;
	y_pos = y_pos + y_pos;  // y_int * 4
	y_pos = y_pos + y_pos;  // y_int * 8
	y_pos = y_pos + y_pos;  // y_int * 16
	y_pos = y_pos + y_pos;  // y_int * 32
	y_pos = y_pos + y_pos;  // y_int * 64

	// Pre-normalize step integers
	while (xstep_int >= 64) xstep_int -= 64;
	while (xstep_int < -64) xstep_int += 64;
	while (ystep_int >= 64) ystep_int -= 64;
	while (ystep_int < -64) ystep_int += 64;

	// Precompute ystep_int * 64 using additions
	ystep_scaled = ystep_int + ystep_int;
	ystep_scaled = ystep_scaled + ystep_scaled;
	ystep_scaled = ystep_scaled + ystep_scaled;
	ystep_scaled = ystep_scaled + ystep_scaled;
	ystep_scaled = ystep_scaled + ystep_scaled;
	ystep_scaled = ystep_scaled + ystep_scaled;  // ystep_int * 64

	while (count >= 3)
	{
	    *dest++ = ds_colormap[ds_source[y_pos + x_int]];
	    x_lo += xstep_lo; if (x_lo > 0) { x_lo -= 0x10000; x_int++; }
	    x_int += xstep_int; if (x_int >= 64) x_int -= 64; if (x_int < 0) x_int += 64;
	    y_lo += ystep_lo; if (y_lo > 0) { y_lo -= 0x10000; y_pos += 64; }
	    y_pos += ystep_scaled; if (y_pos >= 4096) y_pos -= 4096; if (y_pos < 0) y_pos += 4096;

	    *dest++ = ds_colormap[ds_source[y_pos + x_int]];
	    x_lo += xstep_lo; if (x_lo > 0) { x_lo -= 0x10000; x_int++; }
	    x_int += xstep_int; if (x_int >= 64) x_int -= 64; if (x_int < 0) x_int += 64;
	    y_lo += ystep_lo; if (y_lo > 0) { y_lo -= 0x10000; y_pos += 64; }
	    y_pos += ystep_scaled; if (y_pos >= 4096) y_pos -= 4096; if (y_pos < 0) y_pos += 4096;

	    *dest++ = ds_colormap[ds_source[y_pos + x_int]];
	    x_lo += xstep_lo; if (x_lo > 0) { x_lo -= 0x10000; x_int++; }
	    x_int += xstep_int; if (x_int >= 64) x_int -= 64; if (x_int < 0) x_int += 64;
	    y_lo += ystep_lo; if (y_lo > 0) { y_lo -= 0x10000; y_pos += 64; }
	    y_pos += ystep_scaled; if (y_pos >= 4096) y_pos -= 4096; if (y_pos < 0) y_pos += 4096;

	    *dest++ = ds_colormap[ds_source[y_pos + x_int]];
	    x_lo += xstep_lo; if (x_lo > 0) { x_lo -= 0x10000; x_int++; }
	    x_int += xstep_int; if (x_int >= 64) x_int -= 64; if (x_int < 0) x_int += 64;
	    y_lo += ystep_lo; if (y_lo > 0) { y_lo -= 0x10000; y_pos += 64; }
	    y_pos += ystep_scaled; if (y_pos >= 4096) y_pos -= 4096; if (y_pos < 0) y_pos += 4096;

	    count -= 4;
	}
	while (count >= 0)
	{
	    *dest++ = ds_colormap[ds_source[y_pos + x_int]];
	    x_lo += xstep_lo; if (x_lo > 0) { x_lo -= 0x10000; x_int++; }
	    x_int += xstep_int; if (x_int >= 64) x_int -= 64; if (x_int < 0) x_int += 64;
	    y_lo += ystep_lo; if (y_lo > 0) { y_lo -= 0x10000; y_pos += 64; }
	    y_pos += ystep_scaled; if (y_pos >= 4096) y_pos -= 4096; if (y_pos < 0) y_pos += 4096;
	    count--;
	}
    }
} 
#endif /* USE_ASM_RDRAW_SPAN */



// UNUSED.
// Loop unrolled by 4.
#if 0
void R_DrawSpan (void) 
{ 
    unsigned	position, step;

    byte*	source;
    byte*	colormap;
    byte*	dest;
    
    unsigned	count;
    usingned	spot; 
    unsigned	value;
    unsigned	temp;
    unsigned	xtemp;
    unsigned	ytemp;
		
    position = ((ds_xfrac<<10)&0xffff0000) | ((ds_yfrac>>6)&0xffff);
    step = ((ds_xstep<<10)&0xffff0000) | ((ds_ystep>>6)&0xffff);
		
    source = ds_source;
    colormap = ds_colormap;
    dest = ylookup[ds_y] + columnofs[ds_x1];	 
    count = ds_x2 - ds_x1 + 1; 
	
    while (count >= 4) 
    { 
	ytemp = position>>4;
	ytemp = ytemp & 4032;
	xtemp = position>>26;
	spot = xtemp | ytemp;
	position += step;
	dest[0] = colormap[source[spot]]; 

	ytemp = position>>4;
	ytemp = ytemp & 4032;
	xtemp = position>>26;
	spot = xtemp | ytemp;
	position += step;
	dest[1] = colormap[source[spot]];
	
	ytemp = position>>4;
	ytemp = ytemp & 4032;
	xtemp = position>>26;
	spot = xtemp | ytemp;
	position += step;
	dest[2] = colormap[source[spot]];
	
	ytemp = position>>4;
	ytemp = ytemp & 4032;
	xtemp = position>>26;
	spot = xtemp | ytemp;
	position += step;
	dest[3] = colormap[source[spot]]; 
		
	count -= 4;
	dest += 4;
    } 
    while (count > 0) 
    { 
	ytemp = position>>4;
	ytemp = ytemp & 4032;
	xtemp = position>>26;
	spot = xtemp | ytemp;
	position += step;
	*dest++ = colormap[source[spot]]; 
	count--;
    } 
} 
#endif


//
// Again..
//
void R_DrawSpanLow (void) 
{ 
    fixed_t		xfrac;
    fixed_t		yfrac; 
    uint32_t*		dest; 
    int			count;
    int			spot; 
	 
#ifdef RANGECHECK 
    if (ds_x2 < ds_x1
	|| ds_x1<0
	|| ds_x2>=SCREENWIDTH  
	|| (unsigned)ds_y>SCREENHEIGHT)
    {
	I_Error( "R_DrawSpan: %i to %i at %i",
		 ds_x1,ds_x2,ds_y);
    }
//	dscount++; 
#endif 
	 
    xfrac = ds_xfrac; 
    yfrac = ds_yfrac; 

    // Blocky mode, need to multiply by 2.
    ds_x1 <<= 1;
    ds_x2 <<= 1;
    
    dest = ylookup[ds_y] + columnofs[ds_x1];
  
    
    count = ds_x2 - ds_x1; 
    do 
    { 
	spot = ((yfrac>>(16-6))&(63*64)) + ((xfrac>>16)&63);
	// Lowres/blocky mode does it twice,
	//  while scale is adjusted appropriately.
	*dest++ = ds_colormap[ds_source[spot]]; 
	*dest++ = ds_colormap[ds_source[spot]];
	
	xfrac += ds_xstep; 
	yfrac += ds_ystep; 

    } while (count--); 
}

//
// R_InitBuffer 
// Creats lookup tables that avoid
//  multiplies and other hazzles
//  for getting the framebuffer address
//  of a pixel to draw.
//
void
R_InitBuffer
( int		width,
  int		height ) 
{ 
    int		i; 

    // Handle resize,
    //  e.g. smaller view windows
    //  with border and/or status bar.
    viewwindowx = (SCREENWIDTH-width) >> 1; 

    // Column offset. For windows.
    for (i=0 ; i<width ; i++) 
	columnofs[i] = viewwindowx + i;

    // Samw with base row offset.
    if (width == SCREENWIDTH) 
	viewwindowy = 0; 
    else 
	viewwindowy = (SCREENHEIGHT-SBARHEIGHT-height) >> 1; 

    // Preclaculate all row offsets.
    for (i=0 ; i<height ; i++) 
	ylookup[i] = screens[0] + (i+viewwindowy)*SCREENWIDTH; 
} 
 
 


//
// R_FillBackScreen
// Fills the back screen with a pattern
//  for variable screen sizes
// Also draws a beveled edge.
//
void R_FillBackScreen (void) 
{ 
    byte*	src;
    uint32_t*	dest; 
    int		x;
    int		y; 
    int		i;
    patch_t*	patch;

    // DOOM border patch.
    char	name1[] = "FLOOR7_2";

    // DOOM II border patch.
    char	name2[] = "GRNROCK";	

    char*	name;
	
    if (scaledviewwidth == 320)
	return;
	
    if ( gamemode == commercial)
	name = name2;
    else
	name = name1;
    
    src = W_CacheLumpName (name, PU_CACHE); 
    dest = screens[1]; 
	 
    for (y=0 ; y<SCREENHEIGHT-SBARHEIGHT ; y++) 
    { 
	byte* row = src+((y&63)<<6);
	for (x=0 ; x<SCREENWIDTH ; x++) 
	{ 
	    *dest++ = row[x & 63]; 
	} 
    } 
	
    patch = W_CacheLumpName ("brdr_t",PU_CACHE);

    for (x=0 ; x<scaledviewwidth ; x+=8)
	V_DrawPatch (viewwindowx+x,viewwindowy-8,1,patch);
    patch = W_CacheLumpName ("brdr_b",PU_CACHE);

    for (x=0 ; x<scaledviewwidth ; x+=8)
	V_DrawPatch (viewwindowx+x,viewwindowy+viewheight,1,patch);
    patch = W_CacheLumpName ("brdr_l",PU_CACHE);

    for (y=0 ; y<viewheight ; y+=8)
	V_DrawPatch (viewwindowx-8,viewwindowy+y,1,patch);
    patch = W_CacheLumpName ("brdr_r",PU_CACHE);

    for (y=0 ; y<viewheight ; y+=8)
	V_DrawPatch (viewwindowx+scaledviewwidth,viewwindowy+y,1,patch);


    // Draw beveled edge. 
    V_DrawPatch (viewwindowx-8,
		 viewwindowy-8,
		 1,
		 W_CacheLumpName ("brdr_tl",PU_CACHE));
    
    V_DrawPatch (viewwindowx+scaledviewwidth,
		 viewwindowy-8,
		 1,
		 W_CacheLumpName ("brdr_tr",PU_CACHE));
    
    V_DrawPatch (viewwindowx-8,
		 viewwindowy+viewheight,
		 1,
		 W_CacheLumpName ("brdr_bl",PU_CACHE));
    
    V_DrawPatch (viewwindowx+scaledviewwidth,
		 viewwindowy+viewheight,
		 1,
		 W_CacheLumpName ("brdr_br",PU_CACHE));
} 
 

//
// Copy a screen buffer.
//
void
R_VideoErase
( unsigned	ofs,
  int		count ) 
{ 
  // LFB copy.
    memcpy (screens[0]+ofs, screens[1]+ofs, count*sizeof(uint32_t)); 
} 


//
// R_DrawViewBorder
// Draws the border around the view
//  for different size windows?
//
void
V_MarkRect
( int		x,
  int		y,
  int		width,
  int		height ); 
 
void R_DrawViewBorder (void) 
{ 
    int		top;
    int		side;
    int		ofs;
    int		i; 
 
    if (scaledviewwidth == SCREENWIDTH) 
	return; 
  
    top = ((SCREENHEIGHT-SBARHEIGHT)-viewheight)/2; 
    side = (SCREENWIDTH-scaledviewwidth)/2; 
 
    // copy top and one line of left side 
    R_VideoErase (0, top*SCREENWIDTH+side); 
 
    // copy one line of right side and bottom 
    ofs = (viewheight+top)*SCREENWIDTH-side; 
    R_VideoErase (ofs, top*SCREENWIDTH+side); 
 
    // copy sides using wraparound 
    ofs = top*SCREENWIDTH + SCREENWIDTH-side; 
    side <<= 1;
    
    for (i=1 ; i<viewheight ; i++) 
    { 
	R_VideoErase (ofs, side); 
	ofs += SCREENWIDTH; 
    } 

    // ? 
    V_MarkRect (0,0,SCREENWIDTH, SCREENHEIGHT-SBARHEIGHT); 
} 
 
 
