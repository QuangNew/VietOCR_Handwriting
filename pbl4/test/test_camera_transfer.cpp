#include "camera_transfer.h"
#include <assert.h>
#include <stdio.h>
int main() {
  assert(camera_transfer::kNativeWidth == 2592);
  assert(camera_transfer::kNativeHeight == 1944);
  assert(camera_transfer::kJpegQuality >= 4 && camera_transfer::kJpegQuality <= 63);
  assert(!camera_transfer::freshFrame(999, 1000));
  assert(camera_transfer::freshFrame(1000, 1000));
  assert(camera_transfer::freshFrame(1001, 1000));
  assert(!camera_transfer::freshFrame(0, 0));
  assert(!camera_transfer::freshFrame(4999999999ULL, 5000000000ULL));
  const uint8_t bytes[] = "123456789";
  assert(camera_transfer::crc32(bytes, 9) == 0xcbf43926);
  uint8_t encoded[4]; camera_transfer::write32(encoded, 0xfedcba98);
  assert(camera_transfer::read32(encoded) == 0xfedcba98);
  assert(camera_transfer::chunkSize(1000, 0, 480) == 480);
  assert(camera_transfer::chunkSize(1000, 990, 480) == 10);
  assert(camera_transfer::chunkSize(1000, 1000, 10) == 0);
  assert(camera_transfer::chunkSize(1000, 1001, 10) == 0);
  assert(camera_transfer::chunkSize(1000, 0xffffffff, 10) == 0);
  assert(camera_transfer::chunkSize(1000, 0, 481) == 0);
  assert(camera_transfer::chunkSize(1000, 0, 0) == 0);
  const uint8_t preview[] = {0xff,0xd8,0xff,0xe0,0,4,0,0,0xff,0xc0,0,8,8,0,240,1,64,0};
  uint16_t width = 0, height = 0;
  assert(camera_transfer::jpegDimensions(preview, sizeof(preview), width, height));
  assert(width == 320 && height == 240);
  uint8_t still[sizeof(preview)];
  for (size_t i = 0; i < sizeof(preview); ++i) still[i] = preview[i];
  still[13] = 7; still[14] = 0x98; still[15] = 0x0a; still[16] = 0x20;
  assert(camera_transfer::jpegDimensions(still, sizeof(still), width, height));
  assert(width == 2592 && height == 1944);
  for (size_t size = 0; size < sizeof(preview); ++size)
    assert(!camera_transfer::jpegDimensions(preview, size, width, height));
  still[10] = 0xff;
  assert(!camera_transfer::jpegDimensions(still, sizeof(still), width, height));
  assert(!camera_transfer::jpegDimensions(bytes, 9, width, height));
  puts("PASS camera transfer: 41 checks (native quality, frame freshness and truncated JPEG headers)");
}
