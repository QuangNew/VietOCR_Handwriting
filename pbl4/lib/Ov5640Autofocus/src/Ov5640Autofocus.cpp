#include "Ov5640Autofocus.h"
#include "ov5640_af_firmware.h"
bool Ov5640Autofocus::begin(sensor_t* sensor) {
  reset();
  if (!sensor || sensor->id.PID != 0x5640) return false;
  bus_.sensor=sensor;
  return control_.begin(ov5640_af_firmware,sizeof(ov5640_af_firmware));
}
