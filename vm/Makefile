CC ?= cc
CFLAGS ?= -O3 -march=native --std=gnu17
SDL3_CFLAGS := $(shell pkg-config sdl3 --cflags 2>/dev/null)
SDL3_LIBS := $(shell pkg-config sdl3 --libs 2>/dev/null)

all: vm_console vm

vm_console: vm_console.c
	$(CC) $(CFLAGS) -o $@ $<

vm: vm.c
	$(CC) $(CFLAGS) $(SDL3_CFLAGS) -o $@ $< $(SDL3_LIBS)

clean:
	rm -f vm_console vm

.PHONY: all clean
