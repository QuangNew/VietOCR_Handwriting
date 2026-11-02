#pragma once
#include <stdint.h>

namespace capture_quality {
// Actual OV5640 AEC/AGC register readings, not cached sensor_t.status values.
// Require three consecutive native exposures within 8% before accepting a still.
class ExposureSettling {
 public:
  bool observe(int exposure, int gain) {
    if (exposure <= 0 || gain <= 0) { count_ = 0; return false; }
    const bool stable = close(exposure, exposure_) && close(gain, gain_);
    count_ = stable ? count_ + 1 : 1;
    exposure_ = exposure; gain_ = gain;
    return count_ >= 3;
  }
  void reset() { count_ = 0; exposure_ = gain_ = 0; }
 private:
  unsigned count_ = 0;
  int exposure_ = 0, gain_ = 0;
  static bool close(int a, int b) {
    if (b <= 0) return false;
    const int64_t difference = a > b ? int64_t(a)-b : int64_t(b)-a;
    return difference * 100 <= int64_t(b) * 8;
  }
};
}
