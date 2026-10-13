#include "assistant_bluetooth.h"
#include "assistant_config.h"
#include <BLEDevice.h>

AssistantBluetooth::AssistantBluetooth(CommandHandler command, DisconnectHandler disconnected)
    : command_(command), disconnected_(disconnected) {}

void AssistantBluetooth::begin() {
  BLEDevice::init(assistant_config::kBluetoothName);
  server_ = BLEDevice::createServer();
  server_->setCallbacks(this);
  BLEService* service = server_->createService(assistant_config::kBleServiceUuid);
  tx_ = service->createCharacteristic(assistant_config::kBleTxUuid, BLECharacteristic::PROPERTY_NOTIFY);
  subscription_ = new BLE2902();
  tx_->addDescriptor(subscription_);
  tx_->setCallbacks(this);
  BLECharacteristic* rx = service->createCharacteristic(
      assistant_config::kBleRxUuid, BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  rx->setCallbacks(this);
  service->start();
  BLEAdvertising* advertising = BLEDevice::getAdvertising();
  // A 128-bit service UUID and the full name need separate advertising packets.
  static_assert(sizeof(assistant_config::kBluetoothName) <= 30, "BLE name must be at most 29 bytes");
  BLEAdvertisementData data;
  data.setFlags(ESP_BLE_ADV_FLAG_GEN_DISC | ESP_BLE_ADV_FLAG_BREDR_NOT_SPT);
  data.setCompleteServices(BLEUUID(assistant_config::kBleServiceUuid));
  BLEAdvertisementData scanResponse;
  scanResponse.setName(assistant_config::kBluetoothName);
  advertising->setAdvertisementData(data);
  advertising->setScanResponseData(scanResponse);
  advertising->setScanResponse(true);
  advertising->start();
  label_ = "Cho ket noi";
  Serial.printf("BLE READY name=%s service=%s\n", assistant_config::kBluetoothName,
                assistant_config::kBleServiceUuid);
}

void AssistantBluetooth::onConnect(BLEServer*, esp_ble_gatts_cb_param_t* param) {
  portENTER_CRITICAL(&mutex_);
  connected_ = true;
  connectionId_ = param->connect.conn_id;
  ++generation_;
  rxHead_ = rxTail_ = rxSize_ = 0;
  rxOverflow_ = false;
  portEXIT_CRITICAL(&mutex_);
}

void AssistantBluetooth::onDisconnect(BLEServer*, esp_ble_gatts_cb_param_t*) {
  portENTER_CRITICAL(&mutex_);
  connected_ = false;
  ++generation_;
  rxHead_ = rxTail_ = rxSize_ = 0;
  portEXIT_CRITICAL(&mutex_);
}

void AssistantBluetooth::onWrite(BLECharacteristic* characteristic) {
  const std::string value = characteristic->getValue();
  portENTER_CRITICAL(&mutex_);
  if (connected_) {
    if (value.size() > kCapacity - rxSize_) {
      rxOverflow_ = true;  // Never execute a truncated command after overflow.
    } else {
      for (uint8_t byte : value) {
        rx_[rxTail_] = byte;
        rxTail_ = (rxTail_ + 1) % kCapacity;
      }
      rxSize_ += value.size();
    }
  }
  portEXIT_CRITICAL(&mutex_);
}

void AssistantBluetooth::onStatus(BLECharacteristic*, Status status, uint32_t) {
  if (status != Status::SUCCESS_NOTIFY) notifyFailed_ = true;
}

size_t AssistantBluetooth::write(uint8_t value) {
  if (txSize_ == kCapacity) {
    txOverflow_ = true;
    return 0;
  }
  txBuffer_[txTail_] = value;
  txTail_ = (txTail_ + 1) % kCapacity;
  ++txSize_;
  return 1;
}

bool AssistantBluetooth::pop(uint8_t& value) {
  bool available = false;
  portENTER_CRITICAL(&mutex_);
  if (connected_ && !rxOverflow_ && generation_ == sessionGeneration_ && rxSize_) {
    value = rx_[rxHead_];
    rxHead_ = (rxHead_ + 1) % kCapacity;
    --rxSize_;
    available = true;
  }
  portEXIT_CRITICAL(&mutex_);
  return available;
}

void AssistantBluetooth::disconnect(uint16_t id, const char* reason) {
  closing_ = true;
  Serial.printf("BLE DISCONNECT: %s\n", reason);
  disconnected_(millis());
  server_->disconnect(id);
}

void AssistantBluetooth::update(uint32_t now) {
  bool connected, overflow;
  uint16_t id;
  uint32_t generation;
  portENTER_CRITICAL(&mutex_);
  connected = connected_;
  overflow = rxOverflow_;
  id = connectionId_;
  generation = generation_;
  portEXIT_CRITICAL(&mutex_);
  if (generation != sessionGeneration_) {
    if (session_) disconnected_(now);
    sessionGeneration_ = generation;
    receiver_ = assistant::LineReceiver{};
    txHead_ = txTail_ = txSize_ = 0;
    txOverflow_ = closing_ = false;
    session_ = connected;
    restartAdvertising_ = !connected;
    disconnectedAt_ = lastSeen_ = now;
    label_ = connected ? "Da ket noi" : "Cho ket noi";
    Serial.println(connected ? "BLE APP CONNECTED" : "BLE APP DISCONNECTED");
  }
  if (restartAdvertising_ && now - disconnectedAt_ >= 250) {
    // Restart from loop, after the stack finishes its disconnect callback.
    subscription_->setNotifications(false);
    BLEDevice::startAdvertising();
    restartAdvertising_ = false;
  }
  if (!session_ || closing_) return;
  if (overflow || txOverflow_ || now - lastSeen_ >= assistant_config::kConnectionTimeoutMs) {
    disconnect(id, overflow || txOverflow_ ? "BUFFER_OVERFLOW" : "HEARTBEAT_TIMEOUT");
    return;
  }
  uint8_t byte;
  for (int budget = 64; budget > 0 && pop(byte); --budget) {
    const auto result = receiver_.push(static_cast<char>(byte));
    if (result == assistant::LineReceiver::Result::Line) {
      lastSeen_ = now;
      command_(receiver_.line(), now, *this);
    } else if (result == assistant::LineReceiver::Result::TooLong) {
      println("ERR LINE_TOO_LONG");
    } else if (result == assistant::LineReceiver::Result::InvalidCharacter) {
      println("ERR ASCII_COMMANDS_ONLY");
    }
  }
  if (txSize_ && subscription_->getNotifications() && now - lastNotify_ >= 10) {
    uint8_t packet[20];  // Works even with the minimum ATT MTU of 23 bytes.
    const size_t length = txSize_ < sizeof(packet) ? txSize_ : sizeof(packet);
    for (size_t i = 0; i < length; ++i) packet[i] = txBuffer_[(txHead_ + i) % kCapacity];
    tx_->setValue(packet, length);
    notifyFailed_ = false;
    tx_->notify();
    if (notifyFailed_) {
      disconnect(id, "NOTIFY_FAILED");
      return;
    }
    txHead_ = (txHead_ + length) % kCapacity;
    txSize_ -= length;
    lastNotify_ = now;
  }
}
