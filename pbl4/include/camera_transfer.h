#pragma once
#include <stddef.h>
#include <stdint.h>

namespace camera_transfer {
constexpr uint16_t kNativeWidth = 2592, kNativeHeight = 1944;
// VGA uses the full 4:3 sensor window; JPEGs for OCR stay native 5 MP.
constexpr uint16_t kPreviewWidth = 640, kPreviewHeight = 480;
constexpr int kPreviewJpegQuality = 18;
constexpr int kJpegQuality = 8;
static_assert(kJpegQuality >= 4 && kJpegQuality <= 63,
              "Keep native JPEG within the bounded PSRAM buffers");
constexpr size_t kMaxImageBytes = 2 * 1024 * 1024;
inline bool freshFrame(uint64_t capturedUs, uint64_t requestedUs) {
  return capturedUs != 0 && capturedUs >= requestedUs;
}
constexpr size_t kMaxChunk = 480;
// Read the JPEG itself: camera_fb_t dimensions can describe the new sensor mode
// while a queued buffer still contains a frame from the previous mode.
inline bool jpegDimensions(const uint8_t* data, size_t size, uint16_t& width, uint16_t& height) {
  if (size < 4 || data[0] != 0xff || data[1] != 0xd8) return false;
  size_t at = 2;
  while (at + 3 < size) {
    if (data[at++] != 0xff) return false;
    while (at < size && data[at] == 0xff) ++at;
    if (at >= size) return false;
    const uint8_t marker = data[at++];
    if (marker == 0xda || marker == 0xd9) return false;
    if (marker == 0x01 || (marker >= 0xd0 && marker <= 0xd7)) continue;
    if (at + 2 > size) return false;
    const size_t length = (size_t(data[at]) << 8) | data[at + 1];
    if (length < 2 || length > size - at) return false;
    const bool sof = (marker >= 0xc0 && marker <= 0xcf && marker != 0xc4 && marker != 0xc8 && marker != 0xcc);
    if (sof) {
      if (length < 8) return false;
      height = (uint16_t(data[at + 3]) << 8) | data[at + 4];
      width = (uint16_t(data[at + 5]) << 8) | data[at + 6];
      return width && height;
    }
    at += length;
  }
  return false;
}
inline uint32_t crc32(const uint8_t* data, size_t size) {
  uint32_t value = 0xffffffff;
  for (size_t i = 0; i < size; ++i) {
    value ^= data[i];
    for (int bit = 0; bit < 8; ++bit)
      value = (value >> 1) ^ (0xedb88320u & (0u - (value & 1u)));
  }
  return value ^ 0xffffffff;
}
inline uint32_t read32(const uint8_t* bytes) {
  return uint32_t(bytes[0]) | (uint32_t(bytes[1]) << 8) |
         (uint32_t(bytes[2]) << 16) | (uint32_t(bytes[3]) << 24);
}
inline void write32(uint8_t* bytes, uint32_t value) {
  for (int i = 0; i < 4; ++i) bytes[i] = (value >> (8 * i)) & 0xff;
}
inline size_t chunkSize(size_t total, uint32_t offset, uint32_t wanted) {
  if (offset >= total || !wanted || wanted > kMaxChunk) return 0;
  return total - offset < wanted ? total - offset : wanted;
}
}  // namespace camera_transfer
