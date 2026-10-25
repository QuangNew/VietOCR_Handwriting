#include <Arduino.h>
#include "assistant_config.h"
#include "assistant_display.h"
#include "assistant_logic.h"
#include "assistant_bluetooth.h"
#include <VietMusic.h>
#include <VietMusicSongs.h>
#include <VietMusicOutput.h>

namespace {
assistant::Model model;
assistant::Demo demo;
vietmusic::Player buzzer;
vietmusic::Esp32Output audioOutput;
assistant::LineReceiver receiver;
AssistantDisplay display;
bool displayDirty = true;
bool announcedDemo = false;

void handleCommand(const char* line, uint32_t now, Print& response);
void sleepAfterDisconnect(uint32_t now) {
  if (model.state != assistant::State::Sleeping || buzzer.playing() || demo.active()) {
    handleCommand("STOP", now, Serial);
  }
}
AssistantBluetooth bluetooth(handleCommand, sleepAfterDisconnect);

void writeBuzzer() {
  if (audioOutput.ready() && !audioOutput.write(buzzer.frequency())) {
    buzzer.stop();
    audioOutput.write(0);
    Serial.println("ERR AUDIO_OUTPUT: check LEDC channel and buzzer configuration");
  }
}

vietmusic::Melody stateSong(assistant::State state) {
  using assistant::State;
  using vietmusic::Song;
  switch (state) {
    case State::Awake: return vietmusic::song(Song::Wake);
    case State::Received: return vietmusic::song(Song::Received);
    case State::Processing: return vietmusic::song(Song::Process);
    case State::Done: return vietmusic::song(Song::Done);
    case State::Error: return vietmusic::song(Song::Error);
    case State::Sleeping: return vietmusic::song(Song::Sleep);
    case State::Idle: return {nullptr, 0, 120, 85};
  }
  return {nullptr, 0, 120, 85};
}

void announceState(uint32_t now, bool sound = true) {
  displayDirty = true;
  Serial.printf("STATE %s\n", assistant::stateName(model.state));
  if (sound) buzzer.play(stateSong(model.state), now);
  writeBuzzer();
}

void enterState(assistant::State state, uint32_t now) {
  demo.stop();
  model.enter(state, now);
  announceState(now);
}

void printStatus(Print& response) {
  response.printf("STATUS {\"state\":\"%s\",\"progress\":%d,\"images\":%u,\"muted\":%s,\"demo\":%s,\"theme\":\"%s\",\"audio\":\"%s\",\"music\":%s,\"note_hz\":%u}\n",
                assistant::stateName(model.state), model.progress, model.imageCount,
                buzzer.muted() ? "true" : "false", demo.active() ? "true" : "false",
                model.darkTheme ? "dark" : "light",
                audioOutput.mode() == vietmusic::OutputMode::PassiveBuzzer ? "passive" : "active",
                buzzer.playing() ? "true" : "false", buzzer.frequency());
}

void handleCommand(const char* line, uint32_t now, Print& response) {
  using assistant::CommandType;
  using assistant::State;
  assistant::Command command;
  if (!assistant::parseCommand(line, command)) {
    response.println("ERR INVALID_COMMAND: send HELP");
    return;
  }
  switch (command.type) {
    case CommandType::Wake:
      enterState(State::Awake, now);
      response.println("OK WAKE");
      break;
    case CommandType::Received:
      enterState(State::Received, now);
      model.imageCount = static_cast<uint8_t>(command.value);
      response.printf("OK RECEIVED %d\n", command.value);
      break;
    case CommandType::Process:
      enterState(State::Processing, now);
      response.println("OK PROCESS");
      break;
    case CommandType::Progress:
      if (!model.setProgress(command.value)) {
        response.println("ERR PROGRESS_REQUIRES_PROCESSING");
        break;
      }
      demo.stop();
      displayDirty = true;
      response.printf("OK PROGRESS %d\n", command.value);
      break;
    case CommandType::Done:
      enterState(State::Done, now);
      response.println("OK DONE");
      break;
    case CommandType::Error:
      enterState(State::Error, now);
      response.println("OK ERROR");
      break;
    case CommandType::Sleep:
      enterState(State::Sleeping, now);
      response.println("OK SLEEP");
      break;
    case CommandType::Demo:
      demo.start(model, now);
      announceState(now);
      response.println("OK DEMO");
      break;
    case CommandType::Stop:
      demo.stop();
      model.enter(State::Sleeping, now);
      buzzer.stop();
      announceState(now, false);
      writeBuzzer();
      response.println("OK STOP");
      break;
    case CommandType::Mute:
      buzzer.setMuted(command.value != 0);
      writeBuzzer();
      displayDirty = true;
      response.printf("OK MUTE %s\n", buzzer.muted() ? "ON" : "OFF");
      break;
    case CommandType::Theme:
      model.darkTheme = command.value != 0;
      displayDirty = true;
      response.printf("OK THEME %s\n", model.darkTheme ? "DARK" : "LIGHT");
      break;
    case CommandType::Beep:
      buzzer.play(vietmusic::song(vietmusic::Song::Test), now);
      writeBuzzer();
      response.println("OK BEEP");
      break;
    case CommandType::Music: {
      const auto song = static_cast<vietmusic::Song>(command.value);
      buzzer.play(vietmusic::song(song), now);
      writeBuzzer();
      response.printf("OK MUSIC %s\n", vietmusic::songName(song));
      break;
    }
    case CommandType::MusicStop:
      buzzer.stop();
      writeBuzzer();
      response.println("OK MUSIC STOP");
      break;
    case CommandType::MusicList:
      response.print("MUSIC");
      for (uint8_t i = 0; i < vietmusic::kSongCount; ++i) {
        response.print(' ');
        response.print(vietmusic::songName(static_cast<vietmusic::Song>(i)));
      }
      response.println();
      break;
    case CommandType::Status: printStatus(response); break;
    case CommandType::Ping: response.println("PONG"); break;
    case CommandType::Help:
      response.println("COMMANDS WAKE | RECEIVED [1..10] | PROCESS | PROGRESS 0..100 | DONE | ERROR | SLEEP");
      response.println("COMMANDS DEMO | STOP | MUTE ON/OFF | THEME DARK/LIGHT | BEEP | STATUS | PING | HELP");
      response.println("COMMANDS MUSIC LIST | MUSIC <name> | MUSIC STOP");
      response.println("One ASCII command per line (LF/CRLF). STOP sleeps; MUSIC STOP only stops audio.");
      break;
  }
}

void pollSerial(uint32_t now) {
  // Bound each iteration so a busy Serial connection cannot starve the animation.
  for (int budget = 64; budget > 0 && Serial.available(); --budget) {
    const auto result = receiver.push(static_cast<char>(Serial.read()));
    if (result == assistant::LineReceiver::Result::Line) {
      handleCommand(receiver.line(), now, Serial);
    } else if (result == assistant::LineReceiver::Result::TooLong) {
      Serial.println("ERR LINE_TOO_LONG");
    } else if (result == assistant::LineReceiver::Result::InvalidCharacter) {
      Serial.println("ERR ASCII_COMMANDS_ONLY");
    }
  }
}
}  // namespace

