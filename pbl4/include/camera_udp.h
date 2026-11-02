#pragma once
#include "camera_transfer.h"
#include <string.h>
namespace camera_udp {
constexpr size_t kHeader=32, kDatagram=1200, kPayload=kDatagram-kHeader;
inline void write16(uint8_t* data,uint16_t value) { data[0]=value; data[1]=value>>8; }
inline size_t packet(uint8_t* output,size_t capacity,const uint8_t* jpeg,size_t size,
                     uint32_t stream,uint32_t sequence,uint32_t crc,size_t offset,uint16_t width,uint16_t height) {
  if (!output || !jpeg || !size || size>camera_transfer::kMaxImageBytes || offset>=size ||
      !stream || !sequence || !width || !height) return 0;
  const size_t count=size-offset<kPayload ? size-offset:kPayload;
  if (capacity<kHeader+count) return 0;
  memcpy(output,"VOJ1",4);
  camera_transfer::write32(output+4,stream); camera_transfer::write32(output+8,sequence);
  camera_transfer::write32(output+12,size); camera_transfer::write32(output+16,offset);
  camera_transfer::write32(output+20,crc);
  write16(output+24,width); write16(output+26,height); write16(output+28,count); write16(output+30,0);
  memcpy(output+kHeader,jpeg+offset,count); return kHeader+count;
}
}
