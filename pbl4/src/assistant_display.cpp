#include "assistant_display.h"

#include <math.h>
#include <TJpg_Decoder.h>
#include "assistant_config.h"
#include "assistant_labels.h"

#if defined(VIETOCR_CAMERA) && VIETOCR_CAMERA
// Check AFTER TFT_eSPI's processor header has rewritten the user's macros.
static_assert(TFT_MISO != TFT_MOSI,
              "TFT MISO must use GPIO39; TFT_eSPI aliases MISO=-1 to MOSI on ESP32-S3");
#endif

namespace {
TFT_eSPI* cameraTft = nullptr;
bool drawJpegBlock(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t* pixels) {
  if (!cameraTft || y >= cameraTft->height()) return false;
  cameraTft->pushImage(x, y, w, h, pixels);
  return true;
}
constexpr uint16_t rgb(uint8_t red, uint8_t green, uint8_t blue) {
  return ((red & 0xf8) << 8) | ((green & 0xfc) << 3) | (blue >> 3);
}
struct Palette { uint16_t background, housing, panel, accent, text, muted, dim, border, error; };
constexpr Palette kDark = {rgb(12,22,19), rgb(25,60,43), rgb(7,16,13), rgb(130,223,163),
    rgb(223,239,228), rgb(145,173,155), rgb(61,105,77), rgb(39,67,49), rgb(247,143,128)};
constexpr Palette kLight = {rgb(244,247,245), rgb(217,235,223), rgb(255,255,255), rgb(29,115,76),
    rgb(25,57,46), rgb(83,109,93), rgb(115,151,126), rgb(184,211,193), rgb(180,52,43)};
const Palette& palette(bool dark) { return dark ? kDark : kLight; }
constexpr int kFaceX = 18, kFaceY = 42, kFaceWidth = 284, kFaceHeight = 132;

void drawLabel(TFT_eSPI& tft, const assistant_labels::Bitmap& label, int y, uint16_t color, uint16_t background) {
  tft.drawXBitmap((320 - label.width) / 2, y, label.data,
                  label.width, label.height, color, background);
}

template <typename Canvas>
void thickLine(Canvas& canvas, int x1, int y1, int x2, int y2, uint16_t color, int radius = 2) {
  for (int offset = -radius; offset <= radius; ++offset) {
    canvas.drawLine(x1, y1 + offset, x2, y2 + offset, color);
  }
  canvas.fillCircle(x1, y1, radius, color);
  canvas.fillCircle(x2, y2, radius, color);
}

template <typename Canvas>
void mouth(Canvas& canvas, int center, int y, int width, int depth, uint16_t color) {
  int previousX = center - width / 2, previousY = y;
  for (int i = 1; i <= 20; ++i) {
    const float position = i / 20.0f;
    const int x = center - width / 2 + static_cast<int>(width * position);
    const int nextY = y + static_cast<int>(4 * depth * position * (1 - position));
    thickLine(canvas, previousX, previousY, x, nextY, color);
    previousX = x;
    previousY = nextY;
  }
}

template <typename Canvas>
void drawFace(Canvas& canvas, const assistant::Model& model, uint32_t now) {
  using assistant::State;
  const auto& p = palette(model.darkTheme);
  canvas.fillRect(0, 0, kFaceWidth, kFaceHeight, p.background);
  canvas.fillRoundRect(16, 3, 252, 124, 30, p.housing);
  canvas.fillRoundRect(22, 9, 240, 112, 25, p.panel);
  canvas.drawRoundRect(16, 3, 252, 124, 30, p.dim);

  const float seconds = (now % 10000) * 0.001f;
  const bool sleeping = model.state == State::Sleeping;
  const bool happy = model.state == State::Received || model.state == State::Done;
  const bool processing = model.state == State::Processing;
  const int bob = static_cast<int>(sinf(seconds * 2) * (sleeping ? 1 : 2));
  const int eyeY = 55 + bob;
  const bool blink = now % 4200 >= 4050 && !processing;
  const uint16_t eyeColor = model.state == State::Error ? p.error : p.accent;

  const int eyes[] = {91, 193};
  for (int eyeX : eyes) {
    if (sleeping || blink) {
      thickLine(canvas, eyeX - 18, eyeY + 8, eyeX + 18, eyeY + 8, sleeping ? p.dim : eyeColor, 3);
    } else if (happy) {
      thickLine(canvas, eyeX - 17, eyeY + 9, eyeX, eyeY - 6, eyeColor, 3);
      thickLine(canvas, eyeX, eyeY - 6, eyeX + 17, eyeY + 9, eyeColor, 3);
    } else {
      const int gaze = static_cast<int>(sinf(seconds * (processing ? 4 : 1.1f)) * (processing ? 8 : 3));
      int height = 44;
      if (model.state == State::Awake && now - model.stateSince < 600) {
        height = 8 + (now - model.stateSince) * 36 / 600;
      }
      canvas.fillRoundRect(eyeX - 14 + gaze, eyeY - height / 2, 28, height, 9, eyeColor);
      if (model.state == State::Error) {
        const int slope = eyeX < 142 ? 7 : -7;
        thickLine(canvas, eyeX - 16, eyeY - 30, eyeX + 16, eyeY - 30 + slope, p.error);
      }
    }
  }

  canvas.setTextColor(p.dim, p.panel);
  if (sleeping) {
    thickLine(canvas, 133, 93 + bob, 151, 93 + bob, p.dim, 1);
    canvas.drawString("z", 219, 23 + bob, 2);
    canvas.drawString("Z", 237, 13 + bob, 2);
  } else if (processing) {
    for (int i = 0; i < 3; ++i) {
      canvas.fillCircle(127 + i * 15, 94 + bob, 3, (now / 180) % 3 == static_cast<uint32_t>(i) ? p.accent : p.dim);
    }
    if (model.progress >= 0) {
      char progress[8];
      snprintf(progress, sizeof(progress), "%d%%", model.progress);
      canvas.setTextColor(p.muted, p.panel);
      canvas.drawCentreString(progress, 142, 108, 1);
    }
  } else {
    mouth(canvas, 142, 88 + bob, happy ? 46 : 30,
          model.state == State::Error ? -9 : (happy ? 16 : 8), eyeColor);
    if (happy) {
      canvas.fillCircle(63, 84 + bob, 4, p.dim);
      canvas.fillCircle(221, 84 + bob, 4, p.dim);
    }
  }
  if (model.state == State::Done) {
    for (int i = 0; i < 4; ++i) {
      const int x = i < 2 ? 6 : 277;
      const int y = 20 + ((now / 35 + i * 23) % 90);
      canvas.drawLine(x - 3, y, x + 3, y, p.accent);
      canvas.drawLine(x, y - 3, x, y + 3, p.accent);
    }
  }
}
}  // namespace

