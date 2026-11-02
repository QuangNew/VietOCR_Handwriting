#include "assistant_camera.h"
#include "assistant_config.h"
#include <esp_camera.h>
#include <esp_heap_caps.h>
#include <esp_timer.h>
#include <Preferences.h>
#include <cJSON.h>
#include <string.h>

#ifndef VIETOCR_CAMERA
#define VIETOCR_CAMERA 0
#endif
#ifndef CAM_PWDN
#define CAM_PWDN -1
#endif

#if VIETOCR_CAMERA
#include <NativeCameraHal.h>
constexpr bool cameraPin(int pin) {
  return pin == 4 || pin == 5 || pin == 6 || pin == 7 || pin == 8 || pin == 9 ||
         pin == 10 || pin == 11 || pin == 12 || pin == 13 || pin == 15 ||
         pin == 16 || pin == 17 || pin == 18 || (CAM_PWDN >= 0 && pin == CAM_PWDN);
}
static_assert(!cameraPin(TFT_MOSI) && !cameraPin(TFT_MISO) && !cameraPin(TFT_SCLK) &&
              !cameraPin(TFT_CS) && !cameraPin(TFT_DC) && !cameraPin(TFT_RST) &&
              !cameraPin(assistant_config::kBuzzerPin), "Camera conflicts with TFT/buzzer GPIO: rewire first");
#endif

void AssistantCamera::setError(const String& error) {
  xSemaphoreTake(mutex_, portMAX_DELAY); error_ = error; xSemaphoreGive(mutex_);
}

uint16_t AssistantCamera::previewWidth() {
  return configuration()[camera_settings::PreviewWidth];
}
unsigned AssistantCamera::maxFps() {
  return configuration()[camera_settings::MaxFps];
}
bool AssistantCamera::mirrored() {
  return configuration()[camera_settings::Hmirror];
}
bool AssistantCamera::flipped() {
  return configuration()[camera_settings::Vflip];
}
camera_settings::Settings AssistantCamera::configuration() {
  if (!mutex_) return camera_settings::Settings();
  xSemaphoreTake(mutex_, portMAX_DELAY); const auto value = settings_; xSemaphoreGive(mutex_); return value;
}
String AssistantCamera::configJson() {
  if (!mutex_) return "{}";
  xSemaphoreTake(mutex_, portMAX_DELAY);
  const auto current = settings_; const uint32_t revision = settingsRevision_, applied = appliedRevision_;
  const bool saved = settingsSaved_; const String error = settingsError_;
  xSemaphoreGive(mutex_);
  cJSON* root = cJSON_CreateObject();
  if (!root) return "{}";
  cJSON_AddNumberToObject(root, "schema", 2);
  cJSON_AddStringToObject(root, "sensor", "OV5640");
  cJSON_AddStringToObject(root, "focus_status", focusStatus());
  cJSON_AddNumberToObject(root, "still_width", camera_transfer::kNativeWidth);
  cJSON_AddNumberToObject(root, "still_height", camera_transfer::kNativeHeight);
  cJSON_AddStringToObject(root, "firmware", assistant_config::kFirmwareVersion);
  cJSON_AddNumberToObject(root, "revision", revision);
  cJSON_AddNumberToObject(root, "applied_revision", applied);
  cJSON_AddBoolToObject(root, "saved", saved);
  cJSON_AddStringToObject(root, "error", error.c_str());
  auto* settings = cJSON_AddObjectToObject(root, "settings");
  auto* defaults = cJSON_AddObjectToObject(root, "defaults");
  for (int i=0; i<camera_settings::Count; ++i) {
    cJSON_AddNumberToObject(settings, camera_settings::kFields[i].name, current.values[i]);
    cJSON_AddNumberToObject(defaults, camera_settings::kFields[i].name, camera_settings::kFields[i].initial);
  }
  char* json = cJSON_PrintUnformatted(root);
  String result = json ? json : "{}";
  free(json); cJSON_Delete(root); return result;
}
bool AssistantCamera::configure(const char* json, String& error) {
  if (!mutex_) { error = "CAMERA_MEMORY"; return false; }
  cJSON* root = cJSON_Parse(json);
  auto* patch = root ? cJSON_GetObjectItemCaseSensitive(root, "settings") : nullptr;
  auto* persist = root ? cJSON_GetObjectItemCaseSensitive(root, "persist") : nullptr;
  if (!cJSON_IsObject(root) || !cJSON_IsObject(patch) || (persist && !cJSON_IsBool(persist))) {
    error = "CAMERA_CONFIG: expected settings object and optional persist boolean";
    cJSON_Delete(root); return false;
  }
  for (auto* item = root->child; item; item = item->next) {
    if (strcmp(item->string, "settings") && strcmp(item->string, "persist")) {
      error = "CAMERA_CONFIG: unknown property"; cJSON_Delete(root); return false;
    }
  }
  xSemaphoreTake(mutex_, portMAX_DELAY);
  auto next = settings_;
  bool valid = true;
  for (auto* item = patch->child; item; item = item->next) {
    if (!cJSON_IsNumber(item) || item->valuedouble != item->valueint || !next.set(item->string, item->valueint)) {
      error = String("CAMERA_SETTING: invalid value for ") + item->string; valid = false; break;
    }
  }
  if (valid && requested_) { error = "CAMERA_BUSY: finish current photo first"; valid = false; }
  if (valid) {
    settings_ = next;
    if (!++settingsRevision_) settingsRevision_ = 1;
    settingsPending_ = true; persistPending_ = persist && cJSON_IsTrue(persist);
    settingsSaved_ = false; settingsError_ = ""; previewReady_ = false;
  }
  xSemaphoreGive(mutex_);
  cJSON_Delete(root); return valid;
}
void AssistantCamera::saveSettings(const camera_settings::Settings& settings, uint32_t revision) {
  uint8_t bytes[camera_settings::kBlobBytes], verify[sizeof(bytes)];
  camera_settings::encode(settings, bytes);
  Preferences saved; camera_settings::Settings confirmed;
  bool ok = saved.begin("vietocr-camera", false);
  if (ok) {
    ok = saved.putBytes("profile5640", bytes, sizeof(bytes)) == sizeof(bytes) &&
        saved.getBytes("profile5640", verify, sizeof(verify)) == sizeof(verify) &&
        camera_settings::decode(verify, sizeof(verify), confirmed) && confirmed == settings;
    saved.end();
  }
  xSemaphoreTake(mutex_, portMAX_DELAY);
  if (settingsRevision_ == revision) {
    persistPending_ = false; settingsSaved_ = ok;
    if (!ok) settingsError_ = "CAMERA_SAVE: cannot verify NVS record; settings are active in RAM";
  }
  xSemaphoreGive(mutex_);
  Serial.println(ok ? "CAMERA CONFIG saved and verified (NVS)" : "CAMERA CONFIG save failed");
}

