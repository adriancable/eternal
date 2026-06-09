//
//  i_mus_convert.hpp
//  DoomTV
//
//  Created by Kristoffer Andersen on 21/02/2019.
//  Copyright © 2019 Kristoffer Andersen. All rights reserved.
//

#ifndef i_mus_convert_hpp
#define i_mus_convert_hpp

#include <stdio.h>

extern "C" {
    bool convertToMidi(void *musData, void **midiOutput);
}


#endif /* i_mus_convert_hpp */
