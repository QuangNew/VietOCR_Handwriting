// Diagnostic only. Direct GPIO, no SPI.begin(), TFT_eSPI object, camera or BLE.
#include <Arduino.h>
#include <TFT_Drivers/ILI9341_Defines.h>

namespace {
constexpr int kMosi=21, kClock=47, kMiso=39, kReset=40, kDc=41, kCs=42;

uint8_t transfer(uint8_t value, bool reading=false) {
  uint8_t received = 0;
  for (int bit=7; bit>=0; --bit) {
    digitalWrite(kClock,LOW);
    digitalWrite(kMosi,(value >> bit) & 1);
    delayMicroseconds(1);
    digitalWrite(kClock,HIGH);
    if (reading) received = uint8_t((received << 1) | digitalRead(kMiso));
    delayMicroseconds(1);
  }
  digitalWrite(kClock,LOW);
  return received;
}
void writecommand(uint8_t value) {
  digitalWrite(kCs,LOW); digitalWrite(kDc,LOW);
  transfer(value); digitalWrite(kCs,HIGH);
}
void writedata(uint8_t value) {
  digitalWrite(kCs,LOW); digitalWrite(kDc,HIGH);
  transfer(value); digitalWrite(kCs,HIGH);
}
void begin_tft_write() { digitalWrite(kCs,LOW); }
void end_tft_write() { digitalWrite(kCs,HIGH); }

void initialize() {
  pinMode(14,OUTPUT); digitalWrite(14,LOW); // Keep the active buzzer quiet.
  pinMode(kCs,OUTPUT); digitalWrite(kCs,HIGH);
  pinMode(kDc,OUTPUT); digitalWrite(kDc,HIGH);
  pinMode(kClock,OUTPUT); digitalWrite(kClock,LOW);
  pinMode(kMosi,OUTPUT); digitalWrite(kMosi,LOW);
  pinMode(kMiso,INPUT_PULLUP);
  pinMode(kReset,OUTPUT);
  digitalWrite(kReset,HIGH); delay(50);
  digitalWrite(kReset,LOW); delay(50);
  digitalWrite(kReset,HIGH); delay(200);
  // Reuse the proven register sequence, but execute it through GPIO functions
  // above. The TFT_eSPI hardware-SPI driver is never called by this program.
  #include <TFT_Drivers/ILI9341_Init.h>
  delay(150);
}
void readId() {
  digitalWrite(kCs,LOW); digitalWrite(kDc,LOW);
  transfer(0xd3); digitalWrite(kDc,HIGH);
  uint8_t bytes[4];
  for (auto& value : bytes) value = transfer(0,true);
  digitalWrite(kCs,HIGH);
  Serial.printf("SOFT ID D3: %02x %02x %02x %02x (ILI9341 normally ends in 93 41)\n",
                bytes[0],bytes[1],bytes[2],bytes[3]);
}
void drawBars() {
  writecommand(0x2a); // 240 columns, portrait orientation from the init sequence.
  writedata(0); writedata(0); writedata(0); writedata(239);
  writecommand(0x2b); // 320 rows.
  writedata(0); writedata(0); writedata(1); writedata(63);
  writecommand(0x2c);
  digitalWrite(kCs,LOW); digitalWrite(kDc,HIGH);
  for (int y=0; y<320; ++y) {
    const uint16_t color = y < 107 ? 0xf800 : y < 213 ? 0x07e0 : 0x001f;
    for (int x=0; x<240; ++x) { transfer(color >> 8); transfer(color & 0xff); }
    delay(1); // Yield during the deliberately slow GPIO transfer.
  }
  digitalWrite(kCs,HIGH);
  Serial.println("BARS SENT: look for red/green/blue bands. This message is not a display PASS.");
}
void run() {
  Serial.println("\nTFT DIRECT GPIO TEST | CS42 RST40 DC41 MOSI21 SCK47 MISO39");
  Serial.println("Camera/BLE/hardware SPI disabled. Keep the current wires.");
  initialize(); readId(); drawBars();
  Serial.println("Send R to repeat. Keep the log and report whether the bands are visible.");
}
}  // namespace

void setup() {
  Serial.begin(115200); delay(2000); run();
}
void loop() {
  if (Serial.available()) {
    const int value = Serial.read();
    if (value == 'r' || value == 'R') run();
  }
  delay(10);
}
