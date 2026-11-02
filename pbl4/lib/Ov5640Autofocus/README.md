# OV5640 autofocus

The exact AF firmware blob `src/ov5640_af_firmware.h` is from Espressif's
`esp32-camera`, commit `281d951f75b6559adec3cdb8cf076366da103880`.
See `UPSTREAM.json` for source URLs/hashes and `LICENSE` (Apache-2.0).
`autofocus_control.h` is a small mailbox controller adapted to the project's
existing Arduino 2.0.14 `sensor_t`, following the upstream AF sequence.
No global SDK patch or replacement of the camera driver is needed.

Load the blob once after sensor initialization, wait for firmware IDLE,
start continuous AF for preview, trigger a bounded single AF cycle before
capture, and hold lens position while switching to full resolution.
Failure to focus is reported separately from JPEG/DVP failure. Mailbox
status is not proof of optical sharpness: the lens must have a working VCM,
and a scene with useful contrast is needed.

All SCCB operations occur on the camera task. The mailbox controller has
host tests for firmware load, command sequencing, I²C failures, low contrast,
deadlines and timer rollover. Physical testing logs belong in `docs/OV5640.md`.
