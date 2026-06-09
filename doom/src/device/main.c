#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <termios.h>
#include <sys/ioctl.h>
#include <linux/kd.h>

#include "doomdef.h"
#include "d_event.h"
#include "m_argv.h"
#include "d_main.h"

static struct termios orig_term;
static int orig_kbd_mode = -1;

// Translate Linux console scancode to Doom keycode
static int xlatekey(int scancode)
{
    switch(scancode)
    {
    case 0x01: return KEY_ESCAPE;
    case 0x0e: return KEY_BACKSPACE;
    case 0x0f: return KEY_TAB;
    case 0x1c: return KEY_ENTER;
    case 0x39: return ' ';
    // Arrow keys (extended scancodes in medium-raw)
    case 0x67: return KEY_UPARROW;
    case 0x69: return KEY_LEFTARROW;
    case 0x6a: return KEY_RIGHTARROW;
    case 0x6c: return KEY_DOWNARROW;
    case 0x2a: // left shift
    case 0x36: return KEY_RSHIFT;
    case 0x1d: // left ctrl
    case 0x61: return KEY_RCTRL;
    case 0x38: // left alt
    case 0x64: return KEY_RALT;
    case 0x0d: return KEY_EQUALS;
    case 0x0c: return KEY_MINUS;
    case 0x3b: return KEY_F1;
    case 0x3c: return KEY_F2;
    case 0x3d: return KEY_F3;
    case 0x3e: return KEY_F4;
    case 0x3f: return KEY_F5;
    case 0x40: return KEY_F6;
    case 0x41: return KEY_F7;
    case 0x42: return KEY_F8;
    case 0x43: return KEY_F9;
    case 0x44: return KEY_F10;
    case 0x57: return KEY_F11;
    case 0x58: return KEY_F12;
    // Letters (QWERTY layout scancodes)
    case 0x1e: return 'a';  case 0x30: return 'b';
    case 0x2e: return 'c';  case 0x20: return 'd';
    case 0x12: return 'e';  case 0x21: return 'f';
    case 0x22: return 'g';  case 0x23: return 'h';
    case 0x17: return 'i';  case 0x24: return 'j';
    case 0x25: return 'k';  case 0x26: return 'l';
    case 0x32: return 'm';  case 0x31: return 'n';
    case 0x18: return 'o';  case 0x19: return 'p';
    case 0x10: return 'q';  case 0x13: return 'r';
    case 0x1f: return 's';  case 0x14: return 't';
    case 0x16: return 'u';  case 0x2f: return 'v';
    case 0x11: return 'w';  case 0x2d: return 'x';
    case 0x15: return 'y';  case 0x2c: return 'z';
    // Numbers
    case 0x0b: return '0';
    case 0x02: return '1';  case 0x03: return '2';
    case 0x04: return '3';  case 0x05: return '4';
    case 0x06: return '5';  case 0x07: return '6';
    case 0x08: return '7';  case 0x09: return '8';
    case 0x0a: return '9';
    default:   return 0;
    }
}

static void kbd_cleanup(void)
{
    // Restore keyboard mode and terminal settings
    if (orig_kbd_mode >= 0)
        ioctl(0, KDSKBMODE, orig_kbd_mode);
    tcsetattr(0, TCSANOW, &orig_term);
}

int main(int argc, const char** argv)
{
    myargc = argc;
    myargv = argv;

    // Save original terminal settings
    tcgetattr(0, &orig_term);

    // Save original keyboard mode
    if (ioctl(0, KDGKBMODE, &orig_kbd_mode) < 0) {
        printf("Warning: could not get keyboard mode\n");
        orig_kbd_mode = -1;
    }

    // Set up cleanup on exit
    atexit(kbd_cleanup);

    // Set terminal to raw mode
    struct termios raw = orig_term;
    raw.c_iflag &= ~(IXON | ICRNL | ISTRIP);
    raw.c_lflag &= ~(ICANON | ECHO | ISIG);
    raw.c_cc[VMIN] = 0;
    raw.c_cc[VTIME] = 0;
    tcsetattr(0, TCSANOW, &raw);

    // Switch keyboard to medium-raw mode (scancodes with press/release)
    if (orig_kbd_mode >= 0) {
        if (ioctl(0, KDSKBMODE, K_MEDIUMRAW) < 0) {
            printf("Warning: could not set raw keyboard mode\n");
        }
    }

    D_DoomMain();

    // kbd_cleanup called via atexit
    return 0;
}

void I_StartTic (void)
{
    unsigned char buf[32];
    int n = read(0, buf, sizeof(buf));
    int i;

    for (i = 0; i < n; i++)
    {
        int pressed = !(buf[i] & 0x80);
        int scancode = buf[i] & 0x7F;

        int doomkey = xlatekey(scancode);
        if (doomkey == 0)
            continue;

        event_t event;
        event.type = pressed ? ev_keydown : ev_keyup;
        event.data1 = doomkey;
        event.data2 = 0;
        event.data3 = 0;
        D_PostEvent(&event);
    }
}