void AssistantCamera::begin() {
  mutex_ = xSemaphoreCreateMutex();
  if (!mutex_) { error_ = "CAMERA_MEMORY"; return; }
#if VIETOCR_CAMERA
  if (xTaskCreate(task, "VietOCR-Camera", 6144, this, 1, nullptr) != pdPASS)
    error_ = "CAMERA_TASK";
#else
  error_ = "CAMERA_DISABLED: build esp32-s3-cam-ov5640";
#endif
}

bool AssistantCamera::initialize() {
#if VIETOCR_CAMERA
  if (initialized_) return true;
  if (!psramFound()) { setError("CAMERA_PSRAM: requires N16R8 PSRAM"); return false; }
  camera_config_t config{};
  // This S3-WROOM layout was verified by the user's OV3660 JPEG probe, 2026-10-26.
  config.pin_pwdn = CAM_PWDN; config.pin_reset = -1;
  config.pin_xclk = 15; config.pin_sccb_sda = 4; config.pin_sccb_scl = 5;
  config.pin_d0 = 11; config.pin_d1 = 9; config.pin_d2 = 8; config.pin_d3 = 10;
  config.pin_d4 = 12; config.pin_d5 = 18; config.pin_d6 = 17; config.pin_d7 = 16;
  config.pin_vsync = 6; config.pin_href = 7; config.pin_pclk = 13;
  config.xclk_freq_hz = 20000000;
  config.ledc_timer = LEDC_TIMER_1; config.ledc_channel = LEDC_CHANNEL_2;
  // HAL allocates fixed 2 MiB buffers regardless of the initial dimensions.
  // Boot at VGA so AF firmware and DVP settle on the fast preview clock.
  config.pixel_format = PIXFORMAT_JPEG; config.frame_size = FRAMESIZE_VGA;
  // Allocate for the largest still once. Two buffers keep DVP running while
  // the consumer copies the previous frame; sensor output can be VGA/QXGA.
  config.jpeg_quality = camera_transfer::kJpegQuality; config.fb_count = 2;
  config.fb_location = CAMERA_FB_IN_PSRAM; config.grab_mode = CAMERA_GRAB_LATEST;
  native_camera_hal_require();
  const esp_err_t status = esp_camera_init(&config);
  if (status != ESP_OK) {
    setError(String("CAMERA_INIT: ") + esp_err_to_name(status) + "; check board pinout/power");
    return false;
  }
  initialized_ = true;
  modeConfigured_ = false;
  sensor_t* sensor = esp_camera_sensor_get();
  if (!sensor || sensor->id.PID != 0x5640) {
    setError("CAMERA_SENSOR: this profile requires OV5640");
    esp_camera_deinit();
    initialized_ = false;
    return false;
  }
  // Preserve natural colour/detail. Maximum gain/exposure/saturation would
  // produce noise or clipped text, so these controls remain automatic/neutral.
  if (sensor->set_whitebal(sensor, 1) || sensor->set_gain_ctrl(sensor, 1) ||
      sensor->set_exposure_ctrl(sensor, 1) || sensor->set_brightness(sensor, 0) ||
      sensor->set_contrast(sensor, 0) || sensor->set_saturation(sensor, 0) ||
      sensor->set_quality(sensor, camera_transfer::kJpegQuality)) {
    setError("CAMERA_PROFILE: cannot configure native sensor profile");
    esp_camera_deinit(); initialized_ = false; return false;
  }
  setError("");
  const uint32_t afStarted=millis();
  const bool afReady=autofocus_.begin(sensor);
  focusRaw_=afReady ? autofocus_.status() : -1;
  Serial.printf("CAMERA AF firmware=%s load_ms=%lu status=0x%x error=%d\n", afReady ? "READY" : "FAILED",
      (unsigned long)(millis()-afStarted), int(focusRaw_.load()), int(autofocus_.error()));
  Serial.printf("CAMERA INIT OK (waiting for JPEG) sensor=0x%x PSRAM=%u preview=%ux%u QS=%d still=2592x1944 QS=%d\n",
                sensor->id.PID, ESP.getPsramSize(), camera_transfer::kPreviewWidth,
                camera_transfer::kPreviewHeight, camera_transfer::kPreviewJpegQuality, camera_transfer::kJpegQuality);
  return true;
#else
  return false;
#endif
}

