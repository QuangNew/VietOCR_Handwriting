#include "assistant_power.h"
#include <Arduino.h>
#include <atomic>
#include <driver/temp_sensor.h>
#include <math.h>

namespace assistant_power {
namespace {
std::atomic<int> measured{-32768};
std::atomic<bool> cooling{false};
uint32_t checked=0;
bool configured=false;
}
int temperatureDeciC() { return measured.load(); }
bool tooHot() { return cooling.load(); }
unsigned limitFps(unsigned requested) {
  if (measured.load()>=750 && (!requested || requested>10)) return 10;
  return requested;
}
void update(uint32_t now, bool cameraActive, bool transferring) {
  // APB stays at 80 MHz for SPI/UART/LEDC at both CPU rates. Change CPU only
  // after the camera task confirms XCLK/DMA stopped, never during a capture.
  // Keep the radio-serving idle CPU on 160 MHz. In this Arduino/IDF build,
  // requests after dropping to 80 MHz stalled despite STA staying associated.
  // Sensor/XCLK/DMA still shut down independently; deep sleep stops all radios.
  const unsigned target=(cameraActive || transferring) ? 240:160;
  if (getCpuFrequencyMhz()!=target && !setCpuFrequencyMhz(target))
    Serial.println("POWER CPU frequency request failed");
  if (checked && uint32_t(now-checked)<5000) return;
  checked=now;
  if (!configured) {
    temp_sensor_config_t config=TSENS_CONFIG_DEFAULT(); config.dac_offset=TSENS_DAC_L1;
    configured=temp_sensor_set_config(config)==ESP_OK;
  }
  float temperature=NAN;
  if (configured && temp_sensor_start()==ESP_OK) {
    delay(10); // Allow the ADC to settle after powering the sensor up.
    const auto result=temp_sensor_read_celsius(&temperature);
    temp_sensor_stop();
    if (result!=ESP_OK) temperature=NAN;
  }
  if (isfinite(temperature) && temperature>=20 && temperature<=100) {
    const int value=lroundf(temperature*10); measured=value;
    if (value>=850) cooling=true;
    else if (value<=750) cooling=false;
    Serial.printf("POWER die_c=%.1f cpu_mhz=%u camera=%s cooling=%d\n",temperature,getCpuFrequencyMhz(),
                  cameraActive ? "active":"standby",int(cooling.load()));
  } else {
    measured=-32768;
    Serial.printf("POWER temperature unavailable (outside configured 20..100C range), cpu_mhz=%u\n",getCpuFrequencyMhz());
  }
}
}
