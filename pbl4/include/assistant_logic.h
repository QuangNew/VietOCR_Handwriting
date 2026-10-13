#pragma once

#include <stddef.h>
#include <stdint.h>

namespace assistant {

enum class State : uint8_t { Sleeping, Awake, Idle, Received, Processing, Done, Error };
const char* stateName(State state);

enum class CommandType : uint8_t {
  Wake, Received, Process, Progress, Done, Error, Sleep, Demo, Stop,
  Mute, Beep, Status, Help, Ping
};

struct Command {
  CommandType type = CommandType::Help;
  int value = 0;
};

// ASCII protocol, case insensitive, one command per line. No heap allocation.
bool parseCommand(const char* line, Command& command);

class LineReceiver {
 public:
  static constexpr size_t kCapacity = 80;
  enum class Result { None, Line, TooLong, InvalidCharacter };
  Result push(char character);
  const char* line() const { return buffer_; }

 private:
  char buffer_[kCapacity] = {};
  size_t length_ = 0;
  Result rejected_ = Result::None;
};

struct Model {
  State state = State::Sleeping;
  uint32_t stateSince = 0;
  int progress = -1;  // -1: indeterminate, otherwise 0..100.
  uint8_t imageCount = 0;

  void enter(State next, uint32_t now);
  bool update(uint32_t now);
  bool setProgress(int value);
};

class Demo {
 public:
  void start(Model& model, uint32_t now);
  void stop() { active_ = false; }
  bool update(Model& model, uint32_t now);
  bool active() const { return active_; }

 private:
  bool active_ = false;
  uint8_t stage_ = 0;
  uint32_t stageSince_ = 0;
};

struct SoundStep {
  bool on;
  uint16_t milliseconds;
};

struct SoundPattern {
  const SoundStep* steps;
  uint8_t count;
};

SoundPattern soundFor(State state);
SoundPattern testSound();

// TMB12A05 has its own oscillator: only switch it on/off, without tone()/PWM.
class Buzzer {
 public:
  void play(SoundPattern pattern, uint32_t now);
  void update(uint32_t now);
  void stop();
  void setMuted(bool muted);
  bool muted() const { return muted_; }
  bool output() const { return output_; }
  bool playing() const { return pattern_.steps != nullptr; }

 private:
  SoundPattern pattern_ = {nullptr, 0};
  uint8_t index_ = 0;
  uint32_t stepSince_ = 0;
  bool output_ = false;
  bool muted_ = false;
};

}  // namespace assistant
