#pragma once

#include <Arduino.h>
#include <BLE2902.h>
#include <BLECharacteristic.h>
#include <BLEServer.h>
#include "assistant_logic.h"

// BLE callbacks only copy input. All commands, drawing and sound run in loop().
class AssistantBluetooth : public BLEServerCallbacks, public BLECharacteristicCallbacks, public Print {
 public:
  using CommandHandler = void (*)(const char*, uint32_t, Print&);
  using DisconnectHandler = void (*)(uint32_t);
  using ConnectHandler = void (*)(uint32_t);
  AssistantBluetooth(CommandHandler command, DisconnectHandler disconnected);
  void begin();
  void setCameraCallbacks(BLECharacteristicCallbacks* camera) { camera_ = camera; }
  void setConnectHandler(ConnectHandler handler) { connectedHandler_ = handler; }
  void update(uint32_t now);
  const String& label() const { return label_; }
  using Print::write;
  size_t write(uint8_t value) override;

 private:
  static constexpr size_t kCapacity = 512;
  BLEServer* server_ = nullptr;
  BLECharacteristic* tx_ = nullptr;
  BLE2902* subscription_ = nullptr;
  BLECharacteristicCallbacks* camera_ = nullptr;
  CommandHandler command_;
  DisconnectHandler disconnected_;
  ConnectHandler connectedHandler_ = nullptr;
  assistant::LineReceiver receiver_;
  String label_;
  portMUX_TYPE mutex_ = portMUX_INITIALIZER_UNLOCKED;
  // Protected by mutex_: shared between the Bluetooth task and Arduino loop.
  bool connected_ = false;
  bool rxOverflow_ = false;
  uint16_t connectionId_ = 0;
  uint32_t generation_ = 0;
  uint8_t rx_[kCapacity]{};
  size_t rxHead_ = 0, rxTail_ = 0, rxSize_ = 0;
  // Only accessed by Arduino loop.
  uint32_t sessionGeneration_ = 0;
  bool session_ = false, closing_ = false, restartAdvertising_ = false;
  bool txOverflow_ = false, notifyFailed_ = false;
  uint32_t lastSeen_ = 0, lastNotify_ = 0, disconnectedAt_ = 0;
  uint8_t txBuffer_[kCapacity]{};
  size_t txHead_ = 0, txTail_ = 0, txSize_ = 0;

  void onConnect(BLEServer*, esp_ble_gatts_cb_param_t* param) override;
  void onMtuChanged(BLEServer*, esp_ble_gatts_cb_param_t* param) override;
  void onDisconnect(BLEServer*, esp_ble_gatts_cb_param_t*) override;
  void onWrite(BLECharacteristic* characteristic) override;
  void onStatus(BLECharacteristic*, Status status, uint32_t) override;
  bool pop(uint8_t& value);
  void disconnect(uint16_t id, const char* reason);
};
