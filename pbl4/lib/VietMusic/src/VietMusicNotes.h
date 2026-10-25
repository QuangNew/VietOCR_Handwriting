#pragma once

#include <stdint.h>

namespace vietmusic {
namespace notes {
// Equal temperament, A4 = 440 Hz, rounded to whole Hz for ESP32 LEDC.
// C0..B8; REST means silence. C/Do, D/Re, E/Mi, F/Fa, G/Sol, A/La, B/Si.
constexpr uint16_t REST = 0;
constexpr uint16_t kChromaticHz[9][12] = {
    {16, 17, 18, 19, 21, 22, 23, 24, 26, 28, 29, 31},  // Octave 0
    {33, 35, 37, 39, 41, 44, 46, 49, 52, 55, 58, 62},  // Octave 1
    {65, 69, 73, 78, 82, 87, 92, 98, 104, 110, 117, 123},  // Octave 2
    {131, 139, 147, 156, 165, 175, 185, 196, 208, 220, 233, 247},  // Octave 3
    {262, 277, 294, 311, 330, 349, 370, 392, 415, 440, 466, 494},  // Octave 4
    {523, 554, 587, 622, 659, 698, 740, 784, 831, 880, 932, 988},  // Octave 5
    {1047, 1109, 1175, 1245, 1319, 1397, 1480, 1568, 1661, 1760, 1865, 1976},  // Octave 6
    {2093, 2217, 2349, 2489, 2637, 2794, 2960, 3136, 3322, 3520, 3729, 3951},  // Octave 7
    {4186, 4435, 4699, 4978, 5274, 5588, 5920, 6272, 6645, 7040, 7459, 7902},  // Octave 8
};
enum class Key : uint8_t { C, Cs, D, Ds, E, F, Fs, G, Gs, A, As, B,
                           Db = Cs, Eb = Ds, Gb = Fs, Ab = Gs, Bb = As };
constexpr uint16_t frequency(Key key, uint8_t octave) {
  return octave < 9 && static_cast<uint8_t>(key) < 12
      ? kChromaticHz[octave][static_cast<uint8_t>(key)] : REST;
}

constexpr uint16_t C0 = kChromaticHz[0][0];
constexpr uint16_t Cs0 = kChromaticHz[0][1];
constexpr uint16_t D0 = kChromaticHz[0][2];
constexpr uint16_t Ds0 = kChromaticHz[0][3];
constexpr uint16_t E0 = kChromaticHz[0][4];
constexpr uint16_t F0 = kChromaticHz[0][5];
constexpr uint16_t Fs0 = kChromaticHz[0][6];
constexpr uint16_t G0 = kChromaticHz[0][7];
constexpr uint16_t Gs0 = kChromaticHz[0][8];
constexpr uint16_t A0 = kChromaticHz[0][9];
constexpr uint16_t As0 = kChromaticHz[0][10];
// Arduino reserves B0 and B1 as binary-literal macros.
constexpr uint16_t B_0 = kChromaticHz[0][11];
constexpr uint16_t C1 = kChromaticHz[1][0];
constexpr uint16_t Cs1 = kChromaticHz[1][1];
constexpr uint16_t D1 = kChromaticHz[1][2];
constexpr uint16_t Ds1 = kChromaticHz[1][3];
constexpr uint16_t E1 = kChromaticHz[1][4];
constexpr uint16_t F1 = kChromaticHz[1][5];
constexpr uint16_t Fs1 = kChromaticHz[1][6];
constexpr uint16_t G1 = kChromaticHz[1][7];
constexpr uint16_t Gs1 = kChromaticHz[1][8];
constexpr uint16_t A1 = kChromaticHz[1][9];
constexpr uint16_t As1 = kChromaticHz[1][10];
constexpr uint16_t B_1 = kChromaticHz[1][11];
constexpr uint16_t C2 = kChromaticHz[2][0];
constexpr uint16_t Cs2 = kChromaticHz[2][1];
constexpr uint16_t D2 = kChromaticHz[2][2];
constexpr uint16_t Ds2 = kChromaticHz[2][3];
constexpr uint16_t E2 = kChromaticHz[2][4];
constexpr uint16_t F2 = kChromaticHz[2][5];
constexpr uint16_t Fs2 = kChromaticHz[2][6];
constexpr uint16_t G2 = kChromaticHz[2][7];
constexpr uint16_t Gs2 = kChromaticHz[2][8];
constexpr uint16_t A2 = kChromaticHz[2][9];
constexpr uint16_t As2 = kChromaticHz[2][10];
constexpr uint16_t B2 = kChromaticHz[2][11];
constexpr uint16_t C3 = kChromaticHz[3][0];
constexpr uint16_t Cs3 = kChromaticHz[3][1];
constexpr uint16_t D3 = kChromaticHz[3][2];
constexpr uint16_t Ds3 = kChromaticHz[3][3];
constexpr uint16_t E3 = kChromaticHz[3][4];
constexpr uint16_t F3 = kChromaticHz[3][5];
constexpr uint16_t Fs3 = kChromaticHz[3][6];
constexpr uint16_t G3 = kChromaticHz[3][7];
constexpr uint16_t Gs3 = kChromaticHz[3][8];
constexpr uint16_t A3 = kChromaticHz[3][9];
constexpr uint16_t As3 = kChromaticHz[3][10];
constexpr uint16_t B3 = kChromaticHz[3][11];
constexpr uint16_t C4 = kChromaticHz[4][0];
constexpr uint16_t Cs4 = kChromaticHz[4][1];
constexpr uint16_t D4 = kChromaticHz[4][2];
constexpr uint16_t Ds4 = kChromaticHz[4][3];
constexpr uint16_t E4 = kChromaticHz[4][4];
constexpr uint16_t F4 = kChromaticHz[4][5];
constexpr uint16_t Fs4 = kChromaticHz[4][6];
constexpr uint16_t G4 = kChromaticHz[4][7];
constexpr uint16_t Gs4 = kChromaticHz[4][8];
constexpr uint16_t A4 = kChromaticHz[4][9];
constexpr uint16_t As4 = kChromaticHz[4][10];
constexpr uint16_t B4 = kChromaticHz[4][11];
constexpr uint16_t C5 = kChromaticHz[5][0];
constexpr uint16_t Cs5 = kChromaticHz[5][1];
constexpr uint16_t D5 = kChromaticHz[5][2];
constexpr uint16_t Ds5 = kChromaticHz[5][3];
constexpr uint16_t E5 = kChromaticHz[5][4];
constexpr uint16_t F5 = kChromaticHz[5][5];
constexpr uint16_t Fs5 = kChromaticHz[5][6];
constexpr uint16_t G5 = kChromaticHz[5][7];
constexpr uint16_t Gs5 = kChromaticHz[5][8];
constexpr uint16_t A5 = kChromaticHz[5][9];
constexpr uint16_t As5 = kChromaticHz[5][10];
constexpr uint16_t B5 = kChromaticHz[5][11];
constexpr uint16_t C6 = kChromaticHz[6][0];
constexpr uint16_t Cs6 = kChromaticHz[6][1];
constexpr uint16_t D6 = kChromaticHz[6][2];
constexpr uint16_t Ds6 = kChromaticHz[6][3];
constexpr uint16_t E6 = kChromaticHz[6][4];
constexpr uint16_t F6 = kChromaticHz[6][5];
constexpr uint16_t Fs6 = kChromaticHz[6][6];
constexpr uint16_t G6 = kChromaticHz[6][7];
constexpr uint16_t Gs6 = kChromaticHz[6][8];
constexpr uint16_t A6 = kChromaticHz[6][9];
constexpr uint16_t As6 = kChromaticHz[6][10];
constexpr uint16_t B6 = kChromaticHz[6][11];
constexpr uint16_t C7 = kChromaticHz[7][0];
constexpr uint16_t Cs7 = kChromaticHz[7][1];
constexpr uint16_t D7 = kChromaticHz[7][2];
constexpr uint16_t Ds7 = kChromaticHz[7][3];
constexpr uint16_t E7 = kChromaticHz[7][4];
constexpr uint16_t F7 = kChromaticHz[7][5];
constexpr uint16_t Fs7 = kChromaticHz[7][6];
constexpr uint16_t G7 = kChromaticHz[7][7];
constexpr uint16_t Gs7 = kChromaticHz[7][8];
constexpr uint16_t A7 = kChromaticHz[7][9];
constexpr uint16_t As7 = kChromaticHz[7][10];
constexpr uint16_t B7 = kChromaticHz[7][11];
constexpr uint16_t C8 = kChromaticHz[8][0];
constexpr uint16_t Cs8 = kChromaticHz[8][1];
constexpr uint16_t D8 = kChromaticHz[8][2];
constexpr uint16_t Ds8 = kChromaticHz[8][3];
constexpr uint16_t E8 = kChromaticHz[8][4];
constexpr uint16_t F8 = kChromaticHz[8][5];
constexpr uint16_t Fs8 = kChromaticHz[8][6];
constexpr uint16_t G8 = kChromaticHz[8][7];
constexpr uint16_t Gs8 = kChromaticHz[8][8];
constexpr uint16_t A8 = kChromaticHz[8][9];
constexpr uint16_t As8 = kChromaticHz[8][10];
constexpr uint16_t B8 = kChromaticHz[8][11];
}  // namespace notes
}  // namespace vietmusic

