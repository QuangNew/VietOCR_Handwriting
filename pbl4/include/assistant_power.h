#pragma once
#include <stdint.h>
namespace assistant_power {
void update(uint32_t now, bool cameraActive, bool transferring = false);
int temperatureDeciC();  // -32768 means unavailable. Die temperature, not ambient.
bool tooHot();
unsigned limitFps(unsigned requested);
}