void setup() {
  // Keep either buzzer type silent while the display and BLE initialize.
  const bool audioReady = audioOutput.begin(assistant_config::kBuzzerPin,
      assistant_config::kBuzzerMode, assistant_config::kBuzzerActiveHigh,
      assistant_config::kBuzzerPwmChannel);
  buzzer.setMuted(!assistant_config::kSoundEnabled);
  Serial.begin(assistant_config::kSerialBaud);
  if (!audioReady) Serial.println("ERR AUDIO_INIT: check LEDC channel and GPIO");
  Serial.println(audioOutput.mode() == vietmusic::OutputMode::ActiveBuzzer
      ? "AUDIO ACTIVE: rhythm only; use a passive buzzer for musical pitch."
      : "AUDIO PASSIVE: LEDC melody output on GPIO 5.");
  display.begin();
  Serial.println("READY VIETOCR_ASSISTANT 1");
  Serial.println("Send HELP for commands; DEMO to preview all normal states.");
  const uint32_t now = millis();
  model.enter(assistant::State::Sleeping, now);
  if (assistant_config::kDemoOnBoot) demo.start(model, now);
  announceState(now, demo.active());
  bluetooth.begin();
}

void loop() {
  const uint32_t now = millis();
  pollSerial(now);
  bluetooth.update(now);
  if (demo.active()) {
    if (demo.update(model, now)) announceState(now);
  } else if (model.update(now)) {
    announceState(now, false);
  }
  if (announcedDemo != demo.active()) {
    announcedDemo = demo.active();
    displayDirty = true;
  }
  buzzer.update(now);
  writeBuzzer();
  display.setConnectionLabel(bluetooth.label());
  display.render(model, demo.active(), buzzer.muted(), now, displayDirty);
  displayDirty = false;
  delay(1);  // Yield to the RTOS; sound patterns and state transitions use millis().
}
