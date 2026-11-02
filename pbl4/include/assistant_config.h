#pragma once

#include <stdint.h>
#include <VietMusicOutput.h>

// The TFT's SPI pins and ILI9341 driver are configured in platformio.ini.
namespace assistant_config {
constexpr char kFirmwareVersion[] = "3.0.0-ov5640";
#ifndef ASSISTANT_BUZZER_PIN
#define ASSISTANT_BUZZER_PIN 5
#endif
constexpr uint8_t kBuzzerPin = ASSISTANT_BUZZER_PIN;
constexpr bool kBuzzerActiveHigh = true;
// TMB12A05: rhythm only. Select PassiveBuzzer after fitting a passive transducer.
constexpr vietmusic::OutputMode kBuzzerMode = vietmusic::OutputMode::ActiveBuzzer;
constexpr uint8_t kBuzzerPwmChannel = 0;
constexpr bool kSoundEnabled = true;
constexpr bool kDemoOnBoot = false;
constexpr uint8_t kDisplayRotation = 1;
constexpr bool kInvertDisplay = false;
constexpr uint32_t kSerialBaud = 115200;
constexpr uint32_t kFrameIntervalUs = 1000000 / 60;  // Animation target, not a guarantee of camera FPS.
constexpr uint32_t kSleepFrameIntervalMs = 150;
constexpr char kBluetoothName[] = "VietOCR-Assistant";
// Nordic UART Service: RX is phone/app -> ESP32, TX is ESP32 -> phone/app.
constexpr char kBleServiceUuid[] = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
constexpr char kBleRxUuid[] = "6e400002-b5a3-f393-e0a9-e50e24dcca9e";
constexpr char kBleTxUuid[] = "6e400003-b5a3-f393-e0a9-e50e24dcca9e";
constexpr char kBleImageUuid[] = "6e400004-b5a3-f393-e0a9-e50e24dcca9e";
constexpr uint32_t kConnectionTimeoutMs = 60000;
}  // namespace assistant_config
