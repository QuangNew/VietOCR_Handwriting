// Host tests: no board, Arduino framework, or third-party test library needed.
#include "assistant_logic.h"
#include <VietMusicSongs.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

using namespace assistant;
int checks = 0;
#define CHECK(expression) do { \
  ++checks; \
  if (!(expression)) { \
    fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #expression); \
    exit(1); \
  } \
} while (false)

void testCommands() {
  struct Accepted { const char* text; CommandType type; int value; };
  const Accepted valid[] = {
      {"WAKE", CommandType::Wake, 0}, {"  awake\t", CommandType::Wake, 0},
      {"received", CommandType::Received, 1}, {"RECEIVED 1", CommandType::Received, 1},
      {"received 10", CommandType::Received, 10}, {"PROCESS", CommandType::Process, 0},
      {"RECEIVED 11", CommandType::Received, 11}, {"RECEIVED 1000", CommandType::Received, 1000},
      {"RECEIVED 2147483647", CommandType::Received, 2147483647},
      {"processing", CommandType::Process, 0}, {"PROGRESS 0", CommandType::Progress, 0},
      {"progress 100", CommandType::Progress, 100}, {"DONE", CommandType::Done, 0},
      {"ERROR", CommandType::Error, 0}, {"SLEEP", CommandType::Sleep, 0},
      {"DEMO", CommandType::Demo, 0}, {"STOP", CommandType::Stop, 0},
      {"mute on", CommandType::Mute, 1}, {"MUTE OFF", CommandType::Mute, 0},
      {"theme dark", CommandType::Theme, 1}, {"THEME LIGHT", CommandType::Theme, 0},
      {"music wake", CommandType::Music, static_cast<int>(vietmusic::Song::Wake)},
      {"music twinkle", CommandType::Music, static_cast<int>(vietmusic::Song::Twinkle)},
      {"MUSIC SCALE", CommandType::Music, static_cast<int>(vietmusic::Song::Scale)},
      {"MUSIC COIN", CommandType::Music, static_cast<int>(vietmusic::Song::Coin)},
      {"music jump", CommandType::Music, static_cast<int>(vietmusic::Song::Jump)},
      {"MUSIC POWERUP", CommandType::Music, static_cast<int>(vietmusic::Song::PowerUp)},
      {"MUSIC WIN", CommandType::Music, static_cast<int>(vietmusic::Song::Win)},
      {"MUSIC HURT", CommandType::Music, static_cast<int>(vietmusic::Song::Hurt)},
      {"MUSIC STOP", CommandType::MusicStop, 0}, {"MUSIC LIST", CommandType::MusicList, 0},
      {"BEEP", CommandType::Beep, 0}, {"STATUS", CommandType::Status, 0},
      {"HELP", CommandType::Help, 0}, {"PING", CommandType::Ping, 0}};
  Command command;
  for (const auto& item : valid) {
    CHECK(parseCommand(item.text, command));
    CHECK(command.type == item.type && command.value == item.value);
  }
  const char* invalid[] = {nullptr, "", "   ", "UNKNOWN", "WAKE NOW", "RECEIVED 0",
      "RECEIVED 2147483648", "RECEIVED 999999999999999999999999", "RECEIVED -1", "RECEIVED 1 2", "RECEIVED 1.5", "PROGRESS",
      "PROGRESS -1", "PROGRESS 101", "PROGRESS 99999999999999999999999999",
      "PROGRESS 50%", "PROGRESS +1", "PROGRESS 10 EXTRA", "MUTE", "MUTE YES", "MUTE ON OFF",
      "THEME", "THEME BLUE", "THEME DARK EXTRA", "MUSIC", "MUSIC UNKNOWN",
      "MUSIC 440", "MUSIC SCALE EXTRA", "MUSIC STOP EXTRA", "MUSIC LIST EXTRA"};
  for (const char* text : invalid) CHECK(!parseCommand(text, command));
  char longLine[LineReceiver::kCapacity + 1];
  memset(longLine, 'A', sizeof(longLine) - 1);
  longLine[sizeof(longLine) - 1] = '\0';
  CHECK(!parseCommand(longLine, command));
}

