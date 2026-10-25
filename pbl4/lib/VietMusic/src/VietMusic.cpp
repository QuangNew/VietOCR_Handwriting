#include "VietMusic.h"

namespace vietmusic {
bool Player::valid(Melody score) {
  if (!score.notes || !score.count || score.count > 512 ||
      score.bpm < 20 || score.bpm > 400 ||
      !score.gatePercent || score.gatePercent > 100) return false;
  for (uint16_t i = 0; i < score.count; ++i) {
    const Note& note = score.notes[i];
    if (!note.ticks || note.ticks > duration::Whole * 4 ||
        (note.frequencyHz && (note.frequencyHz < 16 || note.frequencyHz > 20000))) return false;
  }
  return true;
}

uint32_t Player::noteMilliseconds(const Note& note, uint16_t bpm) {
  if (bpm < 20 || bpm > 400 || !note.ticks || note.ticks > duration::Whole * 4) return 0;
  const uint32_t denominator = static_cast<uint32_t>(bpm) * duration::Quarter;
  return (60000UL * note.ticks + denominator / 2) / denominator;
}

bool Player::play(Melody score, uint32_t now) {
  stop();
  if (muted_ || !valid(score)) return false;
  melody_ = score;
  noteSince_ = now;
  update(now);
  return true;
}

void Player::update(uint32_t now) {
  if (!playing()) return;
  // Catch up without replaying missed notes when drawing/BLE delays a loop.
  while (now - noteSince_ >= noteMilliseconds(melody_.notes[index_], melody_.bpm)) {
    noteSince_ += noteMilliseconds(melody_.notes[index_], melody_.bpm);
    if (++index_ >= melody_.count) { stop(); return; }
  }
  const Note& note = melody_.notes[index_];
  const uint32_t requested = noteMilliseconds(note, melody_.bpm) * melody_.gatePercent / 100;
  const uint32_t sounding = requested ? requested : 1;  // Keep short notes audible at small gates.
  frequency_ = now - noteSince_ < sounding ? note.frequencyHz : 0;
}

void Player::stop() {
  melody_ = {nullptr, 0, 120, 85};
  index_ = frequency_ = 0;
}

void Player::setMuted(bool muted) {
  muted_ = muted;
  if (muted_) stop();  // Unmute never unexpectedly resumes a stopped song.
}
}  // namespace vietmusic

