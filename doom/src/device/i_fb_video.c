#include "i_video.h"
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <linux/fb.h>
#include <linux/kd.h>
#include <sys/mman.h>
#include <stdint.h>
#include <string.h>
#include "v_video.h"

static FILE* fbfd = 0;
static struct fb_var_screeninfo vinfo;
static struct fb_fix_screeninfo finfo;
static long int screensize = 0;
static char *fbp = 0;
static int fb_stride_words = 0;  // framebuffer stride in uint32_t words


void I_InitGraphics (void)
{
    /* Open the file for reading and writing */
    fbfd = open("/dev/fb0", O_RDWR);
    if (!fbfd) {
            printf("Error: cannot open framebuffer device.\n");
            exit(1);
    }
    printf("The framebuffer device was opened successfully.\n");

    /* Get fixed screen information */
    if (ioctl(fbfd, FBIOGET_FSCREENINFO, &finfo)) {
        printf("Error reading fixed information.\n");
            exit(2);
    }

    /* Get variable screen information */
        if (ioctl(fbfd, FBIOGET_VSCREENINFO, &vinfo)) {
                printf("Error reading variable information.\n");
                exit(3);
        }

    /* Figure out the size of the screen in bytes */
    screensize = vinfo.xres * vinfo.yres * vinfo.bits_per_pixel / 8;
    printf("Screen size is %d\n",screensize);
    printf("Vinfo.bpp = %d\n",vinfo.bits_per_pixel);

    /* Map the device to memory */
    fbp = (char *)mmap(0, screensize, PROT_READ | PROT_WRITE, MAP_SHARED,fbfd, 0);
    if ((int64_t)fbp == -1) {
            printf("Error: failed to map framebuffer device to memory.\n");
            exit(4);
    }
    printf("The framebuffer device was mapped to memory successfully.\n");

    // Clear screen
    printf("\033[2J");

    // Graphics mode
    int tty_fd = open("/dev/tty0", O_RDWR);
    ioctl(tty_fd, KDSETMODE, KD_GRAPHICS);
    close(tty_fd);

    fb_stride_words = finfo.line_length / sizeof(uint32_t);
}


void I_ShutdownGraphics(void)
{
    munmap(fbp, screensize);
    close(fbfd);

    // Text mode
    int tty_fd = open("/dev/tty0", O_RDWR);
    ioctl(tty_fd, KDSETMODE, KD_TEXT);
    close(tty_fd);

    // Clear screen
    printf("\033[2J");
}

void I_StartFrame (void)
{

}

// Palette array: palette index → XRGB8888.
// Used by non-colormapped pixel writes (V_DrawPatch, etc.).
uint32_t colors_raw[256];

// Takes full 8 bit values.
void I_SetPalette (byte* palette)
{
    byte r, g, b;
    // set the X colormap entries
    for (int i=0 ; i<256 ; i++)
    {
        r = gammatable[usegamma][*palette++];
        g = gammatable[usegamma][*palette++];
        b = gammatable[usegamma][*palette++];
        // Build XRGB8888 directly: 0x00RRGGBB
        colors_raw[i] = ((uint32_t)r << 16) | ((uint32_t)g << 8) | b;
    }

    // Rebuild colormaps with XRGB values so render inner loops
    // write XRGB directly (no palette lookup needed in I_FinishUpdate).
    {
        extern lighttable_t* colormaps;
        extern int colormaps_length;
        extern byte* colormaps_raw;
        if (colormaps && colormaps_raw)
        {
            for (int i = 0; i < colormaps_length; i++)
                colormaps[i] = colors_raw[colormaps_raw[i]];
        }
    }
}

void I_UpdateNoBlit (void)
{

}

// I_FinishUpdate: 2x2 pixel doubling from screens[0] (XRGB) to framebuffer.
// Each 320x200 source pixel becomes a 2x2 block in the framebuffer.
// Image is centred within the framebuffer.
extern void RenderBlit(uint32_t *sp, uint32_t *dp, int width, int height, int fb_stride_words);

void I_FinishUpdate (void)
{
    uint32_t *src = screens[0];
    uint32_t *dst = (uint32_t *)fbp;

    // Centre the 2x-doubled image within the framebuffer
    int doubled_w = SCREENWIDTH * 2;
    int doubled_h = SCREENHEIGHT * 2;
    int x_offset = ((int)vinfo.xres - doubled_w) / 2;
    int y_offset = ((int)vinfo.yres - doubled_h) / 2;
    if (x_offset < 0) x_offset = 0;
    if (y_offset < 0) y_offset = 0;

    dst += y_offset * fb_stride_words + x_offset;

    RenderBlit(src, dst, SCREENWIDTH, SCREENHEIGHT, fb_stride_words);
}

void I_ReadScreen (uint32_t* scr)
{
    memcpy(scr, screens[0], SCREENWIDTH*SCREENHEIGHT*sizeof(uint32_t));
}
