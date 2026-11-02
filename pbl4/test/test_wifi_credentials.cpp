#include "wifi_credentials.h"
#include <stdio.h>
#include <stdlib.h>
#include <string>

unsigned checks = 0;
void check(bool value) { ++checks; if (!value) { fprintf(stderr, "FAIL cache check %u\n", checks); abort(); } }

struct FakeNvs {
  uint8_t bytes[wifi_credentials::kBytes]{};
  size_t size = 0;
  unsigned writes = 0;
  bool failWrite = false, failRead = false;
  unsigned missingBlobReads = 0;
  std::string ssid, password;
  bool isKey(const char* key) { return !strcmp(key, "profile") ? size > 0 : !strcmp(key, "ssid") ? !ssid.empty() : !password.empty(); }
  size_t getBytesLength(const char*) { if (!size) ++missingBlobReads; return size; }
  size_t getBytes(const char*, void* out, size_t capacity) {
    if (failRead || capacity < size) return 0;
    memcpy(out, bytes, size); return size;
  }
  size_t putBytes(const char*, const void* value, size_t count) {
    ++writes;
    if (failWrite || count != sizeof(bytes)) return 0;
    memcpy(bytes, value, count); size = count; return count;
  }
  std::string getString(const char* key, const char* fallback = "") {
    const auto value = !strcmp(key, "ssid") ? ssid : password;
    return value.empty() ? std::string(fallback) : value;
  }
};

int main() {
  using namespace wifi_credentials;
  Profile profile{}, restored{};
  strcpy(profile.ssid, "Wi-Fi Viet"); strcpy(profile.password, "password-123");
  uint8_t flash[kBytes];
  check(encode(profile, flash));
  check(decode(flash, sizeof(flash), restored));
  check(equal(profile, restored));
  // A new RAM object simulates reloading the complete persistent record.
  Profile afterRestart{};
  check(decode(flash, sizeof(flash), afterRestart));
  check(equal(profile, afterRestart));
  for (size_t size = 0; size < sizeof(flash); ++size) check(!decode(flash, size, restored));
  for (size_t at = 0; at < sizeof(flash); ++at) {
    flash[at] ^= 1; check(!decode(flash, sizeof(flash), restored)); flash[at] ^= 1;
  }
  check(valid("Open Network", ""));
  check(valid("UTF8-\xe1\xbb\x87", "12345678"));
  check(!valid("", "12345678"));
  check(!valid("Name", "short"));
  memset(profile.ssid, 'x', 32); profile.ssid[32] = 0;
  memset(profile.password, 'p', 63); profile.password[63] = 0;
  check(encode(profile, flash)); check(decode(flash, sizeof(flash), restored)); check(equal(profile, restored));
  profile.password[0] = 0;
  check(encode(profile, flash)); check(decode(flash, sizeof(flash), restored)); check(equal(profile, restored));
  memset(profile.ssid, 'x', sizeof(profile.ssid)); check(!encode(profile, flash));
  strcpy(profile.ssid, "Name"); memset(profile.password, 'p', sizeof(profile.password)); check(!encode(profile, flash));
  check(!valid(nullptr, "12345678")); check(!valid("Name", nullptr));
  FakeNvs nvs;
  bool modern = false;
  check(!load(nvs, restored, modern));
  check(nvs.missingBlobReads == 0);
  nvs.ssid = "Legacy WiFi"; nvs.password = "password123";
  check(load(nvs, restored, modern)); check(!modern && nvs.writes == 0);
  check(!strcmp(restored.ssid, "Legacy WiFi"));
  check(save(nvs, restored)); check(nvs.writes == 1);
  Profile rebooted{};
  check(load(nvs, rebooted, modern)); check(modern && equal(rebooted, restored));
  check(nvs.writes == 1); // Reading at startup never writes flash.
  nvs.bytes[40] ^= 1;
  check(load(nvs, rebooted, modern)); check(!modern); // Legacy fallback.
  check(save(nvs, rebooted)); check(nvs.writes == 2);
  nvs.failWrite = true;
  strcpy(profile.ssid, "Replacement"); strcpy(profile.password, "newPassword");
  check(!save(nvs, profile));
  check(load(nvs, rebooted, modern)); check(!strcmp(rebooted.ssid, "Legacy WiFi"));
  nvs.failWrite = false; nvs.failRead = true;
  check(!save(nvs, profile)); // Must not report success without readback.
  nvs.failRead = false;
  check(load(nvs, rebooted, modern)); check(!strcmp(rebooted.ssid, "Replacement"));
  printf("PASS WiFi credentials: %u checks (persisted record, UTF8, bounds, truncation, corruption)\n", checks);
}
