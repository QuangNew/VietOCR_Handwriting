#include <cassert>
#include <cstdio>
#include <vector>
#include "../lib/NativeCameraHal/src/native_jpeg.h"

int main() {
    const uint8_t soi[] = {0xff, 0xd8, 0xff};
    assert(!native_jpeg_has_soi(nullptr, 3));
    assert(!native_jpeg_has_soi(soi, 0));
    assert(!native_jpeg_has_soi(soi, 1));
    assert(!native_jpeg_has_soi(soi, 2));
    assert(native_jpeg_has_soi(soi, 3));
    assert(native_jpeg_eoi(nullptr, 0) == -1);
    assert(native_jpeg_eoi(soi, 0) == -1);
    assert(native_jpeg_eoi(soi, 1) == -1);
    assert(native_jpeg_eoi(soi, 3) == -1);
    const uint8_t eoi[] = {0xff, 0xd9};
    assert(native_jpeg_eoi(eoi, 2) == -1);
    std::vector<uint8_t> frame(2 * 1024 * 1024, 0);
    frame[0]=0xff; frame[1]=0xd8; frame[2]=0xff; frame[3]=0xda; frame[4]=0; frame[5]=2;
    frame[700000] = 0xff; frame[700001] = 0xd9;
    assert(native_jpeg_eoi(frame.data(), frame.size()) == 700000);
    assert(native_jpeg_eoi(frame.data(), 700001) == -1);
    frame[800000]=0xff; frame[800001]=0xd9;
    assert(native_jpeg_eoi(frame.data(),frame.size())==700000);
    const uint8_t metadata[]={0xff,0xd8,0xff,0xe1,0,6,0xff,0xd9,0,0,0xff,0xda,0,2,0x12,0xff,0,0xd9,0xff,0xd0,0x12,0xff,0xd9};
    assert(native_jpeg_eoi(metadata,sizeof(metadata))==21);
    assert(native_jpeg_eoi(metadata,sizeof(metadata)-1)==-1);
    assert(native_jpeg_remaining(4000, 3999) == 1);
    assert(native_jpeg_remaining(4000, 4000) == 0);
    assert(native_jpeg_remaining(4000, 4500) == 0);
    assert(native_jpeg_remaining(4000, UINT32_MAX) == 0);
    const uint32_t start = UINT32_MAX - 999;
    assert(native_jpeg_remaining(4000, uint32_t(1000 - start)) == 2000);
    puts("native_jpeg: 20 checks passed (marker payloads, stuffing, restart, stale DMA padding)");
}
