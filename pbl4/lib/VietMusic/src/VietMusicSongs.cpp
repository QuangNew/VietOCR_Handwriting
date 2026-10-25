#include "VietMusicSongs.h"

namespace vietmusic {
namespace {
using namespace notes;
using namespace duration;
// Original single-voice arcade effects: coin, jump, power-up, victory and hurt.
// These are synthesized scores, not recordings or transcriptions of game audio.
constexpr Note kCoin[] = {{B5, Sixteenth}, {E6, Eighth}, {REST, Sixteenth}, {E6, Sixteenth}};
constexpr Note kJump[] = {{C5, 2}, {D5, 2}, {F5, 2}, {A5, 2}, {C6, Sixteenth}};
constexpr Note kPowerUp[] = {{C5, Sixteenth}, {G5, Sixteenth}, {D5, Sixteenth},
    {A5, Sixteenth}, {E5, Sixteenth}, {B5, Sixteenth}, {C6, Eighth}};
constexpr Note kWin[] = {{C5, Eighth}, {G5, Sixteenth}, {C6, Sixteenth}, {E6, Eighth},
    {REST, Sixteenth}, {D6, Sixteenth}, {G6, Quarter}};
constexpr Note kHurt[] = {{G4, Sixteenth}, {Fs4, Sixteenth}, {D4, Eighth},
    {REST, Sixteenth}, {C4, Eighth}};
constexpr Note kSleep[] = {{C6, Sixteenth}, {G5, Sixteenth}, {E5, Eighth},
    {REST, Sixteenth}, {C5, Quarter}};
constexpr Note kTest[] = {{B5, Sixteenth}, {E6, Eighth}, {REST, Eighth},
    {C5, 2}, {D5, 2}, {F5, 2}, {A5, 2}, {C6, Eighth}};
constexpr Note kScale[] = {
    {C4, Eighth}, {D4, Eighth}, {E4, Eighth}, {F4, Eighth},
    {G4, Eighth}, {A4, Eighth}, {B4, Eighth}, {C5, Quarter},
    {REST, Eighth}, {B4, Eighth}, {A4, Eighth}, {G4, Eighth},
    {F4, Eighth}, {E4, Eighth}, {D4, Eighth}, {C4, Quarter}};
// Traditional public-domain melody, no lyrics or transcription from the video.
constexpr Note kTwinkle[] = {
    {C4, Quarter}, {C4, Quarter}, {G4, Quarter}, {G4, Quarter},
    {A4, Quarter}, {A4, Quarter}, {G4, Half},
    {F4, Quarter}, {F4, Quarter}, {E4, Quarter}, {E4, Quarter},
    {D4, Quarter}, {D4, Quarter}, {C4, Half},
    {G4, Quarter}, {G4, Quarter}, {F4, Quarter}, {F4, Quarter},
    {E4, Quarter}, {E4, Quarter}, {D4, Half},
    {G4, Quarter}, {G4, Quarter}, {F4, Quarter}, {F4, Quarter},
    {E4, Quarter}, {E4, Quarter}, {D4, Half},
    {C4, Quarter}, {C4, Quarter}, {G4, Quarter}, {G4, Quarter},
    {A4, Quarter}, {A4, Quarter}, {G4, Half},
    {F4, Quarter}, {F4, Quarter}, {E4, Quarter}, {E4, Quarter},
    {D4, Quarter}, {D4, Quarter}, {C4, Half}};
struct Entry { const char* name; Melody score; };
constexpr Entry kSongs[] = {
    {"WAKE", melody(kPowerUp, 230, 94)}, {"RECEIVED", melody(kCoin, 240, 90)},
    {"PROCESS", melody(kJump, 200, 100)}, {"DONE", melody(kWin, 220, 90)},
    {"ERROR", melody(kHurt, 190, 80)}, {"SLEEP", melody(kSleep, 180)},
    {"TEST", melody(kTest, 180)}, {"SCALE", melody(kScale, 160)},
    {"TWINKLE", melody(kTwinkle, 180)},
    {"COIN", melody(kCoin, 240, 90)}, {"JUMP", melody(kJump, 200, 100)},
    {"POWERUP", melody(kPowerUp, 230, 94)}, {"WIN", melody(kWin, 220, 90)},
    {"HURT", melody(kHurt, 190, 80)}};
static_assert(sizeof(kSongs) / sizeof(kSongs[0]) == kSongCount, "Catalog mismatch");
bool sameName(const char* a, const char* b) {
  if (!a) return false;
  while (*a && *b) {
    const char upper = *a >= 'a' && *a <= 'z' ? static_cast<char>(*a - 'a' + 'A') : *a;
    if (upper != *b) return false;
    ++a; ++b;
  }
  return !*a && !*b;
}
}  // namespace

Melody song(Song id) {
  const auto index = static_cast<uint8_t>(id);
  return index < kSongCount ? kSongs[index].score : Melody{nullptr, 0, 120, 85};
}
const char* songName(Song id) {
  const auto index = static_cast<uint8_t>(id);
  return index < kSongCount ? kSongs[index].name : "UNKNOWN";
}
bool findSong(const char* name, Song& id) {
  for (uint8_t i = 0; i < kSongCount; ++i) {
    if (sameName(name, kSongs[i].name)) { id = static_cast<Song>(i); return true; }
  }
  return false;
}
}  // namespace vietmusic