AssistantDisplay::CameraFrame AssistantDisplay::renderCamera(const uint8_t* jpeg, size_t length) {
  uint16_t width = 0, height = 0;
  const JRESULT header = TJpgDec.getJpgSize(&width, &height, jpeg, length);
  if (header != JDR_OK) {
    Serial.printf("ERR TFT CAMERA JPEG header=%d bytes=%u\n", int(header), unsigned(length));
    return CameraFrame::Failed;
  }
  // A buffered UXGA frame may remain after changing the sensor to QVGA.
  // Skip it instead of aborting the whole preview on the first large frame.
  if (width != 320 || height != 240) {
    static uint32_t lastWarning = 0;
    if (millis() - lastWarning > 2000) {
      Serial.printf("CAMERA PREVIEW waiting for 320x240; JPEG is %ux%u\n", width, height);
      lastWarning = millis();
    }
    return CameraFrame::Waiting;
  }
  cameraMode_ = true;
  cameraTft = &tft_;
  TJpgDec.setJpgScale(1);
  TJpgDec.setSwapBytes(true);
  TJpgDec.setCallback(drawJpegBlock);
  const JRESULT result = TJpgDec.drawJpg(0, 0, jpeg, length);
  if (result != JDR_OK) Serial.printf("ERR TFT CAMERA JPEG decode=%d bytes=%u\n", int(result), unsigned(length));
  if (result == JDR_OK) recordFrame(true);
  return result == JDR_OK ? CameraFrame::Drawn : CameraFrame::Failed;
}

