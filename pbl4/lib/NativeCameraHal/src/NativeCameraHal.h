#pragma once
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
// Also anchors this HAL object before the Arduino SDK camera archive is linked.
void native_camera_hal_require(void);
// Bounded, credential-free snapshot; remains available after a failed capture.
void native_camera_hal_diagnostic(char *output, size_t capacity);
#ifdef __cplusplus
}
#endif
