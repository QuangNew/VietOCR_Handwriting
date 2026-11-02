#include "camera_udp.h"
#include <assert.h>
#include <stdio.h>
#include <vector>
int main() {
  std::vector<uint8_t> jpeg(10007);for (size_t i=0;i<jpeg.size();++i) jpeg[i]=i;
  uint8_t packet[camera_udp::kDatagram];std::vector<uint8_t> decoded;
  const auto crc=camera_transfer::crc32(jpeg.data(),jpeg.size());
  for (size_t at=0;at<jpeg.size();at+=camera_udp::kPayload) {
    const size_t size=camera_udp::packet(packet,sizeof(packet),jpeg.data(),jpeg.size(),42,99,crc,at,640,480);
    assert(size>32 && size<=1200 && !memcmp(packet,"VOJ1",4));
    assert(camera_transfer::read32(packet+4)==42 && camera_transfer::read32(packet+8)==99);
    assert(camera_transfer::read32(packet+12)==jpeg.size() && camera_transfer::read32(packet+16)==at);
    assert(camera_transfer::read32(packet+20)==crc && (packet[28]|packet[29]<<8)==int(size-32));
    decoded.insert(decoded.end(),packet+32,packet+size);
  }
  assert(decoded==jpeg);
  assert(!camera_udp::packet(packet,31,jpeg.data(),jpeg.size(),42,99,crc,0,640,480));
  assert(!camera_udp::packet(packet,sizeof(packet),jpeg.data(),jpeg.size(),42,99,crc,jpeg.size(),640,480));
  assert(!camera_udp::packet(packet,sizeof(packet),jpeg.data(),camera_transfer::kMaxImageBytes+1,42,99,crc,0,640,480));
  puts("PASS UDP JPEG: MTU bounds, metadata, offsets, CRC, reconstruction, invalid sizes");
}