void AssistantDisplay::begin() {
  delay(120); // Let the panel supply settle before the library's hardware reset.
  setup_t setup{};
  tft_.getSetup(setup);
  Serial.printf("TFT CONFIG driver=0x%04x MOSI=%d MISO=%d SCK=%d CS=%d DC=%d RST=%d SPI=%ld Hz\n",
                setup.tft_driver,setup.pin_tft_mosi,setup.pin_tft_miso,setup.pin_tft_clk,
                setup.pin_tft_cs,setup.pin_tft_dc,setup.pin_tft_rst,long(setup.tft_spi_freq)*100000L);
  Serial.println("TFT INIT start");
  Serial.flush();
  tft_.init();
  // ILI9341 FRMCTR1: DIVA=0, RTNA=31 is nominally 61 Hz (closest
  // documented setting to 60 Hz). Panel scanning and incoming camera FPS
  // are independent. See ILI9341 datasheet, section 8.3.2.
  tft_.writecommand(ILI9341_FRMCTR1);
  tft_.writedata(0x00);
  tft_.writedata(0x1f);
  Serial.println("TFT refresh: nominal 61 Hz, animation target 60 FPS, boot color test removed");
  tft_.setRotation(assistant_config::kDisplayRotation);
  tft_.invertDisplay(assistant_config::kInvertDisplay);
#if defined(VIETOCR_CAMERA) && VIETOCR_CAMERA
  const uint16_t panelId = (uint16_t(tft_.readcommand8(0xD3,2)) << 8) | tft_.readcommand8(0xD3,3);
  Serial.printf("TFT READ ID=0x%04x (ILI9341 normally 0x9341; 0x0000/0xffff: check SDO/MISO wiring)\n",panelId);
#endif
  tft_.fillScreen(kDark.background);
  Serial.println("TFT INIT complete (SPI writes sent; visual confirmation required)");
  tft_.setTextWrap(false);
  face_.setTextWrap(false);
  face_.setColorDepth(16);
  buffered_ = face_.createSprite(kFaceWidth, kFaceHeight) != nullptr;
  if (!buffered_) {
    face_.setColorDepth(8);
    buffered_ = face_.createSprite(kFaceWidth, kFaceHeight) != nullptr;
  }
  if (!buffered_) Serial.println("WARN NO_SPRITE: using direct drawing");
}

void AssistantDisplay::setConnectionLabel(const String& label) {
  if (connectionLabel_ != label) {
    connectionLabel_ = label;
    firstFrame_ = true;
  }
}

