#include "assistant_wifi.h"
#include <esp_coexist.h>
#include <WiFi.h>
#include <Preferences.h>
#include <esp_system.h>
#include <esp_wifi.h>
#include <lwip/sockets.h>
#include "assistant_config.h"
#include "camera_udp.h"
#include "http_image_range.h"
#include "assistant_power.h"
#include <cJSON.h>

String AssistantWifi::hex(const String& value) {
  String result; result.reserve(value.length() * 2);
  const char* digits = "0123456789abcdef";
  for (uint8_t c : value) { result += digits[c >> 4]; result += digits[c & 15]; }
  return result.length() ? result : "-";
}
bool AssistantWifi::unhex(const char* value, String& output, size_t maximum) {
  output = "";
  if (!strcmp(value, "-")) return true;
  const size_t length = strlen(value);
  if (!length || length % 2 || length > maximum * 2) return false;
  auto digit = [](char c) -> int { if (c >= '0' && c <= '9') return c - '0'; if (c >= 'a' && c <= 'f') return c - 'a' + 10; return -1; };
  for (size_t i = 0; i < length; i += 2) {
    const int a = digit(value[i]), b = digit(value[i + 1]);
    if (a < 0 || b < 0 || !(a * 16 + b)) return false;
    output += char(a * 16 + b);
  }
  return true;
}
void AssistantWifi::endSession() {
  ++replyEpoch_;  // Do not deliver a previous BLE session's queued reply.
  rotateToken();
}
void AssistantWifi::rotateToken() {
  char next[33];
  snprintf(next, sizeof(next), "%08lx%08lx%08lx%08lx", (unsigned long)esp_random(),
           (unsigned long)esp_random(), (unsigned long)esp_random(), (unsigned long)esp_random());
  portENTER_CRITICAL(&tokenMutex_); memcpy(tokenBytes_, next, sizeof(next)); portEXIT_CRITICAL(&tokenMutex_);
}
void AssistantWifi::begin(AssistantCamera* camera) {
  camera_ = camera;
  rotateToken();
  commands_ = xQueueCreate(4, sizeof(CommandJob));
  replies_ = xQueueCreate(4, sizeof(CommandReply));
  if (!commands_ || !replies_ || xTaskCreatePinnedToCore(task, "VietOCR-Wifi", 8192, this, 1, nullptr, 0) != pdPASS) {
    if (commands_) vQueueDelete(commands_);
    if (replies_) vQueueDelete(replies_);
    commands_ = replies_ = nullptr;
    Serial.println("ERR WIFI_TASK: no memory");
  }
}
void AssistantWifi::task(void* context) { static_cast<AssistantWifi*>(context)->run(); }
void AssistantWifi::run() {
  initialize();
  class ReplyBuffer : public Print {
   public:
    char bytes[192]{}; size_t length = 0;
    size_t write(uint8_t byte) override {
      if (length + 1 >= sizeof(bytes)) return 0;
      bytes[length++] = char(byte); bytes[length] = 0; return 1;
    }
  };
  for (;;) {
      if (sleepRequested_) {
        if (!sleeping_) {
          stopServers();
          if (udpSocket_ >= 0) { close(udpSocket_); udpSocket_ = -1; }
          if (udpRadio_) { esp_coex_preference_set(ESP_COEX_PREFER_BALANCE); udpRadio_ = false; }
          WiFi.disconnect(false, false);  // Preserve the saved NVS profile.
          WiFi.mode(WIFI_OFF);
          sleeping_ = true;
          Serial.println("WIFI POWER OFF");
        }
        vTaskDelay(pdMS_TO_TICKS(20));
        continue;
      }
    if (bluetoothWake_.exchange(false)) reconnectForBluetooth(millis());
    CommandJob job;
    if (xQueueReceive(commands_, &job, 0) == pdTRUE && job.epoch == replyEpoch_) {
      ReplyBuffer buffer;
      execute(job.line, buffer);
      CommandReply reply{}; reply.destination = job.destination; reply.epoch = job.epoch;
      memcpy(reply.line, buffer.bytes, sizeof(reply.line));
      if (reply.epoch == replyEpoch_ && xQueueSend(replies_, &reply, 0) != pdTRUE)
        Serial.println("ERR WIFI_REPLY_QUEUE");
    }
    tick(millis());
    udpTick(millis());
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}
bool AssistantWifi::command(const char* line, Print& response) {
  if (strncmp(line, "WIFI ", 5)) return false;
  if (!commands_) { response.println("ERR WIFI_TASK: not ready"); return true; }
  CommandJob job{}; job.destination = &response; job.epoch = replyEpoch_;
  if (strlen(line) >= sizeof(job.line)) { response.println("ERR WIFI_COMMAND"); return true; }
  memcpy(job.line, line, strlen(line) + 1);
  if (xQueueSend(commands_, &job, 0) != pdTRUE) response.println("ERR WIFI_BUSY: queue full");
  return true;
}
void AssistantWifi::update(uint32_t) {
  // Only the Arduino loop writes BLE's TX ring; NVS, connect/scan and HTTP
  // start/stop never block this loop or TFT animation.
  if (!replies_) return;
  CommandReply reply;
  for (int budget = 2; budget && xQueueReceive(replies_, &reply, 0) == pdTRUE; --budget)
    if (reply.epoch == replyEpoch_) reply.destination->print(reply.line);
}
void AssistantWifi::initialize() {
  WiFi.persistent(false);
  // Required for simultaneous Wi-Fi + BLE on this Arduino/IDF runtime.
  // Set the Arduino cached policy before STA_START applies it to the driver.
  // Keep modem sleep enabled for BLE coexistence. With a long AP DTIM,
  // MIN_MODEM can delay every TCP ACK by hundreds of ms. MAX_MODEM with
  // listen_interval=1 below wakes on each beacon instead of that long DTIM.
  WiFi.setSleep(WIFI_PS_MAX_MODEM);
  WiFi.mode(WIFI_STA);
  // A campus SSID can have several APs. Fast scan may stop on a weak AP on
  // the first channel even when a much stronger one is available nearby.
  WiFi.setScanMethod(WIFI_ALL_CHANNEL_SCAN);
  WiFi.setSortMethod(WIFI_CONNECT_AP_BY_SIGNAL);
  const esp_err_t powerSave = esp_wifi_set_ps(WIFI_PS_MAX_MODEM);
  Serial.printf("WIFI COEX power_save=MAX_MODEM listen_interval=1 rc=%s\n", esp_err_to_name(powerSave));
  WiFi.setAutoReconnect(false);
  WiFi.onEvent([this](WiFiEvent_t, WiFiEventInfo_t info) {
    disconnectReason_ = info.wifi_sta_disconnected.reason;
    Serial.printf("WIFI disconnected reason=%u\n", unsigned(disconnectReason_.load()));
  }, ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
  loadProfile();
  reconnect_.reset(millis());
  if (cached_.ssid[0]) queueJoin(cached_, millis());
  // Bind the HTTP listener only after the station has a usable DHCP address.
  // update() also restarts it if the station address changes after reconnect.
}
void AssistantWifi::loadProfile() {
  Preferences saved;
  if (!saved.begin("vietocr-wifi", true)) { Serial.println("WIFI CACHE empty"); return; }
  wifi_credentials::loadBook(saved, savedNetworks_, cacheOnFlash_);
  if (savedNetworks_.count) cached_ = savedNetworks_.profiles[0];
  saved.end();
  Serial.println(cached_.ssid[0] ? "WIFI CACHE loaded; auto-connect enabled" : "WIFI CACHE empty or invalid");
}
bool AssistantWifi::saveProfile() {
  Preferences saved;
  if (!saved.begin("vietocr-wifi", false)) { Serial.println("ERR WIFI_CACHE: cannot open NVS"); return false; }
  wifi_credentials::Book next = savedNetworks_;
  next.remember(candidate_);
  const bool confirmed = wifi_credentials::saveBook(saved, next);
  saved.end();
  if (confirmed) { savedNetworks_ = next; cached_ = candidate_; cacheOnFlash_ = true; Serial.println("WIFI CACHE saved and verified (NVS)"); }
  else Serial.println("ERR WIFI_CACHE: could not save; current connection still works");
  return confirmed;
}
void AssistantWifi::queueJoin(const wifi_credentials::Profile& profile, uint32_t now) {
  candidate_ = profile;
  joinSsid_ = profile.ssid; joinPassword_ = profile.password;
  joining_ = joinPending_ = true; connectingSince_ = now;
  WiFi.setAutoReconnect(false);
  Serial.println("WIFI connect queued (credentials hidden)");
}
void AssistantWifi::reconnectForBluetooth(uint32_t now) {
  const bool online = WiFi.status() == WL_CONNECTED && uint32_t(WiFi.localIP()) != 0;
  if (!reconnect_.bluetoothConnected(now, cached_.ssid[0], online, joining_)) {
    Serial.println(online ? "WIFI BLE WAKE: LAN already connected" :
                   joining_ ? "WIFI BLE WAKE: saved network connection in progress" : "WIFI BLE WAKE: no saved network yet");
    return;
  }
  // esp_wifi_connect (inside WiFi.begin) scans for the configured SSID and
  // authenticates as soon as it finds it. No app scan/list/select is required.
  if (scan_.active()) esp_wifi_scan_stop();
  WiFi.scanDelete(); scan_.reset(); restoreReconnect_ = false;
  WiFi.setAutoReconnect(false); esp_wifi_disconnect();
  queueJoin(cached_, now);
  Serial.println("WIFI BLE WAKE: searching saved SSID and connecting now");
}
void AssistantWifi::startServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.stack_size = 6144; config.max_open_sockets = 4; config.lru_purge_enable = true;
  config.send_wait_timeout = 8; config.recv_wait_timeout = 3;
  if (!server_) {
    const esp_err_t result = httpd_start(&server_, &config);
    if (result == ESP_OK) {
      httpd_uri_t preview{}; preview.uri = "/preview"; preview.method = HTTP_GET; preview.handler = jpeg; preview.user_ctx = this;
      httpd_register_uri_handler(server_, &preview);
      httpd_uri_t image = preview; image.uri = "/image"; httpd_register_uri_handler(server_, &image);
      httpd_uri_t healthRoute = preview; healthRoute.uri = "/health"; healthRoute.handler = health; httpd_register_uri_handler(server_, &healthRoute);
      httpd_uri_t configRoute = preview; configRoute.uri = "/camera/config"; configRoute.handler = cameraConfig;
      httpd_register_uri_handler(server_, &configRoute);
      configRoute.method = HTTP_POST; httpd_register_uri_handler(server_, &configRoute);
      httpd_uri_t udpRoute=configRoute; udpRoute.uri="/stream/udp"; udpRoute.handler=udpControl;
      httpd_register_uri_handler(server_,&udpRoute);
      serverIp_ = WiFi.localIP();
      Serial.printf("WIFI HTTP listening ip=%s port=80 rssi=%ld heap=%u\n", serverIp_.toString().c_str(), long(WiFi.RSSI()), ESP.getFreeHeap());
    } else Serial.printf("ERR WIFI_HTTP: start failed %s (0x%x)\n", esp_err_to_name(result), unsigned(result));
  }
  // A stream handler stays active. A second server/task keeps /health and
  // /image responsive instead of queueing them behind an endless MJPEG GET.
  if (server_ && !streamServer_) {
    config.server_port = 81; config.ctrl_port += 1;
    config.max_open_sockets = 2;
    config.send_wait_timeout = 8;
    const auto status = httpd_start(&streamServer_, &config);
    if (status == ESP_OK) {
      httpd_uri_t route{}; route.uri = "/stream"; route.method = HTTP_GET;
      route.handler = stream; route.user_ctx = this;
      httpd_register_uri_handler(streamServer_, &route);
      Serial.printf("WIFI MJPEG listening port=81 preview=%ux%u still=%ux%u JPEG_QS=%d\n",
          camera_transfer::kPreviewWidth, camera_transfer::kPreviewHeight,
          camera_transfer::kNativeWidth, camera_transfer::kNativeHeight, camera_transfer::kJpegQuality);
    } else Serial.printf("ERR WIFI_STREAM: %s\n", esp_err_to_name(status));
  }
}
void AssistantWifi::stopServers() {
  // Revocation also tells a live handler to exit before stopping its server.
  rotateToken();
  if (streamServer_) { httpd_stop(streamServer_); streamServer_ = nullptr; }
  if (server_) { httpd_stop(server_); server_ = nullptr; }
  serverIp_ = IPAddress();
}
void AssistantWifi::tick(uint32_t now) {
  const bool transfer=transferring();
  const bool fast=!camera_->poweredDown() || transfer;
  if (fast!=fastRadio_) {
    // Never WIFI_PS_NONE: that aborts this runtime when BLE is enabled.
    const auto policy=fast ? WIFI_PS_MAX_MODEM:WIFI_PS_MIN_MODEM;
    const auto result=esp_wifi_set_ps(policy);
    if (result==ESP_OK) fastRadio_=fast;
  }
  const bool transferChanged=photoRadio_!=transfer;
  if (transferChanged) {
    photoRadio_=transfer;
    esp_coex_preference_set((transfer || udpRadio_) ? ESP_COEX_PREFER_WIFI:ESP_COEX_PREFER_BALANCE);
  }
  if (WiFi.status()==WL_CONNECTED && (transferChanged || uint32_t(now-powerPolicyAt_)>=10000)) {
    powerPolicyAt_=now;
    const int rssi=WiFi.RSSI();
    WiFi.setTxPower(transfer ? WIFI_POWER_17dBm:rssi>-60 ? WIFI_POWER_8_5dBm:rssi>-70 ? WIFI_POWER_13dBm:WIFI_POWER_19_5dBm);
  }
  if (joinPending_ && now - connectingSince_ >= 250) {
    joinPending_ = false; connectingSince_ = now; disconnectReason_ = 0;
    // Configure first, associate only after the wake interval has been set.
    WiFi.begin(joinSsid_.c_str(), joinPassword_.c_str(),0,nullptr,false);
    wifi_config_t station{};
    esp_err_t result=esp_wifi_get_config(WIFI_IF_STA,&station);
    if (result==ESP_OK) {
      station.sta.listen_interval=1;
      result=esp_wifi_set_config(WIFI_IF_STA,&station);
    }
    if (result==ESP_OK) result=esp_wifi_connect();
    if (result!=ESP_OK) Serial.printf("WIFI connect request failed rc=%s\n",esp_err_to_name(result));
    joinSsid_ = joinPassword_ = "";
  }
  if (joining_ && !joinPending_ && now - connectingSince_ >= 25000 &&
      (WiFi.status() != WL_CONNECTED || uint32_t(WiFi.localIP()) == 0)) {
    // Merely clearing joining_ left esp_wifi_connect/AutoReconnect running,
    // causing every later scan to fail with a busy driver.
    joining_ = false; WiFi.setAutoReconnect(false); WiFi.disconnect(false, false);
    reconnect_.failed(now);
    Serial.printf("WIFI connection timed out; reconnect stopped, reason=%u\n", unsigned(disconnectReason_.load()));
  }
  if (scan_.due(now)) {
    const int result = WiFi.scanNetworks(true, true, false, 300);
    scan_.started(now, result);
    Serial.printf("WIFI SCAN attempt=%u result=%d sta=%d reason=%u\n", scan_.attempts, result, int(WiFi.status()), unsigned(disconnectReason_.load()));
    if (result == WIFI_SCAN_FAILED && WiFi.status() != WL_CONNECTED) {
      // Arduino 2.x retries the very first disconnect once even with auto
      // reconnect disabled. Cancel a late queued retry before our next scan.
      WiFi.setAutoReconnect(false); esp_wifi_disconnect();
    }
  }
  if (scan_.state == WifiScanRecovery::State::Running) {
    scan_.poll(now, WiFi.scanComplete());
    if (scan_.state == WifiScanRecovery::State::Failed) esp_wifi_scan_stop();
  }
  if (restoreReconnect_ && !scan_.active()) {
    restoreReconnect_ = false;
    reconnect_.pause(now, 30000); // Leave time to choose a scanned network.
  }
  const IPAddress ip = WiFi.localIP();
  const bool ready = WiFi.status() == WL_CONNECTED && uint32_t(ip) != 0;
  if (ready) {
    if (!wasOnline_) {
      wasOnline_ = true; joining_ = joinPending_ = false;
      reconnect_.reset(now);
      cacheDirty_ = !cacheOnFlash_ || !wifi_credentials::equal(candidate_, cached_);
      lastCacheAttempt_ = now - 30000;
      Serial.printf("WIFI connected ip=%s gateway=%s mask=%s\n", ip.toString().c_str(),
                    WiFi.gatewayIP().toString().c_str(), WiFi.subnetMask().toString().c_str());
    }
    if (cacheDirty_ && now - lastCacheAttempt_ >= 30000) {
      lastCacheAttempt_ = now;
      cacheDirty_ = !saveProfile();
    }
    if (server_ && serverIp_ != ip) stopServers();
    if ((!server_ || !streamServer_) && (!lastServerAttempt_ || now - lastServerAttempt_ >= 3000)) {
      lastServerAttempt_ = now; startServer();
    }
  } else {
    if (wasOnline_) {
      wasOnline_ = false; cacheDirty_ = false;
      reconnect_.failed(now);
      Serial.printf("WIFI lost; reconnect in %lu ms\n", (unsigned long)reconnect_.delayMs());
    }
    if (server_ || streamServer_) stopServers();
    if (!joining_ && !scan_.active() && !restoreReconnect_ && cached_.ssid[0] && reconnect_.due(now))
      queueJoin(cached_, now);
  }
}
bool AssistantWifi::execute(const char* line, Print& response) {
  if (strncmp(line, "WIFI ", 5)) return false;
  if (!strcmp(line, "WIFI SAVED COUNT")) {
    response.printf("WIFI SAVED COUNT %u\n", unsigned(savedNetworks_.count));
  } else if (!strncmp(line,"WIFI SAVED SSID ",16)) {
    unsigned index; char extra;
    if (sscanf(line+16,"%u %c",&index,&extra)!=1 || index>=savedNetworks_.count) response.println("ERR WIFI_INDEX");
    else response.printf("WIFI SAVED SSID %u %s\n",index,hex(String(savedNetworks_.profiles[index].ssid)).c_str());
  } else if (!strncmp(line,"WIFI SAVED PASS ",16)) {
    unsigned index,offset; char extra;
    if (sscanf(line+16,"%u %u %c",&index,&offset,&extra)!=2 || index>=savedNetworks_.count || offset>63)
      response.println("ERR WIFI_INDEX");
    else {
      const String password(savedNetworks_.profiles[index].password);
      response.printf("WIFI SAVED PASS %u %u %s\n",index,offset,hex(password.substring(offset,offset+24)).c_str());
    }
  } else if (!strcmp(line, "WIFI SAVED")) {
    response.printf("WIFI SAVED %u %s\n", cached_.ssid[0] ? 1u : 0u, hex(String(cached_.ssid)).c_str());
  } else if (!strcmp(line, "WIFI STATUS")) {
    if (WiFi.status() == WL_CONNECTED && server_ && uint32_t(WiFi.localIP()) != 0) {
      char token[33]; portENTER_CRITICAL(&tokenMutex_); memcpy(token, tokenBytes_, sizeof(token)); portEXIT_CRITICAL(&tokenMutex_);
      response.printf("WIFI STATUS READY %s %s %s\n", WiFi.localIP().toString().c_str(), token, hex(WiFi.SSID()).c_str());
    } else response.printf("WIFI STATUS %s %d %u\n", joining_ ? "JOINING" : "OFFLINE", int(WiFi.status()), unsigned(disconnectReason_.load()));
  } else if (!strcmp(line, "WIFI SCAN")) {
    if (!scan_.active()) {
      WiFi.setAutoReconnect(false);
      joining_ = joinPending_ = false; joinSsid_ = joinPassword_ = "";
      // Keep an existing LAN connection; cancel only an offline connection
      // attempt. A manual disconnect must not erase saved credentials.
      if (WiFi.status() != WL_CONNECTED) {
        const auto result = esp_wifi_disconnect();
        Serial.printf("WIFI SCAN cancel offline connect rc=%s\n", esp_err_to_name(result));
      }
      WiFi.scanDelete();
      scan_.request(millis()); restoreReconnect_ = true;
      reconnect_.pause(millis(), 60000);
      Serial.println("WIFI SCAN queued; connection paused before scan");
    }
    response.println("OK WIFI SCAN");
  } else if (!strcmp(line, "WIFI COUNT")) {
    const int count = WiFi.scanComplete();
    if (scan_.active()) response.println("WIFI COUNT BUSY");
    else if (scan_.state != WifiScanRecovery::State::Done || count < 0) {
      response.println("ERR WIFI_SCAN_FAILED: no completed scan; retry WIFI SCAN");
    } else response.printf("WIFI COUNT %d\n", min(count, 30));
  } else if (!strncmp(line, "WIFI NET ", 9)) {
    unsigned index; char extra;
    const int count = WiFi.scanComplete();
    if (sscanf(line + 9, "%u %c", &index, &extra) != 1 || count < 0 || index >= unsigned(count) || index >= 30)
      response.println("ERR WIFI_INDEX");
    else response.printf("WIFI NET %u %d %u %s\n", index, WiFi.RSSI(index), WiFi.encryptionType(index) != WIFI_AUTH_OPEN, hex(WiFi.SSID(index)).c_str());
  } else if (!strncmp(line, "WIFI SSID ", 10)) {
    String value;
    if (!unhex(line + 10, value, 32) || !value.length()) response.println("ERR WIFI_SSID");
    else { ssid_ = value; password_ = ""; reconnect_.pause(millis(), 60000); response.println("OK WIFI SSID"); }
  } else if (!strncmp(line, "WIFI PASS ", 10)) {
    String value;
    if (!ssid_.length() || !unhex(line + 10, value, 24) || password_.length() + value.length() > 63) response.println("ERR WIFI_PASSWORD");
    else { password_ += value; reconnect_.pause(millis(), 60000); response.println("OK WIFI PASS"); }
  } else if (!strcmp(line, "WIFI JOIN")) {
    if (!ssid_.length() || (password_.length() && password_.length() < 8)) response.println("ERR WIFI_PASSWORD: use 8..63 bytes or empty for open WiFi");
    else if (scan_.active()) response.println("ERR WIFI_BUSY: scanning");
    else {
      WiFi.scanDelete(); scan_.reset(); restoreReconnect_ = false;
      WiFi.setAutoReconnect(false); WiFi.disconnect(false, false);
      wifi_credentials::Profile profile{};
      ssid_.toCharArray(profile.ssid, sizeof(profile.ssid));
      password_.toCharArray(profile.password, sizeof(profile.password));
      queueJoin(profile, millis());
      reconnect_.reset(millis());
      ssid_ = password_ = "";
      response.println("OK WIFI JOIN");
    }
  } else if (!strcmp(line, "WIFI FORGET")) {
    Preferences saved;
    if (!saved.begin("vietocr-wifi", false)) { response.println("ERR WIFI_CACHE: cannot open NVS"); return true; }
    const bool cleared = saved.clear(); saved.end();
    if (!cleared) { response.println("ERR WIFI_CACHE: cannot clear NVS"); return true; }
    WiFi.setAutoReconnect(false); esp_wifi_scan_stop(); scan_.reset(); restoreReconnect_ = false;
    WiFi.disconnect(false, false); joining_ = joinPending_ = false;
    ssid_ = password_ = joinSsid_ = joinPassword_ = "";
    cached_ = candidate_ = wifi_credentials::Profile{}; savedNetworks_ = wifi_credentials::Book{}; cacheOnFlash_ = cacheDirty_ = false;
    rotateToken(); response.println("OK WIFI FORGET");
  } else response.println("ERR WIFI_COMMAND");
  return true;
}
bool AssistantWifi::authorized(httpd_req_t* request) {
  auto* self = static_cast<AssistantWifi*>(request->user_ctx);
  char auth[48]{}, expected[40] = "Bearer ";
  portENTER_CRITICAL(&self->tokenMutex_); memcpy(expected + 7, self->tokenBytes_, 33); portEXIT_CRITICAL(&self->tokenMutex_);
  if (httpd_req_get_hdr_value_str(request, "Authorization", auth, sizeof(auth)) != ESP_OK || strcmp(auth, expected)) {
    httpd_resp_set_status(request, "401 Unauthorized"); httpd_resp_sendstr(request, "Get session from BLE"); return false;
  }
  return true;
}
esp_err_t AssistantWifi::health(httpd_req_t* request) {
  if (!authorized(request)) return ESP_OK;
  const uint32_t started=millis();
  String camera = static_cast<AssistantWifi*>(request->user_ctx)->camera_->diagnostic();
  camera.replace("\\", "/"); camera.replace("\"", "'"); camera.replace("\n", " "); camera.replace("\r", " ");
  auto* self = static_cast<AssistantWifi*>(request->user_ctx);
  const auto profile = self->camera_->configuration();
  char response[896];
  snprintf(response, sizeof(response), "{\"sensor\":\"OV5640\",\"autofocus\":\"%s\",\"preview_fps_limit\":%d,\"firmware\":\"%s\",\"ip\":\"%s\",\"rssi\":%ld,\"http\":true,\"stream_port\":81,\"preview\":[%u,%u],\"still\":[%u,%u],\"preview_jpeg_quality\":%d,\"jpeg_quality\":%d,\"jpeg_capacity\":%u,\"mirror\":%s,\"flip\":%s,\"camera_status\":\"%s\",\"die_deci_c\":%d,\"cooling\":%s,\"cpu_mhz\":%u,\"effective_fps_limit\":%u,\"focus_point\":[%d,%d]}",
           self->camera_->focusStatus(),profile[camera_settings::MaxFps],
           assistant_config::kFirmwareVersion, WiFi.localIP().toString().c_str(), long(WiFi.RSSI()),
           profile[camera_settings::PreviewWidth], profile[camera_settings::PreviewWidth] * 3 / 4,
           camera_transfer::kNativeWidth, camera_transfer::kNativeHeight,
           profile[camera_settings::PreviewQuality], profile[camera_settings::StillQuality],
           unsigned(camera_transfer::kMaxImageBytes), self->camera_->mirrored() ? "true" : "false",
           self->camera_->flipped() ? "true" : "false", camera.c_str(),
           assistant_power::temperatureDeciC(),assistant_power::tooHot() ? "true":"false",getCpuFrequencyMhz(),
           self->camera_->maxFps(),profile[camera_settings::FocusX],profile[camera_settings::FocusY]);
  httpd_resp_set_type(request, "application/json"); httpd_resp_set_hdr(request, "Cache-Control", "no-store");
  const auto result=httpd_resp_sendstr(request, response);
  Serial.printf("WIFI HTTP health cpu=%u send_ms=%lu rc=%s\n",getCpuFrequencyMhz(),(unsigned long)(millis()-started),esp_err_to_name(result));
  return result;
}
esp_err_t AssistantWifi::cameraConfig(httpd_req_t* request) {
  if (!authorized(request)) return ESP_OK;
  auto* self = static_cast<AssistantWifi*>(request->user_ctx);
  httpd_resp_set_type(request, "application/json");
  httpd_resp_set_hdr(request, "Cache-Control", "no-store");
  if (request->method == HTTP_POST) {
    if (request->content_len <= 0 || request->content_len > 2048) {
      httpd_resp_set_status(request, "400 Bad Request"); return httpd_resp_sendstr(request, "{\"error\":\"Invalid config size\"}");
    }
    char body[2049]; int received = 0;
    while (received < request->content_len) {
      const int count = httpd_req_recv(request, body + received, request->content_len - received);
      if (count <= 0) {
        httpd_resp_set_status(request, "408 Request Timeout"); return httpd_resp_sendstr(request, "{\"error\":\"Incomplete config\"}");
      }
      received += count;
    }
    body[received] = 0;
    String error;
    if (!self->camera_->configure(body, error)) {
      httpd_resp_set_status(request, error.startsWith("CAMERA_BUSY") ? "409 Conflict" : "400 Bad Request");
      error.replace("\\", "/"); error.replace("\"", "'"); error.replace("\n", " "); error.replace("\r", " ");
      return httpd_resp_sendstr(request, (String("{\"error\":\"") + error + "\"}").c_str());
    }
    httpd_resp_set_status(request, "202 Accepted");
  }
  return httpd_resp_sendstr(request, self->camera_->configJson().c_str());
}
esp_err_t AssistantWifi::udpControl(httpd_req_t* request) {
  if (!authorized(request)) return ESP_OK;
  auto* self=static_cast<AssistantWifi*>(request->user_ctx);
  httpd_resp_set_type(request,"application/json");
  if (request->content_len<=0 || request->content_len>64) {
    httpd_resp_set_status(request,"400 Bad Request"); return httpd_resp_sendstr(request,"{\"error\":\"Expected port\"}");
  }
  char body[65]{}; size_t at=0;
  while (at<size_t(request->content_len)) {
    const int count=httpd_req_recv(request,body+at,request->content_len-at);
    if (count<=0) return ESP_FAIL;
    at+=count;
  }
  cJSON* json=cJSON_Parse(body);
  auto* port=json ? cJSON_GetObjectItemCaseSensitive(json,"port"):nullptr;
  const int value=cJSON_IsNumber(port) && port->valueint==port->valuedouble ? port->valueint:-1;
  cJSON_Delete(json);
  if (value!=0 && (value<1024 || value>65535)) {
    httpd_resp_set_status(request,"400 Bad Request");return httpd_resp_sendstr(request,"{\"error\":\"Port must be 1024..65535 or 0 to stop\"}");
  }
  sockaddr_storage peer{};socklen_t size=sizeof(peer);uint32_t peer4=0;
  if (getpeername(httpd_req_to_sockfd(request),reinterpret_cast<sockaddr*>(&peer),&size)==0) {
    if (peer.ss_family==AF_INET) peer4=reinterpret_cast<sockaddr_in*>(&peer)->sin_addr.s_addr;
    else if (peer.ss_family==AF_INET6) {
      const auto* address=&reinterpret_cast<sockaddr_in6*>(&peer)->sin6_addr;
      const uint8_t mapped[12]={0,0,0,0,0,0,0,0,0,0,0xff,0xff};
      if (!memcmp(address->s6_addr,mapped,12)) memcpy(&peer4,&address->s6_addr[12],4);
    }
  }
  if (!peer4) {
    httpd_resp_set_status(request,"400 Bad Request");
    return httpd_resp_sendstr(request,"{\"error\":\"UDP requires an IPv4 peer\"}");
  }
  char token[33];
  portENTER_CRITICAL(&self->tokenMutex_); memcpy(token,self->tokenBytes_,33);portEXIT_CRITICAL(&self->tokenMutex_);
  // Destination is always the authenticated HTTP peer, never an arbitrary IP.
  portENTER_CRITICAL(&self->udpMutex_);
  const bool sameLease = self->udpActive_ && value && self->udpPeer_ == peer4 &&
      self->udpPort_ == value && !memcmp(self->udpToken_, token, 33) && int32_t(millis()-self->udpExpires_) < 0;
  self->udpActive_=value!=0; self->udpPeer_=peer4; self->udpPort_=value;
  self->udpExpires_=millis()+60000; memcpy(self->udpToken_,token,33);
  if (!sameLease && !++self->udpGeneration_) self->udpGeneration_=1;
  const uint32_t generation=self->udpGeneration_;
  portEXIT_CRITICAL(&self->udpMutex_);
  if (value) self->camera_->renewPreviewLease();
  char response[128];snprintf(response,sizeof(response),"{\"active\":%s,\"stream\":%lu,\"datagram_bytes\":1200,\"header_bytes\":32,\"lease_seconds\":60}",value ? "true":"false",(unsigned long)generation);
  return httpd_resp_sendstr(request,response);
}
void AssistantWifi::udpTick(uint32_t now) {
  portENTER_CRITICAL(&udpMutex_);
  const bool active=udpActive_; const uint32_t peer=udpPeer_, generation=udpGeneration_, expires=udpExpires_;
  const uint16_t port=udpPort_; char token[33];memcpy(token,udpToken_,33);
  portEXIT_CRITICAL(&udpMutex_);
  bool valid;
  portENTER_CRITICAL(&tokenMutex_);valid=!memcmp(token,tokenBytes_,33);portEXIT_CRITICAL(&tokenMutex_);
  if (!active || !valid || int32_t(now-expires)>=0 || !camera_->viewing() || WiFi.status()!=WL_CONNECTED) {
    if (udpSocket_>=0) { close(udpSocket_);udpSocket_=-1; }
    if (udpRadio_) { esp_coex_preference_set(transferring() ? ESP_COEX_PREFER_WIFI:ESP_COEX_PREFER_BALANCE);udpRadio_=false; }
    return;
  }
  if (udpSocket_<0) {
    udpSocket_=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
    if (udpSocket_<0) return;
    sockaddr_in local{};local.sin_family=AF_INET;local.sin_addr.s_addr=INADDR_ANY;local.sin_port=htons(82);
    if (bind(udpSocket_,reinterpret_cast<sockaddr*>(&local),sizeof(local))!=0) { close(udpSocket_);udpSocket_=-1;return; }
    timeval timeout{};timeout.tv_usec=10000;
    setsockopt(udpSocket_,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));
    udpStatsAt_=now;udpFrames_=udpDropped_=0;udpSequence_=0;
    esp_coex_preference_set(ESP_COEX_PREFER_WIFI);udpRadio_=true;
  }
  const unsigned fps=camera_->maxFps();
  uint8_t probe[16]; recv(udpSocket_,probe,sizeof(probe),MSG_DONTWAIT);
  if (fps && now-udpAt_<1000/fps) return;
  auto frame=camera_->copyPreview(udpSequence_);
  if (!frame.data) return;
  udpSequence_=frame.sequence;udpAt_=now;
  uint16_t width=0,height=0;
  const bool jpeg=camera_transfer::jpegDimensions(frame.data,frame.size,width,height);
  const uint32_t crc=camera_transfer::crc32(frame.data,frame.size);
  sockaddr_in target{};target.sin_family=AF_INET;target.sin_addr.s_addr=peer;target.sin_port=htons(port);
  uint8_t packet[camera_udp::kDatagram];bool complete=jpeg;
  for (size_t offset=0;jpeg && offset<frame.size;offset+=camera_udp::kPayload) {
    if (millis()-now>45) { complete=false;break; } // drop partial frame, never queue stale video
    const size_t count=camera_udp::packet(packet,sizeof(packet),frame.data,frame.size,generation,frame.sequence,crc,offset,width,height);
    if (!count || sendto(udpSocket_,packet,count,0,reinterpret_cast<sockaddr*>(&target),sizeof(target))!=int(count)) { complete=false;break; }
  }
  free(frame.data);
  if (complete) ++udpFrames_;else ++udpDropped_;
  if (now-udpStatsAt_>=5000) {
    Serial.printf("WIFI UDP fps=%.1f dropped=%u %ux%u\n",udpFrames_*1000.0f/(now-udpStatsAt_),unsigned(udpDropped_),width,height);
    udpStatsAt_=now;udpFrames_=udpDropped_=0;
  }
}
esp_err_t AssistantWifi::jpeg(httpd_req_t* request) {
  auto* self = static_cast<AssistantWifi*>(request->user_ctx);
  if (!authorized(request)) return ESP_OK;
  AssistantCamera::Preview frame;
  const bool still = !strncmp(request->uri, "/image", 6);
  struct TransferActivity {
    std::atomic<bool>& active; std::atomic<uint32_t>& until; bool enabled;
    TransferActivity(std::atomic<bool>& a, std::atomic<uint32_t>& u, bool e):active(a),until(u),enabled(e) { if (enabled) active=true; }
    ~TransferActivity() { if (enabled) { until=millis()+2000; active=false; } }
  } transfer(self->photoTransfer_,self->photoUntil_,still);
  unsigned long imageId = 0;
  if (still) {
    char query[48]{}, value[16]{};
    unsigned long id = 0; char extra;
    if (httpd_req_get_url_query_str(request, query, sizeof(query)) != ESP_OK ||
        httpd_query_key_value(query, "id", value, sizeof(value)) != ESP_OK ||
        sscanf(value, "%lu%c", &id, &extra) != 1 || !id || id > UINT32_MAX) {
      httpd_resp_set_status(request, "400 Bad Request"); return httpd_resp_sendstr(request, "Invalid image ID");
    }
    imageId = id;
    frame = self->camera_->copyImage(id);
  } else { self->camera_->renewPreviewLease(); frame = self->camera_->copyPreview(); }
  if (!frame.data) { httpd_resp_set_status(request, "503 Service Unavailable"); return httpd_resp_sendstr(request, "Camera not ready"); }
  httpd_resp_set_type(request, "image/jpeg"); httpd_resp_set_hdr(request, "Cache-Control", "no-store");
  httpd_resp_set_hdr(request, "Connection", "close");
  // Short, resumable requests let control/health run between photo chunks.
  // Keep the exact sensor JPEG: no resize, decode or re-encode on this route.
  http_image_range::Range range; range.length = frame.size;
  char rangeHeader[80]{}, etag[40]{}, ifRange[40]{};
  if (still) {
    snprintf(etag, sizeof(etag), "\"%lu-%08lx\"", imageId,
             (unsigned long)camera_transfer::crc32(frame.data, frame.size));
    httpd_resp_set_hdr(request, "ETag", etag);
    httpd_resp_set_hdr(request, "Accept-Ranges", "bytes");
    const size_t headerSize = httpd_req_get_hdr_value_len(request, "Range");
    const bool hasIfRange = httpd_req_get_hdr_value_len(request, "If-Range") != 0;
    const bool match = !hasIfRange || (httpd_req_get_hdr_value_str(request, "If-Range", ifRange, sizeof(ifRange)) == ESP_OK && !strcmp(ifRange, etag));
    if (headerSize && match) {
      if (headerSize >= sizeof(rangeHeader) || httpd_req_get_hdr_value_str(request, "Range", rangeHeader, sizeof(rangeHeader)) != ESP_OK ||
          !http_image_range::parse(rangeHeader, frame.size, range)) {
        char invalid[48]; snprintf(invalid, sizeof(invalid), "bytes */%u", unsigned(frame.size));
        httpd_resp_set_status(request, "416 Range Not Satisfiable");
        httpd_resp_set_hdr(request, "Content-Range", invalid);
        free(frame.data); return httpd_resp_sendstr(request, "Invalid byte range");
      }
    }
  }
  char contentRange[64];
  if (range.partial) {
    snprintf(contentRange, sizeof(contentRange), "bytes %u-%u/%u", unsigned(range.first),
             unsigned(range.first + range.length - 1), unsigned(frame.size));
    httpd_resp_set_status(request, "206 Partial Content");
    httpd_resp_set_hdr(request, "Content-Range", contentRange);
  }
  const uint32_t start = millis();
  const auto result = httpd_resp_send(request, reinterpret_cast<const char*>(frame.data + range.first), range.length);
  Serial.printf("WIFI JPEG %s offset=%u bytes=%u total=%u send_ms=%lu rc=%s\n", still ? "shot" : "preview",
                unsigned(range.first), unsigned(range.length), unsigned(frame.size), (unsigned long)(millis()-start), esp_err_to_name(result));
  free(frame.data);
  // Clients deliberately use one request per range. Release server slots even
  // if a peer's TCP FIN is delayed/lost on a noisy LAN.
  httpd_sess_trigger_close(request->handle, httpd_req_to_sockfd(request));
  return result;
}

