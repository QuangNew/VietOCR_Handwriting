// Standalone diagnostic: no TFT, buzzer, Wi-Fi, Bluetooth or saved settings.
#include <Arduino.h>
#include <esp_camera.h>
#include <esp_jpg_decode.h>
#include <string.h>

struct JpegInput { const uint8_t* data; size_t size; bool dimensions; };

bool validJpeg(camera_fb_t* frame) {
  if (!frame || frame->format != PIXFORMAT_JPEG || frame->len < 4 ||
      frame->buf[0] != 0xff || frame->buf[1] != 0xd8 ||
      frame->buf[frame->len-2] != 0xff || frame->buf[frame->len-1] != 0xd9) return false;
  JpegInput input{frame->buf, frame->len, false};
  auto read = [](void* arg, size_t offset, uint8_t* output, size_t count) -> size_t {
    auto& in = *static_cast<JpegInput*>(arg);
    if (offset >= in.size) return 0;
    if (count > in.size-offset) count = in.size-offset;
    if (output) memcpy(output,in.data+offset,count);
    return count;
  };
  auto write = [](void* arg, uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint8_t* pixels) -> bool {
    auto& in = *static_cast<JpegInput*>(arg);
    if (!pixels && x == 0 && y == 0) in.dimensions = (w == 40 && h == 30);
    return in.dimensions; // Decode QVGA at 1/8 size; discard pixels.
  };
  return esp_jpg_decode(input.size,JPG_SCALE_8X,read,write,&input) == ESP_OK && input.dimensions;
}

bool tryCamera(int pwdn) {
  pinMode(38, INPUT); // Do not inherit a driven-low PWDN from a previous trial.
  Serial.printf("\nTHU PWDN=%d, XCLK=20MHz\n",pwdn);
  camera_config_t c{};
  c.pin_pwdn = pwdn; c.pin_reset = -1;
  c.pin_xclk = 15; c.pin_sccb_sda = 4; c.pin_sccb_scl = 5;
  c.pin_d0 = 11; c.pin_d1 = 9; c.pin_d2 = 8; c.pin_d3 = 10;
  c.pin_d4 = 12; c.pin_d5 = 18; c.pin_d6 = 17; c.pin_d7 = 16;
  c.pin_vsync = 6; c.pin_href = 7; c.pin_pclk = 13;
  c.xclk_freq_hz = 20000000;
  c.ledc_timer = LEDC_TIMER_1; c.ledc_channel = LEDC_CHANNEL_2;
  c.pixel_format = PIXFORMAT_JPEG; c.frame_size = FRAMESIZE_QVGA;
  c.jpeg_quality = 12; c.fb_count = 1;
  c.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
  c.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  const esp_err_t error = esp_camera_init(&c);
  if (error != ESP_OK) {
    Serial.printf("INIT FAIL: %s (0x%x)\n",esp_err_to_name(error),error);
    esp_camera_deinit();
    return false;
  }
  sensor_t* sensor = esp_camera_sensor_get();
  const uint16_t pid = sensor ? sensor->id.PID : 0;
  Serial.printf("CAMERA PID=0x%04x (%s)\n",pid,
                pid == OV3660_PID ? "OV3660" : pid == OV5640_PID ? "OV5640" : "khac");
  delay(300);
  int good = 0;
  for (int i = 0; i < 3; ++i) {
    camera_fb_t* frame = esp_camera_fb_get();
    const bool valid = validJpeg(frame);
    Serial.printf("JPEG %d: %s, %u bytes\n",i+1,valid ? "PASS" : "FAIL",frame ? unsigned(frame->len) : 0);
    if (valid) ++good;
    if (frame) esp_camera_fb_return(frame);
  }
  esp_camera_deinit();
  if (good != 3 || !pid) { Serial.println("CAPTURE FAIL"); return false; }
  Serial.println("=== WORKS: CAMERA PINOUT ===");
  Serial.println("D0=11 D1=9 D2=8 D3=10 D4=12 D5=18 D6=17 D7=16");
  Serial.println("XCLK=15 PCLK=13 VSYNC=6 HREF=7 SDA=4 SCL=5");
  Serial.printf("PWDN=%d RESET=-1\n",pwdn);
  Serial.println("=== END PINOUT ===");
  return true;
}

void scanCamera() {
  Serial.println("\nESP32-S3 CAMERA PROBE: thu 2 pinout pho bien.");
  Serial.printf("Flash=%lu MB PSRAM=%lu MB\n",(unsigned long)ESP.getFlashChipSize()/1048576,
                (unsigned long)ESP.getPsramSize()/1048576);
  const bool withoutPwdn = tryCamera(-1);
  delay(500);
  const bool withPwdn38 = tryCamera(38);
  if (!withoutPwdn && !withPwdn38) Serial.println("CHUA TIM THAY: gui nguyen log; khong ket luan camera hong.");
  if (withoutPwdn && withPwdn38) Serial.println("Ca hai chay: PWDN chua xac dinh duoc day noi vat ly; co the dung -1.");
  Serial.println("XONG. Gui R de thu lai, hoac nhan RESET de xem lai log.");
}

void setup() {
  Serial.begin(115200);
  const uint32_t start = millis();
  while (!Serial && millis()-start < 3000) delay(10);
  delay(2500);
  scanCamera();
}

void loop() {
  if (Serial.available()) {
    const int ch = Serial.read();
    if (ch == 'R' || ch == 'r') scanCamera();
  }
  delay(10);
}
