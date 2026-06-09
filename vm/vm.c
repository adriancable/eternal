// Eternal Computer Virtual Machine with Framebuffer Support
//
// This code is intended as a minimal implementation of a fully functional VM
// for the ESI architecture. It is not intended as a 'production grade' virtual
// machine (e.g. there is no memory bounds checking) to keep the implementation
// as simple as possible.

#include <SDL3/SDL.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>

#define FB_WIDTH  800
#define FB_HEIGHT 512
#define FB_SIZE   (FB_WIDTH * FB_HEIGHT * 4)
#define FB_ADDR   (0x60000000 - FB_SIZE)
#define MEM_SIZE  (3 << 27)

#define DISPLAY_UPDATE_INTERVAL_MS  (1000 / 30) // 30 FPS

int mem[MEM_SIZE];
int pc, timer;

SDL_Window *window;
SDL_Surface *screen;

// Poll one key event from SDL's internal queue.
// Returns: positive = key down scancode, negative = key up, 0 = none
static inline int kb_poll(void) {
    SDL_Event e;
    if (SDL_PollEvent(&e) && (e.type == SDL_EVENT_KEY_DOWN || e.type == SDL_EVENT_KEY_UP)) {
        return (e.type == SDL_EVENT_KEY_DOWN) ? e.key.scancode : -e.key.scancode;
    }
    return 0;
}

static inline int fetch(void) {
    int raw = mem[pc++];
    return (raw & 1) ? mem[raw / 4] / 4 : raw / 4;
}

int main(int argc, char *argv[]) {
    if (argc < 2) return fprintf(stderr, "Usage: %s <binary>\n", argv[0]), 1;
    
    FILE *f = fopen(argv[1], "r");
    if (!f) return 1;
    fread(mem, 4, MEM_SIZE, f);
    fclose(f);
    
    window = SDL_CreateWindow("ESI Virtual Machine", FB_WIDTH, FB_HEIGHT, 0);
    screen = SDL_GetWindowSurface(window);
    
    Uint32 last_render = 0;
    int a, b, c;

    do {
        // Fetch next instruction
        a = fetch(); b = fetch(); c = fetch();
        
        if (a == -1) { // Read scan code from keyboard
            mem[b] = kb_poll();
        } else if (b == -1) { // Write text to console
            write(1, &mem[a], 1);
        } else { // Subleq operation
            if (a == 64) {
                timespec_get((struct timespec *)&mem[64], TIME_UTC); // Update clock
            }

            mem[b] -= mem[a];
            if (mem[b] <= 0) {
                pc = c;
            }
            
            if (mem[0] && ++timer > 800000) { // Timer interrupt & display update
                // Update display
                Uint32 now = SDL_GetTicks();
                if (now - last_render >= DISPLAY_UPDATE_INTERVAL_MS) {
                    // Just memcpy from VM framebuffer to screen
                    memcpy(screen->pixels, &mem[FB_ADDR / 4], FB_SIZE);
                    SDL_UpdateWindowSurface(window);
                    last_render = now;
                }

                // Trigger interrupt
                mem[1] = pc * 4;
                pc = mem[0] / 4;
                timer = 0;                
            }
        }
    } while(c);
}
