#include "assistant_display.h"

#include <math.h>
#include "assistant_config.h"
#include "assistant_labels.h"

namespace {
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

void AssistantDisplay::begin() {
  tft_.init();
  tft_.setRotation(assistant_config::kDisplayRotation);
  tft_.invertDisplay(assistant_config::kInvertDisplay);
  tft_.fillScreen(kDark.background);
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
    snprintf(images, sizeof(images), "%u/10 anh", model.imageCount);
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
  if (darkTheme_ != model.darkTheme) {
    darkTheme_ = model.darkTheme;
    tft_.fillScreen(palette(darkTheme_).background);
    firstFrame_ = true;
  }
  uint32_t interval = model.state == assistant::State::Sleeping
      ? assistant_config::kSleepFrameIntervalMs : assistant_config::kFrameIntervalMs;
  if (!buffered_ && interval < 150) interval = 150;
  if (!firstFrame_ && !refresh && now - lastFrame_ < interval) return;
  lastFrame_ = now;
  if (refresh || firstFrame_) drawChrome(model, demo, muted);
  firstFrame_ = false;
  if (buffered_) {
    drawFace(face_, model, now);
    face_.pushSprite(kFaceX, kFaceY);
  } else {
    tft_.setViewport(kFaceX, kFaceY, kFaceWidth, kFaceHeight, true);
    drawFace(tft_, model, now);
    tft_.resetViewport();
  }
  drawProgress(model, now);
}
