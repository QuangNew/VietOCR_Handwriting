#pragma once
#include <stdint.h>
#include <esp_arduino_version.h>
#define B0 0
#define B1 1
constexpr uint8_t LOW = 0, HIGH = 1, OUTPUT = 1;
void digitalWrite(uint8_t pin, uint8_t value);
void pinMode(uint8_t pin, uint8_t mode);
#if ESP_ARDUINO_VERSION_MAJOR >= 3
bool ledcAttachChannel(uint8_t pin, uint32_t frequency, uint8_t bits, uint8_t channel);
bool ledcWrite(uint8_t pin, uint32_t duty);
double ledcWriteTone(uint8_t pin, uint32_t frequency);
bool ledcDetach(uint8_t pin);
#else
uint32_t ledcSetup(uint8_t channel, uint32_t frequency, uint8_t bits);
void ledcAttachPin(uint8_t pin, uint8_t channel);
void ledcWrite(uint8_t channel, uint32_t duty);
uint32_t ledcWriteTone(uint8_t channel, uint32_t frequency);
void ledcDetachPin(uint8_t pin);
#endif
