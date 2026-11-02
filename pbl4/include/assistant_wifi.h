#pragma once
#include <Arduino.h>
#include <IPAddress.h>
#include <esp_http_server.h>
#include <freertos/queue.h>
#include "assistant_camera.h"
#include "wifi_recovery.h"
#include "wifi_credentials.h"

// BLE provisions credentials; the HTTP task sends JPEG without blocking loop/TFT.
class AssistantWifi {
 public:
  void begin(AssistantCamera* camera);
  bool command(const char* line, Print& response);
  void update(uint32_t now);
  void endSession();
  void prepareSleep() { sleepRequested_ = true; }
  bool sleeping() const { return sleeping_; }
  void bluetoothConnected() { bluetoothWake_ = true; }
 private:
  AssistantCamera* camera_ = nullptr;
  httpd_handle_t server_ = nullptr;
  httpd_handle_t streamServer_ = nullptr;
  String ssid_, password_;
  portMUX_TYPE tokenMutex_ = portMUX_INITIALIZER_UNLOCKED;
  char tokenBytes_[33]{};
  uint32_t connectingSince_ = 0;
  bool joining_ = false, joinPending_ = false, restoreReconnect_ = false, wasOnline_ = false;
  String joinSsid_, joinPassword_;
  wifi_credentials::Profile cached_, candidate_;
  wifi_credentials::Book savedNetworks_;
  bool cacheOnFlash_ = false, cacheDirty_ = false;
  uint32_t lastCacheAttempt_ = 0;
  WifiReconnect reconnect_;
  WifiScanRecovery scan_;
  std::atomic<uint16_t> disconnectReason_{0};
  IPAddress serverIp_;
  uint32_t lastServerAttempt_ = 0;
  uint32_t powerPolicyAt_ = 0;
  bool fastRadio_ = true;
  portMUX_TYPE udpMutex_=portMUX_INITIALIZER_UNLOCKED;
  bool udpActive_=false, udpRadio_=false;
  uint32_t udpPeer_=0, udpGeneration_=0, udpExpires_=0, udpSequence_=0, udpAt_=0;
  uint32_t udpStatsAt_=0, udpFrames_=0, udpDropped_=0;
  uint16_t udpPort_=0;
  char udpToken_[33]{};
  int udpSocket_=-1;
  struct CommandJob { Print* destination; uint32_t epoch; char line[80]; };
  struct CommandReply { Print* destination; uint32_t epoch; char line[192]; };
  QueueHandle_t commands_ = nullptr, replies_ = nullptr;
  std::atomic<uint32_t> replyEpoch_{0};
  std::atomic<bool> bluetoothWake_{false};
  std::atomic<bool> sleepRequested_{false}, sleeping_{false};
  static void task(void* context);
  void run();
  void initialize();
  void reconnectForBluetooth(uint32_t now);
  void tick(uint32_t now);
  void udpTick(uint32_t now);
  bool execute(const char* line, Print& response);
  void loadProfile();
  bool saveProfile();
  void queueJoin(const wifi_credentials::Profile& profile, uint32_t now);
  void rotateToken();
  void startServer();
  void stopServers();
  static esp_err_t health(httpd_req_t* request);
  static esp_err_t cameraConfig(httpd_req_t* request);
  static bool authorized(httpd_req_t* request);
  static esp_err_t jpeg(httpd_req_t* request);
  static esp_err_t stream(httpd_req_t* request);
  static esp_err_t udpControl(httpd_req_t* request);
  static String hex(const String& value);
  static bool unhex(const char* value, String& output, size_t maximum);
};
