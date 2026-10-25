#pragma once

#include <stdint.h>

namespace vietmusic {
enum class OutputMode : uint8_t { ActiveBuzzer, PassiveBuzzer };

// GPIO/DC for an active buzzer; LEDC square wave for a passive buzzer.
// The active mode follows rhythm only: it cannot change the built-in pitch.
class Esp32Output {
 public:
  bool begin(uint8_t pin, OutputMode mode, bool activeHigh = true, uint8_t channel = 0);
  bool write(uint16_t frequencyHz);
  void end();
  bool ready() const { return ready_; }
  OutputMode mode() const { return mode_; }

 private:
  uint8_t pin_ = 0, channel_ = 0;
  OutputMode mode_ = OutputMode::ActiveBuzzer;
  bool activeHigh_ = true, ready_ = false;
  uint16_t frequency_ = 0;
};
}  // namespace vietmusic