void testReceiver() {
  LineReceiver receiver;
  using Result = LineReceiver::Result;
  CHECK(receiver.push('\n') == Result::None);
  for (char character : "WAKE") {
    if (character) CHECK(receiver.push(character) == Result::None);
  }
  CHECK(receiver.push('\r') == Result::Line);
  CHECK(strcmp(receiver.line(), "WAKE") == 0);
  CHECK(receiver.push('\n') == Result::None);  // CRLF produces one command.
  for (size_t i = 0; i < LineReceiver::kCapacity - 1; ++i) receiver.push('A');
  CHECK(receiver.push('\n') == Result::Line);
  CHECK(strlen(receiver.line()) == LineReceiver::kCapacity - 1);
  for (size_t i = 0; i < LineReceiver::kCapacity; ++i) receiver.push('A');
  for (char character : "WAKE") if (character) receiver.push(character);
  CHECK(receiver.push('\n') == Result::TooLong);  // Never execute a truncated suffix.
  for (char character : "PING") if (character) receiver.push(character);
  CHECK(receiver.push('\n') == Result::Line);
  CHECK(strcmp(receiver.line(), "PING") == 0);
  receiver.push('W'); receiver.push('\0'); receiver.push('A');
  CHECK(receiver.push('\n') == Result::InvalidCharacter);
  receiver.push(static_cast<char>(0xc3));
  CHECK(receiver.push('\r') == Result::InvalidCharacter);
  CHECK(receiver.push('\n') == Result::None);
  for (char character : "PROGRESS\t25") if (character) receiver.push(character);
  CHECK(receiver.push('\n') == Result::Line);
  Command command;
  CHECK(parseCommand(receiver.line(), command));
  CHECK(command.type == CommandType::Progress && command.value == 25);
}

void testModel() {
  Model model;
  CHECK(model.state == State::Sleeping && model.progress == -1);
  CHECK(!model.setProgress(10));
  model.enter(State::Awake, 100);
  CHECK(!model.update(1699));
  CHECK(model.update(1700));
  CHECK(model.state == State::Idle);
  model.enter(State::Received, 2000);
  model.imageCount = 10;
  CHECK(!model.update(200000));
  CHECK(!model.setProgress(0));
  model.enter(State::Processing, 200001);
  CHECK(model.imageCount == 10 && model.progress == -1);
  CHECK(!model.setProgress(-1));
  CHECK(!model.setProgress(101));
  CHECK(model.setProgress(0));
  CHECK(model.setProgress(100));
  CHECK(!model.update(500000));  // 100% still needs a real DONE command.
  CHECK(model.state == State::Processing);
  model.enter(State::Done, 500000);
  CHECK(model.progress == 100);
  CHECK(!model.update(503499));
  CHECK(model.update(503500));
  CHECK(model.state == State::Idle && model.imageCount == 10);
  model.enter(State::Sleeping, 504000);
  CHECK(model.imageCount == 0 && model.progress == -1);
  model.darkTheme = false;
  model.enter(State::Processing, 504100);
  CHECK(!model.darkTheme);  // State changes must not reset the app's appearance.
  model.enter(State::Error, 505000);
  CHECK(!model.update(900000));
  const uint32_t nearWrap = UINT32_MAX - 1000;
  model.enter(State::Awake, nearWrap);
  CHECK(!model.update(nearWrap + 1599u));
  CHECK(model.update(nearWrap + 1600u));
  CHECK(model.state == State::Idle);
}

void testDemo() {
  Model model;
  Demo demo;
  demo.start(model, 100);
  CHECK(demo.active() && model.state == State::Awake);
  CHECK(!demo.update(model, 2099));
  CHECK(demo.update(model, 2100));
  CHECK(model.state == State::Received && model.imageCount == 3);
  CHECK(demo.update(model, 3300));
  CHECK(model.state == State::Processing && model.progress == 0);
  CHECK(!demo.update(model, 5900));
  CHECK(model.progress == 50);
  demo.update(model, 8499);
  CHECK(model.progress == 99);
  CHECK(demo.update(model, 8500));
  CHECK(model.state == State::Done && model.progress == 100);
  CHECK(demo.update(model, 12000));
  CHECK(model.state == State::Idle);
  CHECK(demo.update(model, 13600));
  CHECK(model.state == State::Sleeping && model.imageCount == 0);
  CHECK(!demo.update(model, 14800));
  CHECK(!demo.active());
  demo.start(model, 20000);
  CHECK(demo.update(model, 70000));  // Catch up safely after a delayed loop.
  CHECK(!demo.active() && model.state == State::Sleeping);
  const uint32_t nearWrap = UINT32_MAX - 1500;
  demo.start(model, nearWrap);
  CHECK(demo.update(model, nearWrap + 3200u));
  CHECK(model.state == State::Processing);
  demo.stop();
  model.enter(State::Error, nearWrap + 3300u);
  CHECK(!demo.update(model, nearWrap + 20000u));
  CHECK(model.state == State::Error);
}

int main() {
  testCommands(); testReceiver(); testModel(); testDemo();
  printf("PASS: %d checks (protocol, music commands, framing, states, demo, timer wrap)\n", checks);
  return 0;
}
