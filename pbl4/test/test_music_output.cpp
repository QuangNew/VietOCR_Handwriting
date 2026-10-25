#include <Arduino.h>
#include <VietMusic.h>
#include <VietMusicOutput.h>
#include <stdio.h>
#include <stdlib.h>

using namespace vietmusic;
static_assert(notes::B_0 == 31 && notes::B_1 == 62, "Arduino binary macros must not collide with pitches");
namespace fake {
int gpio = -1, writes = 0, tones = 0, attachments = 0, detachments = 0;
uint8_t target = 255;
uint32_t duty = 9999, frequency = 0;
bool attachOk = true, toneOk = true;
void reset() {
  gpio = -1; writes = tones = attachments = detachments = 0;
  target = 255; duty = 9999; frequency = 0; attachOk = toneOk = true;
}
}
void digitalWrite(uint8_t, uint8_t value) { fake::gpio = value; ++fake::writes; }
void pinMode(uint8_t, uint8_t) {}
#if ESP_ARDUINO_VERSION_MAJOR >= 3
bool ledcAttachChannel(uint8_t, uint32_t, uint8_t, uint8_t) { ++fake::attachments; return fake::attachOk; }
bool ledcWrite(uint8_t target, uint32_t duty) { fake::target = target; fake::duty = duty; return true; }
double ledcWriteTone(uint8_t target, uint32_t frequency) {
  fake::target = target; fake::frequency = frequency; ++fake::tones;
  return fake::toneOk ? frequency : 0;
}
bool ledcDetach(uint8_t) { ++fake::detachments; return true; }
constexpr uint8_t pwmTarget = 5;  // Core 3 addresses GPIOs, not channels.
#else
uint32_t ledcSetup(uint8_t, uint32_t frequency, uint8_t) { ++fake::attachments; return fake::attachOk ? frequency : 0; }
void ledcAttachPin(uint8_t, uint8_t) {}
void ledcWrite(uint8_t target, uint32_t duty) { fake::target = target; fake::duty = duty; }
uint32_t ledcWriteTone(uint8_t target, uint32_t frequency) {
  fake::target = target; fake::frequency = frequency; ++fake::tones;
  return fake::toneOk ? frequency : 0;
}
void ledcDetachPin(uint8_t) { ++fake::detachments; }
constexpr uint8_t pwmTarget = 2;  // Core 2 addresses LEDC channels.
#endif

int checks = 0;
#define CHECK(expression) do { ++checks; if (!(expression)) { \
  fprintf(stderr, "FAIL output line %d: %s\n", __LINE__, #expression); exit(1); } } while (false)

void testActive() {
  fake::reset();
  Esp32Output output;
  CHECK(!output.write(440));
  CHECK(output.begin(5, OutputMode::ActiveBuzzer));
  CHECK(fake::gpio == LOW && fake::attachments == 0);
  CHECK(output.write(440) && fake::gpio == HIGH);
  const int writes = fake::writes;
  CHECK(output.write(440) && fake::writes == writes);
  CHECK(output.write(660) && fake::gpio == HIGH && fake::tones == 0);
  CHECK(output.write(0) && fake::gpio == LOW);
  output.end(); CHECK(!output.ready() && fake::gpio == LOW);
  CHECK(output.begin(5, OutputMode::ActiveBuzzer, false));
  CHECK(fake::gpio == HIGH);
  CHECK(output.write(440) && fake::gpio == LOW);
  CHECK(output.write(0) && fake::gpio == HIGH);
  output.end(); CHECK(fake::gpio == HIGH && fake::detachments == 0);
}

void testPassive() {
  fake::reset();
  Esp32Output output;
  CHECK(output.begin(5, OutputMode::PassiveBuzzer, true, 2));
  CHECK(fake::duty == 0 && fake::target == pwmTarget);
  CHECK(output.write(440) && fake::frequency == 440 && fake::target == pwmTarget);
  const int tones = fake::tones;
  CHECK(output.write(440) && fake::tones == tones);
  CHECK(output.write(880) && fake::frequency == 880);
  CHECK(output.write(0) && fake::duty == 0);
  output.end(); CHECK(!output.ready() && fake::detachments == 1 && fake::gpio == LOW);
  output.end(); CHECK(fake::detachments == 1);
  CHECK(output.begin(5, OutputMode::PassiveBuzzer, false, 2));
  CHECK(fake::duty == 1023);  // Active-low driver must be HIGH at rest.
  CHECK(output.write(440));
  CHECK(output.write(0) && fake::duty == 1023);
  CHECK(output.write(440));
  CHECK(output.begin(5, OutputMode::ActiveBuzzer));  // Reconfiguration stops/detaches PWM.
  CHECK(fake::detachments == 2 && fake::gpio == LOW);
  output.end();
}

void testFailureSilencesOutput() {
  fake::reset();
  Esp32Output output;
  fake::attachOk = false;
  CHECK(!output.begin(5, OutputMode::PassiveBuzzer));
  CHECK(!output.ready() && fake::gpio == LOW);
  fake::attachOk = true;
  CHECK(output.begin(5, OutputMode::PassiveBuzzer));
  CHECK(output.write(440));
  fake::toneOk = false;
  CHECK(!output.write(880));
  CHECK(fake::duty == 0);
  CHECK(output.write(0));
  output.end(); CHECK(fake::gpio == LOW);
}

int main() {
  testActive(); testPassive(); testFailureSilencesOutput();
  printf("PASS: %d output checks (active/passive, silence, polarity, LEDC core %d, errors)\n", checks, ESP_ARDUINO_VERSION_MAJOR);
  return 0;
}