bool AssistantCamera::selectMode(bool preview) {
#if VIETOCR_CAMERA
  if (!initialize()) {
    xSemaphoreTake(mutex_, portMAX_DELAY); settingsError_ = error_; settingsPending_ = false; xSemaphoreGive(mutex_);
    return false;
  }
  xSemaphoreTake(mutex_, portMAX_DELAY);
  const auto settings = settings_; const uint32_t revision = settingsRevision_;
  const bool persist = persistPending_;
  xSemaphoreGive(mutex_);
  if (modeConfigured_ && previewMode_ == preview && appliedRevision_ == revision) return true;
  using namespace camera_settings;
  const unsigned width = preview ? settings[PreviewWidth] : camera_transfer::kNativeWidth;
  framesize_t size = FRAMESIZE_QSXGA;
  switch (width) {
    case 320: size = FRAMESIZE_QVGA; break;
    case 640: size = FRAMESIZE_VGA; break;
    case 800: size = FRAMESIZE_SVGA; break;
    case 1024: size = FRAMESIZE_XGA; break;
    case 1600: size = FRAMESIZE_UXGA; break;
    case 2048: size = FRAMESIZE_QXGA; break;
  }
  sensor_t* sensor = esp_camera_sensor_get();
  if (!sensor || sensor->set_framesize(sensor, size) ||
      // This Arduino SDK names 2560x1920 "QSXGA". Program the real active
      // window explicitly: full 2592x1944 still, same field of view for preview.
      (width==2592 && sensor->set_res_raw(sensor,0,0,2623,1951,width<=1296 ? 8:16,width<=1296 ? 2:4,
          width<=1296 ? 2060:2844,width<=1296 ? 984:1968,width,width*3/4,
          width!=2592 && width!=1296,width<=1296)) ||
      sensor->set_quality(sensor, settings[preview ? PreviewQuality : StillQuality]) ||
      sensor->set_brightness(sensor, settings[Brightness]) || sensor->set_contrast(sensor, settings[Contrast]) ||
      sensor->set_saturation(sensor, settings[Saturation]) || sensor->set_sharpness(sensor, settings[Sharpness]) ||
      sensor->set_denoise(sensor, settings[Denoise]) || sensor->set_whitebal(sensor, 1) ||
      sensor->set_awb_gain(sensor, 1) || sensor->set_wb_mode(sensor, settings[WbMode]) ||
      sensor->set_exposure_ctrl(sensor, settings[Aec]) || sensor->set_ae_level(sensor, settings[AeLevel]) ||
      (!settings[Aec] && sensor->set_aec_value(sensor, settings[AecValue])) ||
      sensor->set_gain_ctrl(sensor, settings[Agc]) ||
      (!settings[Agc] && sensor->set_agc_gain(sensor, settings[AgcGain])) ||
      sensor->set_special_effect(sensor, settings[SpecialEffect]) || sensor->set_lenc(sensor, settings[Lenc]) ||
      sensor->set_hmirror(sensor, settings[Hmirror]) || sensor->set_vflip(sensor, settings[Vflip])) {
    setError("CAMERA_PROFILE: cannot apply sensor settings");
    xSemaphoreTake(mutex_, portMAX_DELAY); settingsError_ = error_; settingsPending_ = false; xSemaphoreGive(mutex_);
    modeConfigured_ = false;
    return false;
  }
  if (settings[Autofocus] && autofocus_.ready() && preview) {
    if (!autofocus_.continuous()) Serial.printf("CAMERA AF continuous failed error=%d\n", int(autofocus_.error()));
    focusRaw_=autofocus_.status();
  } else if (!settings[Autofocus]) {
    if (autofocus_.ready()) autofocus_.pause();
    focusRaw_=-3;
  }
  // Native and VGA use the same 4:3 sensor window. Reject queued exposures
  // from before ALL register writes, as well as JPEGs with old dimensions.
  modeAfterUs_ = esp_timer_get_time();
  settlingFrames_ = 2;
  previewMode_ = preview;
  modeConfigured_ = true;
  appliedSettings_ = settings;
  statsAt_ = millis(); statsFrames_ = 0;
  xSemaphoreTake(mutex_, portMAX_DELAY);
  Preview old = preview_; preview_ = Preview{}; previewReady_ = false;
  appliedRevision_ = revision; settingsPending_ = settingsRevision_ != revision; settingsError_ = "";
  error_ = "";
  xSemaphoreGive(mutex_);
  free(old.data);
  if (persist) saveSettings(settings, revision);
  Serial.printf("CAMERA MODE %s %ux%u QS=%d mirror=%d flip=%d\n", preview ? "preview" : "still",
      width, width * 3 / 4, settings[preview ? PreviewQuality : StillQuality], settings[Hmirror], settings[Vflip]);
  return true;
#else
  return false;
#endif
}

