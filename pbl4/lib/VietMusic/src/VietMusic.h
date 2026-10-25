#pragma once

#include <stddef.h>
#include <stdint.h>
#include "VietMusicNotes.h"

namespace vietmusic {
// A beat is a quarter note. 24 ticks supports eighth-note triplets exactly.
namespace duration {
constexpr uint16_t Sixteenth = 6, Eighth = 12, Quarter = 24, Half = 48, Whole = 96;
constexpr uint16_t DottedEighth = 18, DottedQuarter = 36, DottedHalf = 72;
constexpr uint16_t EighthTriplet = 8;
}
struct Note {
  uint16_t frequencyHz;
  uint16_t ticks;
};
struct Melody {
  const Note* notes;
  uint16_t count;
  uint16_t bpm;
  uint8_t gatePercent;  // End each note with a short gap; REST is always silent.
};
template <size_t Size>
constexpr Melody melody(const Note (&score)[Size], uint16_t bpm, uint8_t gate = 85) {
  static_assert(Size <= 512, "A melody can contain at most 512 notes");
  return {score, static_cast<uint16_t>(Size), bpm, gate};
}

// Score memory must remain alive until playback ends (prefer static const).
// No delay, heap allocation, Arduino dependency, or timer interrupt in this core.
class Player {
 public:
  bool play(Melody melody, uint32_t now);
  void update(uint32_t now);
  void stop();
  void setMuted(bool muted);
  bool muted() const { return muted_; }
  bool playing() const { return melody_.notes != nullptr; }
  uint16_t frequency() const { return frequency_; }
  uint16_t noteIndex() const { return index_; }
  static bool valid(Melody melody);
  static uint32_t noteMilliseconds(const Note& note, uint16_t bpm);

 private:
  Melody melody_ = {nullptr, 0, 120, 85};
  uint16_t index_ = 0, frequency_ = 0;
  uint32_t noteSince_ = 0;
  bool muted_ = false;
};
}  // namespace vietmusic

