#include "assistant_logic.h"
#include <VietMusicSongs.h>

#include <ctype.h>
#include <string.h>

namespace assistant {
namespace {
bool numericArgument(const char* argument, int minimum, int maximum, int& value) {
  if (!argument || !*argument) return false;
  int number = 0;
  for (const char* cursor = argument; *cursor; ++cursor) {
    if (*cursor < '0' || *cursor > '9') return false;
    number = number * 10 + (*cursor - '0');
    if (number > maximum) return false;
  }
  if (number < minimum) return false;
  value = number;
  return true;
}

struct DemoStage { State state; uint32_t duration; };
constexpr DemoStage kDemoStages[] = {
    {State::Awake, 2000}, {State::Received, 1200}, {State::Processing, 5200},
    {State::Done, 3500}, {State::Idle, 1600}, {State::Sleeping, 1200}};
constexpr uint8_t kDemoStagesCount = sizeof(kDemoStages) / sizeof(kDemoStages[0]);

}  // namespace

const char* stateName(State state) {
  switch (state) {
    case State::Sleeping: return "sleep";
    case State::Awake: return "awake";
    case State::Idle: return "idle";
    case State::Received: return "received";
    case State::Processing: return "processing";
    case State::Done: return "done";
    case State::Error: return "error";
  }
  return "unknown";
}

bool parseCommand(const char* line, Command& command) {
  if (!line) return false;
  char text[LineReceiver::kCapacity];
  size_t length = strlen(line);
  if (!length || length >= sizeof(text)) return false;
  for (size_t i = 0; i <= length; ++i) {
    text[i] = static_cast<char>(toupper(static_cast<unsigned char>(line[i])));
  }
  char* save = nullptr;
  const char* verb = strtok_r(text, " \t\r\n", &save);
  const char* argument = strtok_r(nullptr, " \t\r\n", &save);
  if (!verb || strtok_r(nullptr, " \t\r\n", &save)) return false;
  command.value = 0;
  if (!strcmp(verb, "RECEIVED")) {
    command.type = CommandType::Received;
    command.value = 1;
    return !argument || numericArgument(argument, 1, 10, command.value);
  }
  if (!strcmp(verb, "PROGRESS")) {
    command.type = CommandType::Progress;
    return numericArgument(argument, 0, 100, command.value);
  }
  if (!strcmp(verb, "MUTE")) {
    command.type = CommandType::Mute;
    if (argument && !strcmp(argument, "ON")) { command.value = 1; return true; }
    if (argument && !strcmp(argument, "OFF")) return true;
    return false;
  }
  if (!strcmp(verb, "THEME")) {
    command.type = CommandType::Theme;
    if (argument && !strcmp(argument, "DARK")) { command.value = 1; return true; }
    if (argument && !strcmp(argument, "LIGHT")) return true;
    return false;
  }
  if (!strcmp(verb, "MUSIC")) {
    if (!argument) return false;
    if (!strcmp(argument, "STOP")) { command.type = CommandType::MusicStop; return true; }
    if (!strcmp(argument, "LIST")) { command.type = CommandType::MusicList; return true; }
    vietmusic::Song song;
    if (!vietmusic::findSong(argument, song)) return false;
    command.type = CommandType::Music;
    command.value = static_cast<int>(song);
    return true;
  }
  if (argument) return false;
  struct Entry { const char* name; CommandType type; };
  static const Entry commands[] = {
      {"WAKE", CommandType::Wake}, {"AWAKE", CommandType::Wake},
      {"PROCESS", CommandType::Process}, {"PROCESSING", CommandType::Process},
      {"DONE", CommandType::Done}, {"ERROR", CommandType::Error},
      {"SLEEP", CommandType::Sleep}, {"DEMO", CommandType::Demo},
      {"STOP", CommandType::Stop}, {"BEEP", CommandType::Beep},
      {"STATUS", CommandType::Status}, {"HELP", CommandType::Help}, {"PING", CommandType::Ping}};
  for (const Entry& entry : commands) {
    if (!strcmp(verb, entry.name)) { command.type = entry.type; return true; }
  }
  return false;
}

LineReceiver::Result LineReceiver::push(char character) {
  if (character == '\r' || character == '\n') {
    Result result = rejected_;
    if (result == Result::None && length_) {
      buffer_[length_] = '\0';
      result = Result::Line;
    }
    length_ = 0;
    rejected_ = Result::None;
    return result;
  }
  if (rejected_ != Result::None) return Result::None;
  if ((character < 32 && character != '\t') || static_cast<unsigned char>(character) > 126) {
    rejected_ = Result::InvalidCharacter;
  } else if (length_ >= kCapacity - 1) {
    rejected_ = Result::TooLong;
  } else {
    buffer_[length_++] = character;
  }
  return Result::None;
}

void Model::enter(State next, uint32_t now) {
  state = next;
  stateSince = now;
  progress = next == State::Done ? 100 : -1;
  if (next == State::Sleeping || next == State::Awake) imageCount = 0;
}

bool Model::update(uint32_t now) {
  const uint32_t elapsed = now - stateSince;
  if ((state == State::Awake && elapsed >= 1600) || (state == State::Done && elapsed >= 3500)) {
    enter(State::Idle, now);
    return true;
  }
  return false;
}

bool Model::setProgress(int value) {
  if (state != State::Processing || value < 0 || value > 100) return false;
  progress = value;
  return true;
}

void Demo::start(Model& model, uint32_t now) {
  active_ = true;
  stage_ = 0;
  stageSince_ = now;
  model.enter(State::Awake, now);
}

bool Demo::update(Model& model, uint32_t now) {
  if (!active_) return false;
  bool changed = false;
  while (now - stageSince_ >= kDemoStages[stage_].duration) {
    stageSince_ += kDemoStages[stage_].duration;
    if (++stage_ == kDemoStagesCount) { active_ = false; return changed; }
    model.enter(kDemoStages[stage_].state, stageSince_);
    if (model.state == State::Received) model.imageCount = 3;
    changed = true;
  }
  if (model.state == State::Processing) {
    model.setProgress(static_cast<int>((now - stageSince_) * 100 / kDemoStages[stage_].duration));
  }
  return changed;
}

}  // namespace assistant
