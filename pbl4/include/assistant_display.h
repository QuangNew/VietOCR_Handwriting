#pragma once

#include <TFT_eSPI.h>
#include "assistant_logic.h"

class AssistantDisplay {
 public:
  void begin();
  void powerDown() { tft_.writecommand(0x28); tft_.writecommand(0x10); }
  void setConnectionLabel(const String& label);
  enum class CameraFrame { Waiting, Drawn, Failed };
  CameraFrame renderCamera(const uint8_t* jpeg, size_t length);
  void render(const assistant::Model& model, bool demo, bool muted,
              uint32_t now, bool refresh = false);

 private:
  TFT_eSPI tft_;
  TFT_eSprite face_{&tft_};
  bool buffered_ = false;
  bool firstFrame_ = true;
  bool cameraMode_ = false;
  bool darkTheme_ = true;
  uint32_t lastFrameUs_ = 0;
  uint32_t statsAt_ = 0, statsFrames_ = 0;
  bool statsCamera_ = false;
  String connectionLabel_;

  void drawChrome(const assistant::Model& model, bool demo, bool muted);
  void drawProgress(const assistant::Model& model, uint32_t now);
  void recordFrame(bool camera);
};
