//
//  i_sdl_sound.h
//  sdldoom
//
//  Created by Kristoffer Andersen on 20/02/2019.
//  Copyright © 2019 Kristoffer Andersen. All rights reserved.
//

#ifndef i_sdl_sound_h
#define i_sdl_sound_h

#include <stdio.h>
#include "sounds.h"

void I_InitSound(void);

// ... update sound buffer and audio device at runtime...
void I_UpdateSound(void);
void I_SubmitSound(void);

// ... shut down and relase at program termination.
void I_ShutdownSound(void);

//
//  SFX I/O
//

// Initialize channels?
void I_SetChannels(void);

// Get raw data lump index for sound descriptor.
int I_GetSfxLumpNum (sfxinfo_t* sfxinfo);


// Starts a sound in a particular sound channel.
int
I_StartSound(int        id,
            int        vol,
            int        sep,
            int        pitch,
            int        priority);

int firstAvailSlot(void);

// Stops a sound channel.
void I_StopSound(int handle);

// Called by S_*() functions
//  to see if a channel is still playing.
// Returns 0 if no longer playing, 1 if playing.
int I_SoundIsPlaying(int handle);

// Updates the volume, separation,
//  and pitch of a sound channel.
void
I_UpdateSoundParams
( int        handle,
 int        vol,
 int        sep,
 int        pitch );


//
//  MUSIC I/O
//
void I_InitMusic(void);
void I_ShutdownMusic(void);
// Volume.
void I_SetMusicVolume(int volume);
// PAUSE game handling.
void I_PauseSong(int handle);
void I_ResumeSong(int handle);
// Registers a song handle to song data.
int I_RegisterSong(void *data, const char *name);
// Called by anything that wishes to start music.
//  plays a song, and when the song is done,
//  starts playing it again in an endless loop.
// Horrible thing to do, considering.
void
I_PlaySong
( int        handle,
 int        looping );
// Stops a song over 3 seconds.
void I_StopSong(int handle);
// See above (register), then think backwards
void I_UnRegisterSong(int handle);

#endif /* i_sdl_sound_h */
