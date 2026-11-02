#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "camera_transfer.h"

// OV5640 controls; old OV3660 profiles are not loaded onto a different sensor.
// UI/control reference: easytarget/esp32-cam-webserver API.md (see CAMERA.md).
namespace camera_settings {
enum Key {
  PreviewWidth, PreviewQuality, StillQuality, MaxFps, Brightness, Contrast,
  Saturation, Sharpness, Denoise, WbMode, Aec, AeLevel, AecValue, Agc,
  AgcGain, SpecialEffect, Hmirror, Vflip, Lenc, Autofocus, Count
};
struct Field { const char* name; int32_t minimum, maximum, initial; };
static const Field kFields[Count] = {
  {"preview_width",320,2592,camera_transfer::kPreviewWidth}, {"preview_quality",4,63,camera_transfer::kPreviewJpegQuality}, {"still_quality",4,63,camera_transfer::kJpegQuality},
  {"max_fps",0,30,30}, {"brightness",-3,3,0}, {"contrast",-3,3,0},
  {"saturation",-4,4,0}, {"sharpness",-3,3,0}, {"denoise",0,8,0},
  {"wb_mode",0,4,0}, {"aec",0,1,1}, {"ae_level",-5,5,0},
  {"aec_value",0,1944,500}, {"agc",0,1,1}, {"agc_gain",0,64,0},
  {"special_effect",0,6,0}, {"hmirror",0,1,0}, {"vflip",0,1,0}, {"lenc",0,1,1},
  {"autofocus",0,1,1}
};
inline bool previewWidth(int32_t width) {
  return width == 320 || width == 640 || width == 800 || width == 1024 || width == 1600 || width == 2048 || width == 2592;
}
inline int find(const char* name) {
  for (int i=0; i<Count; ++i) if (!strcmp(name, kFields[i].name)) return i;
  return -1;
}
struct Settings {
  int32_t values[Count];
  Settings() { for (int i=0; i<Count; ++i) values[i] = kFields[i].initial; }
  int32_t operator[](Key key) const { return values[key]; }
  bool set(const char* name, int32_t value) {
    const int key = find(name);
    if (key < 0 || value < kFields[key].minimum || value > kFields[key].maximum ||
        (key == PreviewWidth && !previewWidth(value))) return false;
    values[key] = value; return true;
  }
  bool valid() const {
    for (int i=0; i<Count; ++i)
      if (values[i] < kFields[i].minimum || values[i] > kFields[i].maximum) return false;
    return previewWidth(values[PreviewWidth]);
  }
  bool operator==(const Settings& other) const { return !memcmp(values, other.values, sizeof(values)); }
};
// Explicit little-endian, versioned, CRC-protected single NVS record.
constexpr size_t kBlobBytes = 12 + 4 * Count;
inline void encode(const Settings& settings, uint8_t* output) {
  camera_transfer::write32(output, 0x43414d32);
  camera_transfer::write32(output+4, 2);
  for (int i=0; i<Count; ++i) camera_transfer::write32(output+8+i*4, uint32_t(settings.values[i]));
  camera_transfer::write32(output+kBlobBytes-4, camera_transfer::crc32(output, kBlobBytes-4));
}
inline bool decode(const uint8_t* input, size_t length, Settings& output) {
  if (length != kBlobBytes || camera_transfer::read32(input) != 0x43414d32 ||
      camera_transfer::read32(input+4) != 2 ||
      camera_transfer::read32(input+length-4) != camera_transfer::crc32(input,length-4)) return false;
  Settings next;
  for (int i=0; i<Count; ++i) next.values[i] = int32_t(camera_transfer::read32(input+8+i*4));
  if (!next.valid()) return false;
  output = next; return true;
}
}
