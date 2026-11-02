#include "capture_quality.h"
#include <assert.h>
#include <stdio.h>
int main() {
  capture_quality::ExposureSettling gate;
  assert(!gate.observe(10000, 32));
  assert(!gate.observe(10300, 33));
  assert(gate.observe(10000, 32));
  assert(!gate.observe(18000, 64)); // light/motion change resets convergence
  assert(!gate.observe(17500, 62));
  assert(gate.observe(17800, 64));
  assert(!gate.observe(-1, 64)); // failed SCCB reads cannot pass
  assert(!gate.observe(18000, 64));
  assert(!gate.observe(18000, 64));
  assert(gate.observe(18000, 64));
  gate.reset();
  assert(!gate.observe(18000, 64));
  assert(!gate.observe(0, 0));
  puts("PASS native capture exposure convergence, change, read faults and reset");
}
