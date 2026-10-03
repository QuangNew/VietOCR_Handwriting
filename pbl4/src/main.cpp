#include <Arduino.h>
#include <TFT_eSPI.h>
#include <JPEGDEC.h>
#include <LittleFS.h> // Gọi thư viện đọc bộ nhớ trong

TFT_eSPI tft = TFT_eSPI();
JPEGDEC jpeg;

// Khai báo bộ đệm lưu khung hình trên PSRAM
uint8_t *frameBuffer;
const int MAX_FRAME_SIZE = 102400; // 100KB cho 1 khung hình 320x240

// Hàm Callback: Đẩy từng mảng pixel đã giải mã lên màn hình
int JPEGDraw(JPEGDRAW *pDraw) {
  tft.pushImage(pDraw->x, pDraw->y, pDraw->iWidth, pDraw->iHeight, pDraw->pPixels);
  return 1; 
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  tft.init();
  tft.invertDisplay(false);
  tft.setRotation(1);
  tft.fillScreen(TFT_BLACK);
  tft.setSwapBytes(false); // Không đổi byte khi đẩy dữ liệu lên màn hình

  // Cấp phát vùng nhớ từ PSRAM
  frameBuffer = (uint8_t *)heap_caps_malloc(MAX_FRAME_SIZE, MALLOC_CAP_SPIRAM);
  if (!frameBuffer) {
    Serial.println("Loi: Khong the cap phat PSRAM!");
    return;
  }

  // Khởi tạo bộ nhớ trong LittleFS
  if (!LittleFS.begin(true)) {
    Serial.println("Loi: Khong the khoi tao LittleFS!");
    return;
  }
  Serial.println("LittleFS san sang!");
}

void loop() {
  // Mở file video từ bộ nhớ trong
  File vFile = LittleFS.open("/rickroll.mjpeg", "r");
  if (!vFile) {
    Serial.println("Khong tim thay rickroll.mjpeg trong bo nho");
    delay(5000);
    return;
  }

  const int BUF_SIZE = 512;
  uint8_t buf[BUF_SIZE];
  int frameSize = 0;
  bool readingFrame = false;
  uint8_t lastByte = 0x00;

  Serial.println("Dang phat video...");

  // Quét liên tục các byte để bóc tách từng khung ảnh JPEG
  while (vFile.available()) {
    int bytesRead = vFile.read(buf, BUF_SIZE);
    
    for (int i = 0; i < bytesRead; i++) {
      uint8_t currByte = buf[i];
      
      if (!readingFrame) {
        if (lastByte == 0xFF && currByte == 0xD8) {
          readingFrame = true;
          frameSize = 0;
          frameBuffer[frameSize++] = 0xFF;
          frameBuffer[frameSize++] = 0xD8;
        }
      } else {
        frameBuffer[frameSize++] = currByte;
        
        if (frameSize >= MAX_FRAME_SIZE) {
          readingFrame = false; 
        }
        
        if (lastByte == 0xFF && currByte == 0xD9) {
          // Gửi khung hình qua JPEGDEC để giải mã và hiển thị
          if (jpeg.openRAM(frameBuffer, frameSize, JPEGDraw)) {
            jpeg.setPixelType(RGB565_BIG_ENDIAN);
            jpeg.decode(0, 0, 0);
            jpeg.close();
          }
          readingFrame = false; 
        }
      }
      lastByte = currByte;
    }
  }
  
  vFile.close();
  Serial.println("Phat xong, lap lai video...");
}