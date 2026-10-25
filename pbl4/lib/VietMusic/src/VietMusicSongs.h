#pragma once

#include "VietMusic.h"

namespace vietmusic {
enum class Song : uint8_t { Wake, Received, Process, Done, Error, Sleep, Test, Scale, Twinkle,
                          Coin, Jump, PowerUp, Win, Hurt };
constexpr uint8_t kSongCount = 14;
Melody song(Song id);
const char* songName(Song id);
bool findSong(const char* name, Song& id);
}  // namespace vietmusic

