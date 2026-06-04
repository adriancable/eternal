// Eternal Computer Virtual Machine (console support only)
// Executes an Eternal Software Initiative capsule (operating system + application software)

#include <stdio.h>
#include <unistd.h>
#include <time.h>

#define MEM_SIZE 3<<27

int mem[MEM_SIZE];  /* Memory: 1.5GB (3*2^27 words) */
int pc;             /* Program counter (word index) */
int timer;          /* Timer counter for interrupts */

int fetch_operand(void) {
    int raw = mem[pc++];

    if (raw & 1) { // Indirect: bit 0 set, dereference the pointer */
        return mem[raw / 4] / 4;
    } else { // Direct: use the value as-is (byte addr -> word index) */
        return raw / 4;
    }
}

int main(int argc, char *argv[]) {
    int a, b, c;

    fread(mem, 4, MEM_SIZE, fopen(argv[1], "r"));
    do {
        // Fetch instruction
        a = fetch_operand(), b = fetch_operand(), c = fetch_operand();

        if (a == -1) { // GETCHAR: A is sentinel
            read(0, &mem[b], 1);
        } else if (b == -1) { // PUTCHAR: B is sentinel (-4 byte addr / 4 = -1)
            write(1, &mem[a], 1);
        } else { // Regular instruction
            if (a == 64) timespec_get((struct timespec *)&mem[64], 1);  // Update clock
            mem[b] -= mem[a];
            if (mem[b] <= 0) { // Branch taken: jump to C
                pc = c;
            } else if (mem[0] && timer++ > 300000) { // Timer interrupt
                timer = 0;                           // Reset timer
                mem[1] = pc * 4;                     // Save PC (as byte address)
                pc = mem[0] / 4;                     // Jump to handler
            }
        }
    } while(c);
}
