// Eternal Computer Virtual Machine (console support only)
// Executes an Eternal Software Initiative capsule (operating system + application software)
//
// This code is intended as a minimal implementation of a fully functional VM
// for the ESI architecture. It is not intended as a 'production grade' virtual
// machine (e.g. there is no memory bounds checking) to keep the implementation
// as simple as possible.

#include <stdint.h>
#include <stdio.h>
#include <unistd.h>
#include <time.h>

#define MEM_SIZE 3<<27
#define IO_SENTINEL_WORD (((uint32_t)-4) / 4)

uint32_t mem[MEM_SIZE];  /* Memory: 1.5GB (3*2^27 words) */

static inline uint32_t fetch_operand(uint32_t *pc) {
    uint32_t raw = mem[(*pc)++];

    if (raw & 1) { // Indirect: bit 0 set, dereference the pointer */
        return mem[raw / 4] / 4;
    } else { // Direct: use the value as-is (byte addr -> word index) */
        return raw / 4;
    }
}

int main(int argc, char *argv[]) {
    uint32_t a, b, c;
    uint32_t pc = 0;     /* Program counter (word index) */
    uint32_t timer = 0;  /* Timer counter for interrupts */

    fread(mem, 4, MEM_SIZE, fopen(argv[1], "r"));
    do {
        // Fetch instruction
        a = fetch_operand(&pc), b = fetch_operand(&pc), c = fetch_operand(&pc);

        if (a == IO_SENTINEL_WORD) { // GETCHAR: A is sentinel
            read(0, &mem[b], 1);
        } else if (b == IO_SENTINEL_WORD) { // PUTCHAR: B is sentinel (-4 byte addr / 4)
            write(1, &mem[a], 1);
        } else { // Regular instruction
            if (a == 64) timespec_get((struct timespec *)&mem[64], 1);  // Update clock
            uint32_t result = mem[b] - mem[a];
            mem[b] = result;
            if ((int32_t)result <= 0) { // Branch taken: jump to C
                pc = c;
            } else if (mem[0] && timer++ > 300000) { // Timer interrupt
                timer = 0;                           // Reset timer
                mem[1] = pc * 4;                     // Save PC (as byte address)
                pc = mem[0] / 4;                     // Jump to handler
            }
        }
    } while(c);
}
