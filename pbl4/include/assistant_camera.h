#pragma once
#include <Arduino.h>
#include <BLECharacteristic.h>
#include <atomic>
#include "camera_transfer.h"
#include "camera_settings.h"
#include <Ov5640Autofocus.h>

// Camera/DVP runs on its own task; BLE callbacks only select/copy a bounded chunk.
class AssistantCamera : public BLECharacteristicCallbacks {
 public:
  struct Preview { uint8_t* data = nullptr; size_t size = 0; uint32_t sequence = 0; };
  void begin();
  bool command(const char* line, Print& response);
  bool viewing() const { return viewing_; }
  Preview takePreview();
  Preview copyPreview(uint32_t afterSequence = 0, size_t prefix=0, size_t suffix=0);
  Preview copyImage(uint32_t id);
  void previewDisplayed(bool success);
  void disconnect();
  String diagnostic();
  String configJson();
  bool configure(const char* json, String& error);
  camera_settings::Settings configuration();
  uint16_t previewWidth();
  unsigned maxFps();
  bool mirrored();
  bool flipped();
  const char* focusStatus() const;
  void onWrite(BLECharacteristic* characteristic) override;
  void onRead(BLECharacteristic* characteristic) override;
 private:
  SemaphoreHandle_t mutex_ = nullptr;
  std::atomic<bool> viewing_{false}, closing_{false}, previewReady_{false};
  bool initialized_ = false;
  bool previewMode_ = false;
  bool modeConfigured_ = false;
  camera_settings::Settings settings_, appliedSettings_;
  uint32_t settingsRevision_ = 1, appliedRevision_ = 0;
  bool settingsPending_ = false, persistPending_ = false, settingsSaved_ = false;
  String settingsError_;
  Ov5640Autofocus autofocus_;
  std::atomic<int> focusRaw_{-2};
  std::atomic<bool> focusPending_{false};
  uint32_t focusPollAt_ = 0;
  uint64_t modeAfterUs_ = 0;
  unsigned settlingFrames_ = 0;
  uint32_t statsAt_ = 0, statsFrames_ = 0;
  uint32_t previewSequence_ = 0;
  uint64_t previewAfterUs_ = 0;
  uint32_t requested_ = 0, pending_ = 0, frameId_ = 0, crc_ = 0;
  uint32_t readId_ = 0, readOffset_ = 0, readCount_ = 0, touched_ = 0;
  uint16_t width_ = 0, height_ = 0;
  uint8_t* image_ = nullptr;
  size_t size_ = 0;
  Preview preview_;
  String error_;
  static void task(void* context);
  void run();
  bool initialize();
  bool selectMode(bool preview);
  void setError(const String& error);
  void capture(uint32_t id);
  void clear();
  void saveSettings(const camera_settings::Settings& settings, uint32_t revision);
  void focusOnce();
};
