#include "VietMusicOutput.h"

#include <Arduino.h>
#include <esp_arduino_version.h>

namespace vietmusic {
bool Esp32Output::begin(uint8_t pin, OutputMode mode, bool activeHigh, uint8_t channel) {
  if (ready_) end();
  pin_ = pin; mode_ = mode; activeHigh_ = activeHigh; channel_ = channel;
  digitalWrite(pin_, activeHigh_ ? LOW : HIGH);
  pinMode(pin_, OUTPUT);
  if (mode_ == OutputMode::PassiveBuzzer) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    if (!ledcAttachChannel(pin_, 2000, 10, channel_)) return false;
#else
    if (!ledcSetup(channel_, 2000, 10)) return false;
    ledcAttachPin(pin_, channel_);
#endif
  }
  ready_ = true;
  frequency_ = UINT16_MAX;  // Force silence, including active-low drivers.
  return write(0);
}

bool Esp32Output::write(uint16_t frequencyHz) {
  if (!ready_) return false;
  if (frequencyHz == frequency_) return true;
  if (mode_ == OutputMode::ActiveBuzzer) {
    digitalWrite(pin_, (frequencyHz != 0) == activeHigh_ ? HIGH : LOW);
  } else {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    const uint8_t target = pin_;
#else
    const uint8_t target = channel_;
#endif
    if (!frequencyHz) {
      ledcWrite(target, activeHigh_ ? 0 : 1023);
    } else if (!ledcWriteTone(target, frequencyHz)) {
      ledcWrite(target, activeHigh_ ? 0 : 1023);
      frequency_ = 0;
      return false;
    }
  }
  frequency_ = frequencyHz;
  return true;
}

void Esp32Output::end() {
  if (!ready_) return;
  write(0);
  if (mode_ == OutputMode::PassiveBuzzer) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcDetach(pin_);
#else
    ledcDetachPin(pin_);
#endif
  }
  digitalWrite(pin_, activeHigh_ ? LOW : HIGH);
  ready_ = false;
}
}  // namespace vietmusic

