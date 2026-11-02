#include "camera_settings.h"
#include <assert.h>
#include <stdio.h>
int main() {
  using namespace camera_settings;
  Settings settings;
  assert(settings.valid());
  assert(settings[MaxFps] == 30 && settings[PreviewWidth] == 640 && settings[Autofocus] == 1);
  for (int i=0; i<Count; ++i) {
    const Settings before = settings;
    assert(!settings.set(kFields[i].name, kFields[i].minimum - 1));
    assert(settings == before);
    assert(!settings.set(kFields[i].name, kFields[i].maximum + 1));
    assert(settings == before);
    assert(settings.set(kFields[i].name, kFields[i].minimum));
    assert(settings.valid());
    assert(settings.set(kFields[i].name, kFields[i].maximum));
    assert(settings.valid());
  }
  assert(!settings.set("preview_width", 720)); // cannot silently change 4:3 FOV
  assert(!settings.set("still_quality", 0)); // failed hardware profile
  assert(!settings.set("unknown", 1));
  uint8_t bytes[kBlobBytes]; encode(settings, bytes);
  Settings decoded;
  assert(decode(bytes, sizeof(bytes), decoded) && decoded == settings);
  const Settings prior = decoded;
  for (size_t length=0; length<sizeof(bytes); ++length) {
    assert(!decode(bytes, length, decoded)); assert(decoded == prior);
  }
  for (size_t at=0; at<sizeof(bytes); ++at) {
    bytes[at] ^= 1; assert(!decode(bytes, sizeof(bytes), decoded));
    assert(decoded == prior); bytes[at] ^= 1;
  }
  settings.values[PreviewWidth] = 1920; encode(settings, bytes);
  assert(!decode(bytes, sizeof(bytes), decoded));
  puts("camera_settings: OV5640 VGA/5MP/AF defaults, ranges, NVS CRC/version/truncation passed");
}
