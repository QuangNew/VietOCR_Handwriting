#include <Arduino.h>
#include "assistant_config.h"
#include "assistant_display.h"
#include "assistant_logic.h"
#include "assistant_bluetooth.h"

namespace {
assistant::Model model;
assistant::Demo demo;
assistant::Buzzer buzzer;
assistant::LineReceiver receiver;
AssistantDisplay display;
bool displayDirty = true;
bool lastBuzzerOutput = false;
bool announcedDemo = false;

void handleCommand(const char* line, uint32_t now, Print& response);
void sleepAfterDisconnect(uint32_t now) {
  if (model.state != assistant::State::Sleeping) handleCommand("STOP", now, Serial);
}
AssistantBluetooth bluetooth(handleCommand, sleepAfterDisconnect);

void writeBuzzer() {
  if (lastBuzzerOutput == buzzer.output()) return;
  lastBuzzerOutput = buzzer.output();
  digitalWrite(assistant_config::kBuzzerPin,
               buzzer.output() == assistant_config::kBuzzerActiveHigh ? HIGH : LOW);
}

void announceState(uint32_t now, bool sound = true) {
  displayDirty = true;
  Serial.printf("STATE %s\n", assistant::stateName(model.state));
  if (sound) buzzer.play(assistant::soundFor(model.state), now);
  writeBuzzer();
}

void enterState(assistant::State state, uint32_t now) {
  demo.stop();
  model.enter(state, now);
  announceState(now);
}

void printStatus(Print& response) {
  response.printf("STATUS {\"state\":\"%s\",\"progress\":%d,\"images\":%u,\"muted\":%s,\"demo\":%s}\n",
                assistant::stateName(model.state), model.progress, model.imageCount,
                buzzer.muted() ? "true" : "false", demo.active() ? "true" : "false");
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
    case CommandType::Beep:
      buzzer.play(assistant::testSound(), now);
      writeBuzzer();
      response.println("OK BEEP");
      break;
    case CommandType::Status: printStatus(response); break;
    case CommandType::Ping: response.println("PONG"); break;
    case CommandType::Help:
      response.println("COMMANDS WAKE | RECEIVED [1..10] | PROCESS | PROGRESS 0..100 | DONE | ERROR | SLEEP");
      response.println("COMMANDS DEMO | STOP | MUTE ON/OFF | BEEP | STATUS | PING | HELP");
      response.println("One ASCII command per line (LF/CRLF). DEMO runs one cycle. STOP also silences buzzer.");
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
  // Keep the active buzzer silent during display initialization.
  digitalWrite(assistant_config::kBuzzerPin, assistant_config::kBuzzerActiveHigh ? LOW : HIGH);
  pinMode(assistant_config::kBuzzerPin, OUTPUT);
  buzzer.setMuted(!assistant_config::kSoundEnabled);
  Serial.begin(assistant_config::kSerialBaud);
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
