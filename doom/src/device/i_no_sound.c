#include "i_sound.h"


// Init at program start...
void I_InitSound()
{

}

// ... update sound buffer and audio device at runtime...
void I_UpdateSound(void)
{

}
void I_SubmitSound(void)
{

}

// ... shut down and relase at program termination.
void I_ShutdownSound(void)
{

}


//
//  SFX I/O
//

// Initialize channels?
void I_SetChannels()
{

}

// Get raw data lump index for sound descriptor.
int I_GetSfxLumpNum (sfxinfo_t* sfxinfo )
{
    return 0;
}


// Starts a sound in a particular sound channel.
int
I_StartSound
( int		id,
  int		vol,
  int		sep,
  int		pitch,
  int		priority )
{
    return 0;
}


// Stops a sound channel.
void I_StopSound(int handle)
{

}

// Called by S_*() functions
//  to see if a channel is still playing.
// Returns 0 if no longer playing, 1 if playing.
int I_SoundIsPlaying(int handle)
{
    return 0;
}

// Updates the volume, separation,
//  and pitch of a sound channel.
void
I_UpdateSoundParams
( int		handle,
  int		vol,
  int		sep,
  int		pitch )
{

}