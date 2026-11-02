# Native JPEG HAL

**OV5640, 02/11/2026:** keep two bounded 2 MiB buffers, boot the sensor at
VGA for AF initialization, use reduced preview and switch to 2592×1944 only
for capture. `native_jpeg_eoi` now parses marker lengths and byte stuffing
to take the first real EOI. A backwards scan included a stale, older EOI in
the DMA padding; a received preview had two EOIs and repeated 14,491-byte
lengths despite a smaller current JPEG. Marker payloads, restart markers,
truncations and stale DMA padding are covered by the host test.
The text below records the previous OV3660 investigation.

Five upstream source/header files from Espressif `esp32-camera` **v2.0.4**;
source URLs and SHA-256 hashes are in `UPSTREAM.json`, Apache-2.0 in `LICENSE`.
This local HAL uses Arduino core 2.0.14's public camera API and its existing
sensor/SCCB code. The installed global Arduino SDK is unchanged.

Local changes in `cam_hal.c`: allocate **2 MiB** per JPEG frame instead of
`width*height/5` (629,145 bytes at 2048×1536), bound SOI/EOI reads and frame
timeouts, reject overflows, and provide a link anchor. From 2.5.0,
`AssistantCamera` uses **two** frame buffers so DVP keeps receiving while the
application copies the previous JPEG. The configured capacity stays 2 MiB
per buffer for native stills; preview copies only allocate their real JPEG size.
`ll_cam.c` uses a 32 KiB SRAM ring with 4 KiB EOF events (2 KiB DMA nodes,
within the S3 descriptor limit). The HAL drains it on core 1, away from the
Wi-Fi/BLE tasks on core 0. `native_camera_hal_diagnostic` reports event,
overflow, marker and good-frame counters even when Arduino disables warnings.
The former recursive NO-EOI retry is a loop with one deadline.

**2.4.3-camera:** the old raw-register scan for a free GDMA RX channel has
been replaced by ESP-IDF `gdma_new_channel` / `gdma_connect(CAM)` ownership.
The channel handle keeps the GDMA clock referenced until camera shutdown.
This fixes a concrete resource ownership defect: a camera omitted from the
IDF allocator could lose its channel/clock when another registered client
uses or releases GDMA. The selected RX is re-armed at each frame start;
other channels and the global peripheral reset are not touched. Disconnect
and release the channel after unregistering ISR handlers, before deleting
their queues. Failed allocation does not free `cam_obj` from the low-level
driver (the caller owns it).

The production wrapper `native_dma.h` is tested with simulated IDF clients:
shared clock lifetime, occupied channels, failures, and 100 open/close cycles.
This is an API-level regression test, not electrical validation. Physical
testing on 2026-10-29 confirmed that managed DMA alone did not fix the stream:
QS0/1 still failed, QS2 stalled, while changing only JPEG QS to 4 yielded 28
fully decoded native frames in 125 seconds, with no camera reinitialization.
Firmware 2.4.4 therefore uses QS4 for both preview and capture. XCLK and
native resolution are unchanged. Upstream source provenance
remains in UPSTREAM.json; modified upstream files are now `cam_hal.c`,
`ll_cam.c` and `ll_cam.h`. No global Arduino SDK source has been changed.

References: [Espressif managed allocation](https://github.com/espressif/esp32-camera/blob/master/target/esp32s3/ll_cam.c),
[IDF 4.4 GDMA ownership/clock lifecycle](https://github.com/espressif/esp-idf/blob/v4.4.6/components/driver/gdma.c),
[S3 Wi-Fi/GDMA stall report](https://github.com/espressif/esp32-camera/issues/620).
The last report concerns IDF 5.2; it is supporting context, not proof that
the exact same SDK regression occurs on the project's IDF 4.4.

Older preview copies are freed before allocating a new one. In 2.5.0 preview
uses VGA/QS16 and still uses QXGA/QS4, both with the 4:3 sensor window. Two
settling frames are discarded after each sensor mode/orientation change;
only JPEGs of the requested dimensions and a new timestamp are accepted.
These 2.5.0 changes are built/host-tested but not yet tested on the board.

The link map must resolve `cam_config` and `ll_cam_*` from this library,
not from the SDK archive. Hardware JPEGs exceeding the explicit 2 MiB safety
limit are rejected, never accepted as a truncated picture. Native resolution
was verified by decoding received JPEGs on the PC, not just reading metadata.
