#pragma once
#include <stddef.h>
#include <stdint.h>

static inline int native_jpeg_has_soi(const uint8_t *data, size_t length) {
    return data && length >= 3 && data[0] == 0xff && data[1] == 0xd8 && data[2] == 0xff;
}

static inline int native_jpeg_eoi(const uint8_t *data, size_t length) {
    if (!native_jpeg_has_soi(data,length)) return -1;
    // DMA padding may contain an older frame's EOI. Skip marker payloads
    // (EXIF/DQT may contain FF D9), then find the first real entropy-stream EOI.
    size_t at=2;
    int entropy=0;
    while (at+1<length) {
        if (entropy) { while (at<length && data[at]!=0xff) ++at; }
        if (at+1>=length || data[at]!=0xff) return -1;
        const size_t marker=at++;
        while (at<length && data[at]==0xff) ++at;
        if (at>=length) return -1;
        const uint8_t code=data[at++];
        if (code==0xd9) return (int)marker;
        if (entropy && (code==0 || (code>=0xd0 && code<=0xd7))) continue;
        if (code==1) continue;
        if (code==0 || code==0xd8 || at+2>length) return -1;
        const size_t size=((size_t)data[at]<<8)|data[at+1];
        if (size<2 || size>length-at) return -1;
        at+=size;
        entropy=code==0xda;
    }
    return -1;
}

static inline uint32_t native_jpeg_remaining(uint32_t budget, uint32_t elapsed) {
    return elapsed < budget ? budget - elapsed : 0;
}