void AssistantDisplay::drawChrome(const assistant::Model& model, bool demo, bool muted) {
  using namespace assistant_labels;
  using assistant::State;
  const auto& p = palette(model.darkTheme);
  tft_.fillRect(0, 0, 320, 38, p.background);
  tft_.setTextColor(p.accent, p.background);
  tft_.drawString("VIETOCR", 18, 9, 2);
  tft_.setTextColor(p.muted, p.background);
  tft_.drawRightString(demo ? "DEMO" : "BLE", 302, 9, 1);
  tft_.drawRightString(muted ? "MUTE" : "BEEP", 302, 21, 1);
  if (connectionLabel_.length()) tft_.drawCentreString(connectionLabel_, 176, 9, 1);
  if (model.imageCount) {
    char images[16];
    snprintf(images, sizeof(images), "%lu anh", (unsigned long)model.imageCount);
    tft_.drawCentreString(images, 178, 21, 1);
  }
  tft_.drawFastHLine(18, 35, 284, p.border);
  tft_.fillRect(0, 190, 320, 50, p.background);
  const Bitmap* title = &kIdleTitle;
  const Bitmap* detail = &kIdleDetail;
  switch (model.state) {
    case State::Sleeping: title = &kSleepTitle; detail = &kSleepDetail; break;
    case State::Awake: title = &kAwakeTitle; detail = &kAwakeDetail; break;
    case State::Received: title = &kReceivedTitle; detail = &kReceivedDetail; break;
    case State::Processing: title = &kProcessingTitle; detail = &kProcessingDetail; break;
    case State::Done: title = &kDoneTitle; detail = &kDoneDetail; break;
    case State::Error: title = &kErrorTitle; detail = &kErrorDetail; break;
    case State::Idle: break;
  }
  drawLabel(tft_, *title, 191, model.state == State::Error ? p.error : p.text, p.background);
  drawLabel(tft_, *detail, 219, p.muted, p.background);
}

void AssistantDisplay::drawProgress(const assistant::Model& model, uint32_t now) {
  const auto& p = palette(model.darkTheme);
  tft_.fillRoundRect(28, 181, 264, 5, 2, p.border);
  if (model.state == assistant::State::Processing) {
    if (model.progress >= 0) {
      const int width = model.progress * 264 / 100;
      if (width) tft_.fillRoundRect(28, 181, width, 5, 2, p.accent);
    } else {
      tft_.fillRoundRect(28 + (now / 12) % 224, 181, 40, 5, 2, p.accent);
    }
  } else if (model.state == assistant::State::Done) {
    tft_.fillRoundRect(28, 181, 264, 5, 2, p.accent);
  }
}

void AssistantDisplay::render(const assistant::Model& model, bool demo, bool muted,
                              uint32_t now, bool refresh) {
  if (cameraMode_) {
    cameraMode_ = false;
    tft_.fillScreen(palette(model.darkTheme).background);
    firstFrame_ = true;
  }
  if (darkTheme_ != model.darkTheme) {
    darkTheme_ = model.darkTheme;
    tft_.fillScreen(palette(darkTheme_).background);
    firstFrame_ = true;
  }
  uint32_t interval = model.state == assistant::State::Sleeping
      ? assistant_config::kSleepFrameIntervalMs * 1000 : assistant_config::kFrameIntervalUs;
  if (!buffered_ && interval < 150000) interval = 150000;
  const uint32_t frameAt = micros();
  if (!firstFrame_ && !refresh && frameAt - lastFrameUs_ < interval) return;
  lastFrameUs_ = frameAt;
  const bool fullFace = refresh || firstFrame_ || model.state == assistant::State::Done;
  if (refresh || firstFrame_) drawChrome(model, demo, muted);
  firstFrame_ = false;
  if (buffered_) {
    drawFace(face_, model, now);
    if (fullFace) face_.pushSprite(kFaceX, kFaceY);
    else face_.pushSprite(kFaceX + 50, kFaceY + 8, 50, 8, 205, 116);
  } else {
    tft_.setViewport(kFaceX, kFaceY, kFaceWidth, kFaceHeight, true);
    drawFace(tft_, model, now);
    tft_.resetViewport();
  }
  drawProgress(model, now);
  recordFrame(false);
}

void AssistantDisplay::recordFrame(bool camera) {
  const uint32_t now = millis();
  if (!statsAt_ || statsCamera_ != camera) {
    statsAt_ = now; statsFrames_ = 0; statsCamera_ = camera;
  }
  ++statsFrames_;
  const uint32_t elapsed = now - statsAt_;
  if (elapsed >= 5000) {
    Serial.printf("TFT FPS %s=%lu (animation target=60; camera limited by SPI/JPEG)\n",
                  camera ? "camera" : "assistant", (unsigned long)(statsFrames_ * 1000 / elapsed));
    statsAt_ = now; statsFrames_ = 0;
  }
}
