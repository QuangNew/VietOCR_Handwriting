#pragma once

#include <TFT_eSPI.h>
#include "assistant_logic.h"

class AssistantDisplay {
 public:
  void begin();
  void setConnectionLabel(const String& label);
  void render(const assistant::Model& model, bool demo, bool muted,
              uint32_t now, bool refresh = false);

 private:
  TFT_eSPI tft_;
  TFT_eSprite face_{&tft_};
  bool buffered_ = false;
  bool firstFrame_ = true;
  uint32_t lastFrame_ = 0;
  String connectionLabel_;

  void drawChrome(const assistant::Model& model, bool demo, bool muted);
  void drawProgress(const assistant::Model& model, uint32_t now);
};
