#CXX=g++
#CC=aarch64-linux-gnu-gcc

SOURCES = $(patsubst src/%, %, $(wildcard src/*.c))
SOURCES += device/main.c device/i_fb_video.c device/i_no_sound.c device/i_no_music.c
OBJECTS = $(patsubst %.c, %.o, $(SOURCES))

# Assembly sources (Subleq hand-optimized)
ASM_SOURCES = $(patsubst src/%, %, $(wildcard src/*.S))
ASM_OBJECTS = $(patsubst %.S, %.o, $(ASM_SOURCES))

TARGET_OBJS = $(patsubst %, build/%, $(OBJECTS)) $(patsubst %, build/%, $(ASM_OBJECTS))
CCFLAGS = -DNORMALUNIX -DUSE_ASM_FIXED -DUSE_ASM_RDRAW -std=gnu99 -O3 -Wno-implicit-int -Wno-int-conversion --sysroot=../runtime/sysroot -isystem ../runtime/sysroot/kernel-headers
MC ?= $(dir $(CC))llvm-mc

.PHONY:
all: doom

.PHONY: sources
sources:
	@echo $(SOURCES)

.PHONY: objects
objects:
	@echo $(TARGET_OBJS)

build:
	mkdir -p build/device

build/%.o: src/%.c
	@mkdir -p build/device
	@echo "Compiling $<..."
	@$(CC) -c $< -I src $(CCFLAGS) -g -o $@

build/%.o: src/%.S
	@mkdir -p build
	@echo "Assembling $<..."
	@$(MC) -triple=subleq -filetype=obj -o $@ $<

build/device/%.o: src/device/%.c
	@echo "Compiling $<..."
	@$(CC) -c $< -I src $(CCFLAGS) -g -o $@

.PHONY:
link: $(TARGET_OBJS)
	@echo "Linking..."
	@$(CC) $(CCFLAGS) -o doom $(TARGET_OBJS)

doom: link
