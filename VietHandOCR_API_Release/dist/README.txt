VietOCR OV5640 desktop test build
Open VietOCR.exe here, or use ../Run-VietOCR.cmd.
This small Windows launcher uses the Python environment, model and source in the parent project.
Keep it under VietHandOCR_API_Release/dist; it is not a standalone portable distribution.
The independent debug terminal stays open if the GUI crashes. Logs: ../.logs.
Model default: ../model/ml_s44_fp16.pth + model_config.json (ML_s44 release, 64px, V2c, FP32 compute).
Desktop UI: Sun Valley ttk 2.6.1 (MIT), neutral light/dark document workspace.
Keep ../desktop/vendor/sunvalley and its LICENSE with the source. See ../THIRD_PARTY_NOTICES.md.
Recommended firmware OV5640 3.2.0-focus-power: preview AF lock, full 5 MP JPEG, saved WiFi list and idle power policy.
Desktop: upload local images or open Chup OV5640; Tai tat ca exports the original image queue.
Bluetooth/WiFi dialogs resize; WiFi state refreshes every 3s; completed queue popup hides after 5s.
Camera settings > Tai lieu OCR: VGA UDP preview, native 5 MP QS6 stills, neutral image processing.
