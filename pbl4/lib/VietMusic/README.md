# VietMusic

Thư viện C++ riêng của dự án để lưu nốt nhạc theo Hz và phát giai điệu đơn âm.
PlatformIO tự nhận thư viện tại `pbl4/lib/VietMusic`, không cần tải package mới.

## Phần cứng và chọn chế độ

**TMB12A05 hiện có là còi active**: nó tự phát một cao độ khoảng 2,4 kHz khi cấp
DC. Chế độ `ActiveBuzzer` chỉ phát được **nhịp** của bản nhạc. PWM vào nguồn
còi active không biến nó thành nhạc cụ phát đúng các nốt.
Xem [datasheet nhà sản xuất](https://datasheet.lcsc.com/datasheet/pdf/2a16321f74deffcaef3942d9437fae37.pdf?productCode=C96093).

Để nghe giai điệu đúng cao độ, dùng **buzzer passive không có bộ dao động**,
với mạch điều khiển phù hợp điện áp/dòng của nó. Giữ chân điều khiển GPIO 5;
tham khảo mạch transistor và GND chung trong [README phần cứng](../../README.md#đấu-còi).
Loa thường cần mạch khuếch đại/ghép phù hợp, không nối trực tiếp thay còi vào GPIO.

Sau khi thay còi, sửa `pbl4/include/assistant_config.h` rồi build/nạp lại:

```cpp
constexpr vietmusic::OutputMode kBuzzerMode = vietmusic::OutputMode::PassiveBuzzer;
```

Mặc định vẫn là `ActiveBuzzer` cho TMB12A05 đang dùng. `kBuzzerActiveHigh`
quy định cực tính mạch điều khiển; `kBuzzerPwmChannel` chọn kênh LEDC. Adapter
hỗ trợ API LEDC của Arduino ESP32 2.x và 3.x; firmware dự án hiện build với 2.x.

## Nốt và trường độ

`VietMusicNotes.h` chứa bảng 108 tần số C0–B8 theo A4 = 440 Hz, làm tròn Hz.
Tên nốt: C=Đô, D=Rê, E=Mi, F=Fa, G=Sol, A=La, B=Si; `Cs4` là Đô thăng 4.

| Nốt | C4 | D4 | E4 | F4 | G4 | A4 | B4 | C5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Hz | 262 | 294 | 330 | 349 | 392 | 440 | 494 | 523 |

Dùng `notes::C4`, `notes::A4`, `notes::REST`; hoặc
`notes::frequency(notes::Key::Db, 4)` cho Rê giáng. Riêng Si ở hai quãng thấp
dùng `B_0` / `B_1` vì Arduino đã dùng macro `B0` / `B1` cho số nhị phân.

Mỗi phách nốt đen có 24 tick. `duration::Quarter`, `Eighth`, `Sixteenth`, `Half`,
`Whole`, `DottedQuarter` và `EighthTriplet` hỗ trợ trường độ cơ bản. BPM hợp lệ
20–400; mỗi nốt 1–384 tick; tối đa 512 nốt/bài. Tần số 0 là nghỉ, các tần số
khác phải trong 16–20.000 Hz; đáp ứng âm lượng thực tế phụ thuộc còi.

## Thêm bài nhạc

```cpp
#include <VietMusic.h>
#include <VietMusicOutput.h>

using namespace vietmusic;
static constexpr Note myTune[] = {
    {notes::C5, duration::Eighth},
    {notes::E5, duration::Eighth},
    {notes::REST, duration::Eighth},
    {notes::G5, duration::Quarter},
};
Player player;
Esp32Output output;

void setup() {
  // Chỉ dùng PassiveBuzzer với phần cứng passive.
  output.begin(5, OutputMode::PassiveBuzzer);
  player.play(melody(myTune, 140, 85), millis());
}
void loop() {
  player.update(millis());
  output.write(player.frequency());
  // Vẫn xử lý BLE, màn hình... Không delay theo thời lượng nốt.
}
```

`melody(score, bpm, gatePercent)` quy định tempo và phần trăm thời gian nốt được
phát trước khoảng ngắt. Với gate 85, 15% cuối nốt im lặng để tách hai nốt liên
tiếp; nốt nghỉ luôn im lặng. Score phải còn tồn tại trong suốt lượt phát, nên
khai báo `static constexpr` như ví dụ. Cập nhật `Player` thường xuyên; khi vòng
lặp bị trễ, player nhảy đến nốt hiện tại và bỏ các nốt đã lỡ.

Để chọn bài mới qua BLE/Serial, thêm score và entry trong `VietMusicSongs.cpp`,
thêm ID vào `Song` và tăng `kSongCount` trong `VietMusicSongs.h`. Các giai điệu
WAKE/RECEIVED/PROCESS/DONE/ERROR/SLEEP/TEST là cue ngắn tự soạn; SCALE và
TWINKLE là bài mẫu. Các cue dùng phong cách game arcade: WAKE tăng sức mạnh,
RECEIVED nhặt xu, PROCESS nhảy, DONE thắng cuộc, ERROR trúng đòn và SLEEP hạ âm.
Có thêm tên `COIN`, `JUMP`, `POWERUP`, `WIN`, `HURT` để nghe thử từng hiệu ứng.
Đây là score ngắn tự soạn, không có file âm thanh tải từ trò chơi hoặc video.

## Lệnh thử trên firmware

Gửi mỗi dòng kèm LF qua Serial 115200 hoặc BLE RX sau khi bật TX Notify:

```text
MUSIC LIST       -> MUSIC WAKE RECEIVED PROCESS DONE ERROR SLEEP TEST SCALE TWINKLE COIN JUMP POWERUP WIN HURT
MUSIC COIN       -> OK MUSIC COIN
MUSIC JUMP       -> OK MUSIC JUMP
MUSIC POWERUP    -> OK MUSIC POWERUP
MUSIC WIN        -> OK MUSIC WIN
MUSIC HURT       -> OK MUSIC HURT
MUSIC SCALE      -> OK MUSIC SCALE
MUSIC TWINKLE    -> OK MUSIC TWINKLE
MUSIC STOP       -> OK MUSIC STOP
MUTE ON          -> OK MUTE ON
MUTE OFF         -> OK MUTE OFF
```

Lệnh nhận ACK ngay, không chờ hết nhạc. `MUSIC STOP` chỉ dừng âm thanh; `STOP`
dừng cả demo và đưa trợ lý về ngủ. Mute dừng ngay, unmute không phát lại bài cũ.
Lệnh đổi trạng thái mới ưu tiên cue tương ứng, thay bài đang chạy; PROGRESS,
THEME và PING giữ nguyên bài. Ngắt BLE dừng nhạc kể cả khi trợ lý đang ngủ.
`STATUS` thêm `audio`, `music`, `note_hz`; `note_hz` là nốt yêu cầu từ player,
không phải tần số âm thực của TMB12A05 ở chế độ active.

## Kiểm tra

Từ thư mục gốc repository, có g++ trong PATH:

```powershell
powershell -ExecutionPolicy Bypass -File pbl4/tools/test_host.ps1
pio run -d pbl4
```

Host test kiểm tra nốt/tempo/nốt nghỉ/gate/mute/đổi bài, tràn `millis()`, lệnh,
và đầu ra GPIO/LEDC bằng API giả cho core 2.x/3.x. Build firmware kiểm tra với
SDK thật đang dùng. Các kiểm tra này chưa xác nhận âm thanh trên mạch thực tế.
Kết quả build và checksum firmware hiện tại nằm trong [báo cáo kiểm chứng](../../docs/music-validation.json).
