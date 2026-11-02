#include "wifi_recovery.h"
#include <assert.h>
#include <stdio.h>

int main() {
  WifiScanRecovery scan;
  assert(!scan.active());
  scan.request(1000);
  assert(scan.active());
  assert(!scan.due(1249));
  assert(scan.due(1250));
  scan.started(1250, -2); // Exact failed-start result from the user's firmware.
  assert(scan.active() && scan.attempts == 1);
  assert(!scan.due(1749));
  scan.request(1600); // Repeated SCAN must not reset the retry clock/budget.
  assert(scan.attempts == 1);
  assert(scan.due(1750));
  scan.started(1750, -2);
  assert(scan.active() && scan.attempts == 2);
  assert(scan.due(2250));
  scan.started(2250, -2);
  assert(!scan.active() && scan.state == WifiScanRecovery::State::Failed);
  assert(!scan.due(99999));
  scan.request(100000);
  assert(scan.attempts == 0 && scan.active());
  scan.started(100250, -1);
  assert(scan.active() && !scan.due(200000));
  scan.poll(100300, -1);
  assert(scan.active());
  scan.poll(104000, 7);
  assert(!scan.active() && scan.state == WifiScanRecovery::State::Done);
  scan.request(200000);
  scan.started(200250, -1);
  scan.poll(215249, -1);
  assert(scan.active());
  scan.poll(215250, -1);
  assert(scan.state == WifiScanRecovery::State::Failed);
  scan.reset();
  assert(scan.state == WifiScanRecovery::State::Idle);
  scan.request(UINT32_MAX - 100);
  assert(!scan.due(148));
  assert(scan.due(149));
  scan.started(149, 0); // A genuinely empty completed scan is success.
  assert(scan.state == WifiScanRecovery::State::Done);
  scan.request(400);
  scan.started(650, -1);
  scan.poll(700, -2);
  assert(scan.state == WifiScanRecovery::State::Failed);
  puts("PASS WiFi recovery: 23 checks (busy driver retries, retry exhaustion, timeout, zero networks, rollover)");
  WifiReconnect reconnect;
  reconnect.reset(1000);
  assert(reconnect.due(1000));
  reconnect.failed(1000);
  assert(reconnect.delayMs() == 3000 && !reconnect.due(3999) && reconnect.due(4000));
  reconnect.failed(5000); assert(reconnect.delayMs() == 6000);
  reconnect.failed(12000); assert(reconnect.delayMs() == 12000);
  reconnect.failed(25000); assert(reconnect.delayMs() == 24000);
  reconnect.failed(50000); assert(reconnect.delayMs() == 60000);
  reconnect.failed(111000); assert(reconnect.delayMs() == 60000);
  reconnect.pause(120000, 30000);
  assert(!reconnect.due(149999) && reconnect.due(150000));
  reconnect.reset(150001); assert(reconnect.due(150001));
  reconnect.failed(UINT32_MAX - 1000);
  assert(!reconnect.due(1998) && reconnect.due(1999));
  puts("PASS WiFi reconnect: 10 checks (backoff, scan pause, connected reset, rollover)");
  reconnect.pause(10000, 60000);
  assert(!reconnect.due(10001));
  assert(reconnect.bluetoothConnected(10001, true, false, false));
  assert(reconnect.due(10001));
  reconnect.pause(11000, 60000);
  assert(!reconnect.bluetoothConnected(11001, true, true, false));
  assert(!reconnect.due(11001));
  assert(!reconnect.bluetoothConnected(11001, false, false, false));
  assert(!reconnect.due(11001));
  assert(!reconnect.bluetoothConnected(11001, true, false, true));
  assert(reconnect.due(11001));
  assert(reconnect.bluetoothConnected(11002, true, false, false));
  puts("PASS BLE WiFi wake: 10 checks (immediate retry, no profile, existing LAN, active join)");
}
