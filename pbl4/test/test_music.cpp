#include <VietMusic.h>
#include <VietMusicSongs.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

using namespace vietmusic;
int checks = 0;
#define CHECK(expression) do { ++checks; if (!(expression)) { \
  fprintf(stderr, "FAIL music line %d: %s\n", __LINE__, #expression); exit(1); } } while (false)

void testNotesAndTempo() {
  CHECK(notes::REST == 0 && notes::A4 == 440 && notes::A5 == 880);
  CHECK(notes::C4 == 262 && notes::E4 == 330 && notes::G4 == 392);
  CHECK(notes::frequency(notes::Key::Db, 4) == notes::Cs4);
  CHECK(notes::frequency(notes::Key::Bb, 4) == notes::As4);
  CHECK(notes::frequency(notes::Key::C, 9) == 0);
  CHECK(notes::frequency(static_cast<notes::Key>(255), 4) == 0);
  uint16_t previous = 0;
  for (uint8_t octave = 0; octave < 9; ++octave) {
    for (uint8_t key = 0; key < 12; ++key) {
      const uint16_t hz = notes::kChromaticHz[octave][key];
      CHECK(hz > previous);
      previous = hz;
      if (octave) {
        const int difference = hz - 2 * notes::kChromaticHz[octave - 1][key];
        CHECK(difference >= -1 && difference <= 1);
      }
    }
  }
  CHECK(Player::noteMilliseconds({notes::A4, duration::Quarter}, 120) == 500);
  CHECK(Player::noteMilliseconds({notes::A4, duration::Eighth}, 120) == 250);
  CHECK(Player::noteMilliseconds({notes::A4, duration::DottedQuarter}, 120) == 750);
  CHECK(Player::noteMilliseconds({notes::A4, duration::EighthTriplet}, 120) == 167);
  CHECK(Player::noteMilliseconds({notes::A4, duration::Quarter}, 240) == 250);
  CHECK(Player::noteMilliseconds({notes::A4, duration::Quarter}, 0) == 0);
  CHECK(Player::noteMilliseconds({notes::A4, 0}, 120) == 0);
}

void testTimingRestAndGate() {
  static const Note score[] = {{notes::C4, duration::Quarter},
      {notes::REST, duration::Eighth}, {notes::E4, duration::Quarter}};
  Player player;
  CHECK(!player.playing() && player.frequency() == 0);
  CHECK(player.play(melody(score, 120, 80), 100));
  CHECK(player.frequency() == notes::C4 && player.noteIndex() == 0);
  player.update(499); CHECK(player.frequency() == notes::C4);
  player.update(500); CHECK(player.frequency() == 0 && player.playing());
  player.update(600); CHECK(player.frequency() == 0 && player.noteIndex() == 1);
  player.update(849); CHECK(player.noteIndex() == 1);
  player.update(850); CHECK(player.frequency() == notes::E4 && player.noteIndex() == 2);
  player.update(1250); CHECK(player.frequency() == 0 && player.playing());
  player.update(1349); CHECK(player.playing());
  player.update(1350); CHECK(!player.playing() && player.frequency() == 0);
  player.update(800000); CHECK(!player.playing());
  CHECK(player.play(melody(score, 120), 10));
  player.update(1010);  // Skip to the current note, never replay missed notes.
  CHECK(player.noteIndex() == 2 && player.frequency() == notes::E4);
  player.update(1000000); CHECK(!player.playing() && player.frequency() == 0);
  const uint32_t nearWrap = UINT32_MAX - 100;
  CHECK(player.play(melody(score, 120, 100), nearWrap));
  player.update(nearWrap + 499u); CHECK(player.frequency() == notes::C4);
  player.update(nearWrap + 500u); CHECK(player.noteIndex() == 1 && player.frequency() == 0);
  player.update(nearWrap + 750u); CHECK(player.frequency() == notes::E4);
  player.update(nearWrap + 1250u); CHECK(!player.playing() && player.frequency() == 0);
  static const Note veryShort[] = {{notes::A4, 1}};
  CHECK(player.play(melody(veryShort, 400, 1), 0));
  CHECK(player.frequency() == notes::A4);
  player.update(1); CHECK(player.frequency() == 0 && player.playing());
  player.update(6); CHECK(!player.playing());
}

void testMuteReplacementAndInvalidScores() {
  Player player;
  CHECK(player.play(song(Song::Scale), 0));
  player.setMuted(true); CHECK(!player.playing() && player.frequency() == 0);
  CHECK(!player.play(song(Song::Test), 5));
  player.setMuted(false); CHECK(!player.playing());
  CHECK(player.play(song(Song::Scale), 10));
  CHECK(player.play(song(Song::Done), 20));
  CHECK(player.frequency() == notes::C5 && player.noteIndex() == 0);
  player.stop(); CHECK(!player.playing() && player.frequency() == 0);
  static const Note startWithRest[] = {{0, duration::Eighth}, {notes::A4, duration::Quarter}};
  CHECK(player.play(melody(startWithRest, 120), 50));
  CHECK(player.frequency() == 0 && player.playing());
  const Note badNotes[] = {{notes::A4, 0}, {notes::A4, 385}, {1, 24}, {65535, 24}};
  for (const auto& note : badNotes) CHECK(!Player::valid({&note, 1, 120, 85}));
  static const Note valid[] = {{notes::A4, duration::Quarter}};
  const Melody invalid[] = {{nullptr, 1, 120, 85}, {valid, 0, 120, 85}, {valid, 513, 120, 85},
      {valid, 1, 19, 85}, {valid, 1, 401, 85}, {valid, 1, 120, 0}, {valid, 1, 120, 101}};
  for (const auto& score : invalid) {
    CHECK(!player.play(score, 90));
    CHECK(!player.playing() && player.frequency() == 0);
  }
}

void testCatalog() {
  Player player;
  for (uint8_t index = 0; index < kSongCount; ++index) {
    const auto id = static_cast<Song>(index);
    Song found;
    CHECK(findSong(songName(id), found) && found == id);
    const auto score = song(id);
    CHECK(Player::valid(score));
    CHECK(player.play(score, 0));
    uint32_t length = 0;
    for (uint16_t i = 0; i < score.count; ++i) length += Player::noteMilliseconds(score.notes[i], score.bpm);
    player.update(length - 1); CHECK(player.playing());
    player.update(length); CHECK(!player.playing() && player.frequency() == 0);
  }
  Song found;
  CHECK(findSong("tWiNkLe", found) && found == Song::Twinkle);
  CHECK(!findSong(nullptr, found) && !findSong("", found) && !findSong("UNKNOWN", found));
  CHECK(!Player::valid(song(static_cast<Song>(255))));
  CHECK(strcmp(songName(static_cast<Song>(255)), "UNKNOWN") == 0);
}

int main() {
  testNotesAndTempo(); testTimingRestAndGate(); testMuteReplacementAndInvalidScores(); testCatalog();
  printf("PASS: %d music checks (notes, tempo, rests, gate, mute, interruption, rollover, catalog)\n", checks);
  return 0;
}
