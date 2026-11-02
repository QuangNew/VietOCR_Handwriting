#pragma once
#include <stdint.h>

// User scans take priority over an offline station's reconnect attempts.
// Delayed, bounded retries let the driver finish disconnecting without blocking
// BLE/TFT or reporting every temporary WIFI_SCAN_FAILED as a permanent failure.
class WifiScanRecovery {
 public:
  enum class State { Idle, Waiting, Running, Done, Failed };
  State state = State::Idle;
  unsigned attempts = 0;
  void request(uint32_t now) {
    if (active()) return;
    state = State::Waiting; attempts = 0; changed_ = now;
  }
  bool active() const { return state == State::Waiting || state == State::Running; }
  bool due(uint32_t now) const {
    return state == State::Waiting && uint32_t(now - changed_) >= (attempts ? 500u : 250u);
  }
  void started(uint32_t now, int result) {
    ++attempts; changed_ = now;
    state = result >= 0 ? State::Done : result == -1 ? State::Running :
            attempts < 3 ? State::Waiting : State::Failed;
  }
  void poll(uint32_t now, int result) {
    if (state != State::Running) return;
    if (result >= 0) state = State::Done;
    else if (result != -1 || uint32_t(now - changed_) >= 15000u) state = State::Failed;
  }
  void reset() { state = State::Idle; attempts = 0; }
 private:
  uint32_t changed_ = 0;
};

class WifiReconnect {
 public:
  void reset(uint32_t now) { failures_ = 0; delay_ = 0; changed_ = now; }
  void failed(uint32_t now) {
    if (failures_ < 6) ++failures_;
    delay_ = failures_ >= 5 ? 60000 : 3000u << (failures_ - 1);
    changed_ = now;
  }
  void pause(uint32_t now, uint32_t milliseconds) { changed_ = now; delay_ = milliseconds; }
  bool due(uint32_t now) const { return uint32_t(now - changed_) >= delay_; }
  uint32_t delayMs() const { return delay_; }
  bool bluetoothConnected(uint32_t now, bool hasProfile, bool online, bool joining) {
    if (!hasProfile || online) return false;
    reset(now);  // A new BLE session must not wait out a 60s retry/scan pause.
    return !joining; // Keep a connection attempt that is already in progress.
  }
 private:
  uint32_t changed_ = 0, delay_ = 0;
  unsigned failures_ = 0;
};