esp_err_t AssistantWifi::stream(httpd_req_t* request) {
  auto* self = static_cast<AssistantWifi*>(request->user_ctx);
  if (!authorized(request)) return ESP_OK;
  const int noDelay = 1;
  setsockopt(httpd_req_to_sockfd(request), IPPROTO_TCP, TCP_NODELAY, &noDelay, sizeof(noDelay));
  char session[33];
  portENTER_CRITICAL(&self->tokenMutex_); memcpy(session, self->tokenBytes_, sizeof(session)); portEXIT_CRITICAL(&self->tokenMutex_);
  if (!self->camera_->viewing()) {
    httpd_resp_set_status(request, "503 Service Unavailable");
    return httpd_resp_sendstr(request, "Open camera over BLE first");
  }
  auto sendAll=[request](const char* bytes,size_t length) {
    while (length) {
      const int sent=httpd_send(request,bytes,length);
      if (sent<=0) return ESP_FAIL;
      bytes+=sent; length-=sent;
    }
    return ESP_OK;
  };
  struct RadioPreference {
    RadioPreference() { esp_coex_preference_set(ESP_COEX_PREFER_WIFI); }
    ~RadioPreference() { esp_coex_preference_set(ESP_COEX_PREFER_BALANCE); }
  } radioPreference;
  // Flush response headers immediately; clients need not wait for camera init.
  // Multipart has its own lengths/boundaries. A close-delimited HTTP body
  // avoids tiny HTTP chunk-size/terminator packets and their ACK latency.
  constexpr char responseHeader[]="HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=vietocr-frame\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n";
  esp_err_t result = sendAll(responseHeader,sizeof(responseHeader)-1);
  uint32_t last = 0, sent = 0, started = millis(), lastFrame = started;
  uint32_t statsAt = started, statsFrames = 0, sendMs = 0, sendBytes = 0;
  while (result == ESP_OK && self->camera_->viewing() && WiFi.status() == WL_CONNECTED) {
    self->camera_->renewPreviewLease();
    bool current;
    portENTER_CRITICAL(&self->tokenMutex_); current = !memcmp(session, self->tokenBytes_, sizeof(session)); portEXIT_CRITICAL(&self->tokenMutex_);
    if (!current || millis() - lastFrame > 30000) break;
    constexpr size_t prefix=160;
    auto frame = self->camera_->copyPreview(last,prefix,2);
    if (!frame.data) { vTaskDelay(pdMS_TO_TICKS(1)); continue; }
    last = frame.sequence; lastFrame = millis();
    char header[160];
    const int length = snprintf(header, sizeof(header), "--vietocr-frame\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\nX-Sequence: %lu\r\n\r\n",
                                unsigned(frame.size), (unsigned long)last);
    const uint32_t sending = millis();
    // Send header + JPEG + CRLF as one chunk. Three separate chunks forced
    // small-packet ACK round trips on power-saving/campus access points.
    uint8_t* packet=frame.data+prefix-length;
    memcpy(packet,header,length);
    frame.data[prefix+frame.size]='\r'; frame.data[prefix+frame.size+1]='\n';
    result = sendAll(reinterpret_cast<const char*>(packet),length+frame.size+2);
    free(frame.data);
    // A full native frame may take several seconds on a weak LAN. Time spent
    // successfully sending it is not a sensor stall.
    if (result == ESP_OK) lastFrame = millis();
    if (result == ESP_OK && ++sent == 1) Serial.printf("WIFI MJPEG first_frame_ms=%lu bytes=%u\n", (unsigned long)(millis()-started), unsigned(frame.size));
    if (result == ESP_OK) {
      ++statsFrames; sendMs += millis() - sending; sendBytes += frame.size;
      const uint32_t now = millis();
      if (now - statsAt >= 5000) {
        Serial.printf("WIFI MJPEG fps=%.1f avg_send_ms=%u KiB_s=%.1f\n",
            statsFrames * 1000.0f / (now-statsAt), unsigned(sendMs / statsFrames),
            sendBytes * 1000.0f / (1024 * (now-statsAt)));
        statsAt = now; statsFrames = sendMs = sendBytes = 0;
      }
    }
    // User-selectable cap, measured from frame start rather than adding a
    // fixed delay after the network transfer. Slow clients skip older frames.
    const unsigned fps = self->camera_->maxFps();
    const uint32_t elapsed = millis() - sending;
    if (fps && elapsed < 1000 / fps) vTaskDelay(pdMS_TO_TICKS(1000 / fps - elapsed));
    else taskYIELD();
  }
  Serial.printf("WIFI MJPEG closed frames=%lu elapsed_ms=%lu rc=%s\n", (unsigned long)sent, (unsigned long)(millis()-started), esp_err_to_name(result));
  // A non-OK return closes the socket on capture/close/revocation as well.
  return result == ESP_OK ? ESP_FAIL : result;
}
