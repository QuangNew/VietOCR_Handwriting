VietOCR OV5640 desktop test build
Open VietOCR.exe here, or use ../Run-VietOCR.cmd.
This small Windows launcher uses the Python environment and source in the parent project.
Keep it under VietHandOCR_API_Release/dist; it is not a standalone portable distribution.
The independent debug terminal stays open if the GUI crashes. Logs: ../.logs.
OCR is server-only. Open OCR Server, enter the host address and sign in with Google. No local weights/runtime are loaded.
Desktop UI: Sun Valley ttk 2.6.1 (MIT), neutral light/dark document workspace.
Keep ../desktop/vendor/sunvalley and its LICENSE with the source. See ../THIRD_PARTY_NOTICES.md.
Recommended firmware OV5640 3.2.1-resume: native sensor readback, resumable JPEG transfer, preview AF lock and idle camera standby.
Desktop: upload local images or open Chup OV5640; Tai tat ca exports the original image queue.
Bluetooth/WiFi dialogs resize; WiFi state refreshes every 3s; completed queue popup hides after 5s.
Camera settings > Tai lieu OCR: VGA UDP preview, native 5 MP QS6 stills, neutral image processing.
Image detail: rectangle, ellipse or freehand crop, rotate selection; original JPEG remains intact.
Den trang OCR creates a separate lossless PNG. Thang xam OCR is a sensor preset for preview and stills.
