#pragma once
#include <stdint.h>
#include <stddef.h>

// OV5640 mailbox sequence following Espressif's AF helper. Bus owns SCCB + time;
// all calls run on the camera task, never the BLE/HTTP/TFT tasks.
namespace autofocus {
enum class Error { None, NotReady, Read, Write, Timeout, NoContrast };
template<class Bus> class Control {
 public:
  explicit Control(Bus& bus): bus_(bus) {}
  bool ready() const { return ready_; }
  Error error() const { return error_; }
  void reset() { ready_ = false; error_ = Error::NotReady; }
  bool begin(const uint8_t* firmware, size_t size) {
    reset();
    if (!firmware || !size || size > 0x8000) return false;
    if (!write(0x3000, 0x20)) return false;
    for (size_t i=0; i<size; ++i) {
      if (!write(0x8000 + i, firmware[i])) return false;
      if (!(i % 64)) bus_.delay(1);
    }
    for (uint16_t reg=0x3022; reg<=0x3028; ++reg) if (!write(reg, 0)) return false;
    if (!write(0x3029, 0x7f) || !write(0x3000, 0) || !wait(0x3029, 0x70, 2000)) return false;
    ready_ = true; error_ = Error::None; return true;
  }
  bool continuous() {
    if (!ready_) { error_ = Error::NotReady; return false; }
    // Reset the AF command engine before continuous mode, as in Espressif's
    // helper. A bare 0x04 after a mode switch can leave CMD_ACK stuck high.
    return write(0x3022, 0x01) && write(0x3022, 0x08) && wait(0x3023, 0, 1000) &&
        write(0x3023, 1) && write(0x3022, 0x04) && wait(0x3023, 0, 1500);
  }
  bool pause() {
    if (!ready_) { error_ = Error::NotReady; return false; }
    return write(0x3023, 1) && write(0x3022, 0x06) && wait(0x3023, 0, 500);
  }
  bool single(uint32_t timeoutMs=2000) {
    if (!ready_) { error_ = Error::NotReady; return false; }
    if (!write(0x3023, 1) || !write(0x3022, 0x03) || !wait(0x3023, 0, timeoutMs)) return false;
    const int raw = status();
    if (raw < 0) return false;
    if (raw != 0x10) { error_ = Error::NoContrast; return false; }
    error_ = Error::None; return true;
  }
  int status() {
    const int value = bus_.read(0x3029);
    if (value < 0) error_ = Error::Read;
    return value;
  }
 private:
  Bus& bus_;
  bool ready_ = false;
  Error error_ = Error::NotReady;
  bool write(uint16_t reg, uint8_t value) {
    if (!bus_.write(reg, value)) { error_ = Error::Write; return false; }
    return true;
  }
  bool wait(uint16_t reg, uint8_t wanted, uint32_t timeout) {
    const uint32_t started = bus_.millis();
    do {
      const int value = bus_.read(reg);
      if (value < 0) { error_ = Error::Read; return false; }
      if (value == wanted) { error_ = Error::None; return true; }
      bus_.delay(5);
    } while (uint32_t(bus_.millis() - started) < timeout);
    error_ = Error::Timeout; return false;
  }
};
}
