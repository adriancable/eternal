#include "i_sound.h"


void I_InitMusic(void)
{

}

void I_ShutdownMusic(void)
{

}

// Volume.
void I_SetMusicVolume(int volume)
{

}

// PAUSE game handling.
void I_PauseSong(int handle)
{

}

void I_ResumeSong(int handle)
{

}

// Registers a song handle to song data.
int I_RegisterSong(void *data, const char *name)
{
    return 0;
}

// Called by anything that wishes to start music.
//  plays a song, and when the song is done,
//  starts playing it again in an endless loop.
// Horrible thing to do, considering.
void
I_PlaySong
( int		handle,
  int		looping )
  {

  }

// Stops a song over 3 seconds.
void I_StopSong(int handle)
{

}

// See above (register), then think backwards
void I_UnRegisterSong(int handle)
{

}