void AssistantCamera::task(void* context) { static_cast<AssistantCamera*>(context)->run(); }
void AssistantCamera::run() {
  Preferences saved;
  if (saved.begin("vietocr-camera", true)) {
    camera_settings::Settings loaded;
    uint8_t bytes[camera_settings::kBlobBytes];
    const bool valid = saved.isKey("profile5640") && saved.getBytesLength("profile5640") == sizeof(bytes) &&
        saved.getBytes("profile5640", bytes, sizeof(bytes)) == sizeof(bytes) &&
        camera_settings::decode(bytes, sizeof(bytes), loaded);
    if (!valid) {
      const uint8_t orientation = saved.getUChar("orientation", 0);
      loaded.set("hmirror", !!(orientation & 1)); loaded.set("vflip", !!(orientation & 2));
    }
    xSemaphoreTake(mutex_, portMAX_DELAY); settings_ = loaded; settingsSaved_ = valid; xSemaphoreGive(mutex_);
    saved.end();
    Serial.println(valid ? "CAMERA OV5640 profile loaded (NVS)" : "CAMERA OV5640 defaults: reduced preview target=15FPS, still=5MP, autofocus=on");
  }
  unsigned missingFrames = 0, rejectedFrames = 0;
  for (;;) {
    uint32_t shot;
    xSemaphoreTake(mutex_, portMAX_DELAY);
    const bool close = closing_;
    const bool configure = settingsPending_;
    shot = pending_; pending_ = 0;
    xSemaphoreGive(mutex_);
    if (close) { clear(); shot = 0; }
    if (shot) capture(shot);
    else if (focusPending_.exchange(false)) {
      if (selectMode(true)) {
        focusOnce();
        if (appliedSettings_[camera_settings::Autofocus] && autofocus_.ready()) autofocus_.continuous();
      }
    }
    else if (configure && !viewing_) { selectMode(true); }
    else if (viewing_ && !selectMode(true)) { viewing_ = false; }
    else if (viewing_) {
      if (appliedSettings_[camera_settings::Autofocus] && autofocus_.ready() && millis()-focusPollAt_>=250) {
        focusRaw_=autofocus_.status(); focusPollAt_=millis();
      }
      camera_fb_t* frame = esp_camera_fb_get();
      if (frame) {
        missingFrames = 0;
        if (settlingFrames_) {
          --settlingFrames_; esp_camera_fb_return(frame); continue;
        }
        xSemaphoreTake(mutex_, portMAX_DELAY);
        const uint64_t after = previewAfterUs_;
        xSemaphoreGive(mutex_);
        const uint64_t captured = uint64_t(frame->timestamp.tv_sec) * 1000000ULL + frame->timestamp.tv_usec;
        if (!camera_transfer::freshFrame(captured, after > modeAfterUs_ ? after : modeAfterUs_)) {
          // A single framebuffer can retain a queued exposure while closed.
          // Reopening must never show that previous session's image.
          esp_camera_fb_return(frame);
          vTaskDelay(pdMS_TO_TICKS(1));
          continue;
        }
        Preview next;
        // Drop the older local copy BEFORE allocating the next full JPEG.
        // HTTP owns its separate snapshot. Driver buffers stay allocated at
        // still capacity; preview copies are only the current VGA JPEG length.
        xSemaphoreTake(mutex_, portMAX_DELAY);
        Preview discarded = preview_; preview_ = Preview{};
        xSemaphoreGive(mutex_);
        free(discarded.data);
        uint16_t width = 0, height = 0;
        if (frame->format == PIXFORMAT_JPEG && frame->len <= camera_transfer::kMaxImageBytes &&
            camera_transfer::jpegDimensions(frame->buf, frame->len, width, height) &&
            width == appliedSettings_[camera_settings::PreviewWidth] && height == width * 3 / 4) {
          next.data = static_cast<uint8_t*>(heap_caps_malloc(frame->len, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
          if (next.data) { memcpy(next.data, frame->buf, frame->len); next.size = frame->len; }
        }
        esp_camera_fb_return(frame);
        if (next.data) {
          rejectedFrames = 0;
          xSemaphoreTake(mutex_, portMAX_DELAY);
          Preview old = preview_;
          if (viewing_ && appliedRevision_ == settingsRevision_) {
            next.sequence = ++previewSequence_; if (!next.sequence) next.sequence = ++previewSequence_;
            preview_ = next;
            if (!previewReady_) Serial.printf("CAMERA FIRST JPEG bytes=%u %ux%u\n", unsigned(next.size), width, height);
            previewReady_ = true;
          } else { old = next; }
          xSemaphoreGive(mutex_);
          free(old.data);
          ++statsFrames_;
          const uint32_t now = millis();
          if (now - statsAt_ >= 5000) {
            Serial.printf("CAMERA CAPTURE fps=%.1f JPEG_bytes=%u free_psram=%u\n",
                statsFrames_ * 1000.0f / (now - statsAt_), unsigned(next.size), ESP.getFreePsram());
            statsAt_ = now; statsFrames_ = 0;
          }
        } else if (++rejectedFrames >= 3) {
          setError("CAMERA_PREVIEW: invalid frames or no PSRAM buffer");
          viewing_ = false;
        }
      } else if (++missingFrames == 1) {
        // Arduino's old S3 GDMA can stall after a Wi-Fi reconnect. Reset only
        // the camera once; never reboot the assistant or loop unboundedly.
        Serial.println("CAMERA RECOVER: no frame; reinitializing driver once");
        sensor_t* sensor = esp_camera_sensor_get();
        if (sensor) {
          // The sensor's compressed-length counter separates "no JPEG was
          // generated" from "JPEG generated but the ESP32 DMA did not receive".
          const int hi = sensor->get_reg(sensor, 0x4414, 0xff);
          const int mid = sensor->get_reg(sensor, 0x4415, 0xff);
          const int lo = sensor->get_reg(sensor, 0x4416, 0xff);
          const int bytes = hi < 0 || mid < 0 || lo < 0 ? -1 : (hi << 16) | (mid << 8) | lo;
          Serial.printf("CAMERA SENSOR QS=%d JFIFO=0x%x JPEG_BYTES=%d compression=%d free_psram=%u\n",
              sensor->get_reg(sensor, 0x4407, 0x3f), sensor->get_reg(sensor, 0x4417, 0xff), bytes,
              sensor->get_reg(sensor, 0x3821, 0x20), ESP.getFreePsram());
        }
        autofocus_.reset(); focusRaw_=-2;
        esp_camera_deinit(); initialized_ = false;
      } else {
        char detail[160] = "camera disabled";
#if VIETOCR_CAMERA
        native_camera_hal_diagnostic(detail, sizeof(detail));
#endif
        setError(String("CAMERA_PREVIEW: no JPEG; ") + detail);
        Serial.printf("CAMERA PREVIEW FAILED %s\n", detail);
        viewing_ = false;
      }
    } else { missingFrames = 0; rejectedFrames = 0; }
    xSemaphoreTake(mutex_, portMAX_DELAY);
    const bool expired = image_ && millis() - touched_ > 120000;
    xSemaphoreGive(mutex_);
    if (expired) clear();
    vTaskDelay(pdMS_TO_TICKS(viewing_ ? 1 : 20));
  }
}

void AssistantCamera::capture(uint32_t id) {
  const uint32_t started = millis();
  // Focus while the sensor is in fast preview mode, then hold the lens while
  // switching to full 5 MP. Never autofocus from a BLE or HTTP callback.
  if (!selectMode(true)) return;
  if (appliedSettings_[camera_settings::Autofocus]) focusOnce();
  if (!selectMode(false)) return;
  uint64_t after = esp_timer_get_time();
  // Drop the preview copy before allocating a still. Keep driver frame buffers
  // alive at native resolution and take the next current full-quality exposure.
  xSemaphoreTake(mutex_, portMAX_DELAY);
  Preview oldPreview = preview_; preview_ = Preview{}; previewReady_ = false;
  xSemaphoreGive(mutex_);
  free(oldPreview.data);
  camera_fb_t* frame = nullptr;
  uint16_t width = 0, height = 0;
  bool recovered=false;
  unsigned invalid=0;
  for (int attempt = 0; attempt < 16 && millis() - started < 24000; ++attempt) {
    xSemaphoreTake(mutex_, portMAX_DELAY);
    const bool cancelled = requested_ != id || closing_;
    xSemaphoreGive(mutex_);
    if (cancelled) break;
    frame = esp_camera_fb_get();
    if (frame && settlingFrames_) {
      --settlingFrames_; esp_camera_fb_return(frame); frame = nullptr; continue;
    }
    const uint64_t captured = frame ? uint64_t(frame->timestamp.tv_sec) * 1000000ULL + frame->timestamp.tv_usec : 0;
    if (frame && frame->format == PIXFORMAT_JPEG && frame->len <= camera_transfer::kMaxImageBytes &&
        camera_transfer::freshFrame(captured, after) &&
        camera_transfer::jpegDimensions(frame->buf, frame->len, width, height) &&
        width == camera_transfer::kNativeWidth && height == camera_transfer::kNativeHeight) break;
    const bool absent=!frame;
    if (frame) esp_camera_fb_return(frame);
    frame = nullptr;
    if (!recovered && (absent || ++invalid>=3)) {
      // A mode change can leave DVP on an incomplete exposure. Recover once
      // on the camera task, never reset the assistant or loop indefinitely.
      recovered=true;
      Serial.println("CAMERA CAPTURE RECOVER: reinitializing sensor/DVP once");
      autofocus_.reset(); focusRaw_=-2;
      esp_camera_deinit(); initialized_=false;
      if (!selectMode(true)) break;
      if (appliedSettings_[camera_settings::Autofocus]) focusOnce();
      if (!selectMode(false)) break;
      after=esp_timer_get_time();
    }
  }
  uint8_t* copy = nullptr;
  size_t length = 0;
  if (frame) {
    copy = static_cast<uint8_t*>(heap_caps_malloc(frame->len, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (copy) { length = frame->len; memcpy(copy, frame->buf, length); }
  }
  if (frame) esp_camera_fb_return(frame);
  const uint32_t checksum = copy ? camera_transfer::crc32(copy, length) : 0;
  xSemaphoreTake(mutex_, portMAX_DELAY);
  if (requested_ != id || closing_) { xSemaphoreGive(mutex_); free(copy); return; }
  uint8_t* previous = image_;
  image_ = copy; size_ = length; frameId_ = id; crc_ = checksum;
  width_ = width; height_ = height; touched_ = millis();
  if (!copy) error_ = frame ? "CAMERA_MEMORY: no PSRAM for full JPEG" : "CAMERA_CAPTURE: no complete fresh 2592x1944 JPEG after bounded recovery; see Serial DVP counters";
  else error_ = "";
  xSemaphoreGive(mutex_);
  free(previous);
  if (copy) Serial.printf("CAMERA JPEG READY id=%lu bytes=%u crc=%08lx %ux%u capture_ms=%lu\n",
                         (unsigned long)id, unsigned(length), (unsigned long)checksum, width, height, (unsigned long)(millis()-started));
}

const char* AssistantCamera::focusStatus() const {
  const int raw=focusRaw_.load();
  if (raw==-3) return "DISABLED";
  if (raw==-2) return "NOT_INITIALIZED";
  if (raw==-1) return "UNAVAILABLE";
  if (raw==-4) return "FOCUSING";
  if (raw==0x10) return "FOCUSED";
  if (raw==0x70) return "IDLE";
  return "SEARCHING";
}
void AssistantCamera::focusOnce() {
  if (!autofocus_.ready()) { focusRaw_=-1; return; }
  focusRaw_=-4;
  const uint32_t started=millis();
  autofocus_.pause();
  const bool focused=autofocus_.single();
  focusRaw_=autofocus_.status();
  Serial.printf("CAMERA AF single=%s status=0x%x error=%d elapsed_ms=%lu\n", focused ? "FOCUSED" : "NOT_LOCKED",
      int(focusRaw_.load()), int(autofocus_.error()), (unsigned long)(millis()-started));
  modeAfterUs_=esp_timer_get_time(); settlingFrames_=2;
}

void AssistantCamera::clear() {
  xSemaphoreTake(mutex_, portMAX_DELAY);
  uint8_t* old = image_; image_ = nullptr; size_ = 0; requested_ = frameId_ = pending_ = 0;
  Preview preview = preview_; preview_ = Preview{};
  closing_ = false;
  xSemaphoreGive(mutex_);
  free(old); free(preview.data);
}
void AssistantCamera::disconnect() {
  if (!mutex_) return;
  xSemaphoreTake(mutex_, portMAX_DELAY);
  viewing_ = false; previewReady_ = false; closing_ = true; pending_ = requested_ = 0;
  xSemaphoreGive(mutex_);
}
String AssistantCamera::diagnostic() {
  if (!mutex_) return "ERROR CAMERA_MEMORY";
  xSemaphoreTake(mutex_, portMAX_DELAY);
  String result = error_.length() ? String("ERROR ") + error_ :
      (viewing_ ? (previewReady_ ? "READY" : "OPENING") : "CLOSED");
  xSemaphoreGive(mutex_);
  return result;
}
AssistantCamera::Preview AssistantCamera::takePreview() {
  if (!mutex_) return Preview{};
  xSemaphoreTake(mutex_, portMAX_DELAY);
  Preview result = preview_; preview_ = Preview{};
  xSemaphoreGive(mutex_);
  return result;
}

AssistantCamera::Preview AssistantCamera::copyPreview(uint32_t afterSequence, size_t prefix, size_t suffix) {
  Preview result;
  if (!mutex_) return result;
  xSemaphoreTake(mutex_, portMAX_DELAY);
  if (viewing_ && previewReady_ && preview_.data && preview_.sequence != afterSequence) {
    result.data = static_cast<uint8_t*>(heap_caps_malloc(prefix+preview_.size+suffix, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (result.data) { result.size = preview_.size; result.sequence = preview_.sequence; memcpy(result.data+prefix, preview_.data, result.size); }
  }
  xSemaphoreGive(mutex_);
  return result;
}

AssistantCamera::Preview AssistantCamera::copyImage(uint32_t id) {
  Preview result;
  if (!mutex_) return result;
  xSemaphoreTake(mutex_, portMAX_DELAY);
  if (id && id == requested_ && id == frameId_ && image_) {
    result.data = static_cast<uint8_t*>(heap_caps_malloc(size_, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (result.data) { result.size = size_; memcpy(result.data, image_, size_); touched_ = millis(); }
  }
  xSemaphoreGive(mutex_);
  return result;
}

void AssistantCamera::previewDisplayed(bool success) {
  if (!mutex_) return;
  xSemaphoreTake(mutex_, portMAX_DELAY);
  if (viewing_) {
    if (!success) {
      error_ = "CAMERA_PREVIEW: JPEG decode failed; see Serial";
      viewing_ = false;
      previewReady_ = false;
    } else if (!previewReady_) {
      previewReady_ = true;
      Serial.println("CAMERA PREVIEW READY: JPEG decoded");
    }
  }
  xSemaphoreGive(mutex_);
}

bool AssistantCamera::command(const char* line, Print& response) {
  if (strncmp(line, "CAM ", 4)) return false;
  if (!mutex_) { response.println("ERR CAMERA_MEMORY"); return true; }
#if !VIETOCR_CAMERA
  response.println("ERR CAMERA_DISABLED: build camera profile"); return true;
#endif
  // Serial/BLE setup for standalone firmware diagnostics, same validation as HTTP.
  if (!strcmp(line,"CAM CONFIG")) { response.println(configJson()); return true; }
  char name[32], tail; int value;
  if (sscanf(line,"CAM SET %31s %d %c",name,&value,&tail)==2) {
    camera_settings::Settings check;
    if (!check.set(name,value)) { response.println("ERR CAMERA_SETTING: invalid field/value"); return true; }
    char json[128]; snprintf(json,sizeof(json),"{\"settings\":{\"%s\":%d},\"persist\":false}",name,value);
    String error;
    if (configure(json,error)) response.println("OK CAM SET");
    else { response.print("ERR "); response.println(error); }
    return true;
  }
  if (!strcmp(line,"CAM SAVE")) {
    String error;
    if (configure("{\"settings\":{},\"persist\":true}",error)) response.println("OK CAM SAVE");
    else { response.print("ERR "); response.println(error); }
    return true;
  }
  unsigned long id; char extra; int mirror, flip;
  xSemaphoreTake(mutex_, portMAX_DELAY);
  if (closing_) { xSemaphoreGive(mutex_); response.println("ERR CAMERA_BUSY: releasing image"); return true; }
  if (!strcmp(line, "CAM AF STATUS")) {
    response.printf("CAM AF %s\n", focusStatus());
  } else if (!strcmp(line, "CAM FOCUS")) {
    if (requested_) response.println("ERR CAMERA_BUSY: capturing");
    else { focusPending_=true; response.println("OK CAM FOCUS"); }
  } else if (sscanf(line, "CAM ORIENT %d %d %c", &mirror, &flip, &extra) == 2 &&
      (mirror == 0 || mirror == 1) && (flip == 0 || flip == 1)) {
    if (requested_) { response.println("ERR CAMERA_BUSY: finish current image"); }
    else {
      if (settings_[camera_settings::Hmirror] != mirror || settings_[camera_settings::Vflip] != flip) {
        settings_.set("hmirror", mirror); settings_.set("vflip", flip);
        if (!++settingsRevision_) settingsRevision_ = 1;
        settingsPending_ = persistPending_ = true; settingsSaved_ = false; settingsError_ = "";
      }
      previewReady_ = false;
      response.printf("OK CAM ORIENT %d %d\n", mirror, flip);
    }
  } else if (!strcmp(line, "CAM ORIENT")) {
    response.printf("CAM ORIENT %d %d\n", settings_[camera_settings::Hmirror], settings_[camera_settings::Vflip]);
  } else if (!strcmp(line, "CAM OPEN")) {
    if (!viewing_) { previewReady_ = false; error_ = ""; previewAfterUs_ = esp_timer_get_time(); }
    viewing_ = true; closing_ = false;
    Serial.println("CAMERA PREVIEW OPEN requested");
    response.println("OK CAM OPEN");
  } else if (!strcmp(line, "CAM STATUS")) {
    if (error_.length()) { response.print("CAM STATUS ERROR "); response.println(error_); }
    else response.println(viewing_ ? (previewReady_ ? "CAM STATUS READY" : "CAM STATUS OPENING") : "CAM STATUS CLOSED");
  } else if (!strcmp(line, "CAM CLOSE")) {
    viewing_ = false; previewReady_ = false; response.println("OK CAM CLOSE");
  }
  else if (sscanf(line, "CAM SHOT %lu %c", &id, &extra) == 1 && id && id <= UINT32_MAX) {
    if (settingsPending_) response.println("ERR CAMERA_BUSY: applying settings");
    else if (requested_ && requested_ != id) response.println("ERR CAMERA_BUSY: finish/release current image");
    else {
      if (requested_ != id) { requested_ = pending_ = id; error_ = ""; }
      viewing_ = false; previewReady_ = false; closing_ = false;
      response.printf("OK CAM SHOT %lu\n", id);
    }
  } else if (sscanf(line, "CAM META %lu %c", &id, &extra) == 1 && id && id == requested_) {
    if (error_.length()) { response.print("ERR "); response.println(error_); }
    else if (frameId_ != id || !image_) response.println("ERR CAMERA_BUSY: capturing");
    else response.printf("CAM %lu %u %08lx %u %u\n", id, unsigned(size_), (unsigned long)crc_, width_, height_);
  } else if (sscanf(line, "CAM RELEASE %lu %c", &id, &extra) == 1 && id && id == requested_) {
    // Deallocation belongs to the camera task, never a BLE callback.
    requested_ = pending_ = 0; closing_ = true;
    response.printf("OK CAM RELEASE %lu\n", id);
  } else response.println("ERR CAMERA_REQUEST: no matching image or invalid command");
  xSemaphoreGive(mutex_);
  return true;
}

void AssistantCamera::onWrite(BLECharacteristic* characteristic) {
  if (!mutex_) return;
  const std::string data = characteristic->getValue();
  xSemaphoreTake(mutex_, portMAX_DELAY);
  readId_ = readOffset_ = readCount_ = 0;
  if (data.size() == 12) {
    const auto* bytes = reinterpret_cast<const uint8_t*>(data.data());
    readId_ = camera_transfer::read32(bytes); readOffset_ = camera_transfer::read32(bytes + 4);
    readCount_ = camera_transfer::read32(bytes + 8); touched_ = millis();
  }
  xSemaphoreGive(mutex_);
}
void AssistantCamera::onRead(BLECharacteristic* characteristic) {
  uint8_t packet[8 + camera_transfer::kMaxChunk]; size_t length = 0;
  size_t total = 0;
  if (mutex_) {
    xSemaphoreTake(mutex_, portMAX_DELAY);
    if (image_ && requested_ == frameId_ && readId_ == frameId_)
      length = camera_transfer::chunkSize(size_, readOffset_, readCount_);
    if (length) {
      camera_transfer::write32(packet, frameId_); camera_transfer::write32(packet + 4, readOffset_);
      memcpy(packet + 8, image_ + readOffset_, length); touched_ = millis();
      total = size_;
    }
    xSemaphoreGive(mutex_);
  }
  characteristic->setValue(packet, length ? length + 8 : 0);
  if (length) {
    const uint32_t offset = camera_transfer::read32(packet + 4);
    if (!offset || offset + length == total)
      Serial.printf("CAMERA JPEG READ id=%lu offset=%lu bytes=%u total=%u\n",
                    (unsigned long)camera_transfer::read32(packet), (unsigned long)offset,
                    unsigned(length), unsigned(total));
  }
}
