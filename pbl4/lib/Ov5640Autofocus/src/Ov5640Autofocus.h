#pragma once
#include <Arduino.h>
#include <sensor.h>
#include "autofocus_control.h"
struct Ov5640FocusBus {
  sensor_t* sensor = nullptr;
  bool write(uint16_t reg, uint8_t value) { return sensor && sensor->set_reg(sensor,reg,0xff,value) == 0; }
  int read(uint16_t reg) { return sensor ? sensor->get_reg(sensor,reg,0xff) : -1; }
  uint32_t millis() { return ::millis(); }
  void delay(unsigned ms) { vTaskDelay(pdMS_TO_TICKS(ms ? ms : 1)); }
};
class Ov5640Autofocus {
 public:
  Ov5640Autofocus(): control_(bus_) {}
  bool begin(sensor_t* sensor);
  void reset() { control_.reset(); bus_.sensor=nullptr; }
  bool ready() const { return control_.ready(); }
  bool continuous() { return control_.continuous(); }
  bool pause() { return control_.pause(); }
  bool single(uint32_t timeoutMs=4000) { return control_.single(timeoutMs); }
  bool zone(unsigned x, unsigned y, bool mirror, bool flip) { return control_.zone(x,y,mirror,flip); }
  int status() { return control_.status(); }
  autofocus::Error error() const { return control_.error(); }
 private:
  Ov5640FocusBus bus_;
  autofocus::Control<Ov5640FocusBus> control_;
};
