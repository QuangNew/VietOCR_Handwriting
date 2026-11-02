// Test the production ownership wrapper at the ESP-IDF API boundary.
// The fake models allocator reservations and the refcounted GDMA clock, not
// electrical signals; successful host tests do not prove camera image capture.
#include <cassert>
#include <cstdio>
#include "../lib/NativeCameraHal/src/native_dma.h"

struct FakeDma { bool allocated = false, connected = false; int id = 0; };
static FakeDma pool[5];
static int references = 0, clockResets = 0, injectFailure = 0, checks = 0;
static bool clockOn = false, unmanagedCameraRunning = false;
#define CHECK(expression) do { ++checks; assert(expression); } while (0)

esp_err_t gdma_new_channel(const gdma_channel_alloc_config_t* config, gdma_channel_handle_t* result) {
    assert(config->direction == GDMA_CHANNEL_DIRECTION_RX);
    assert(!config->sibling_chan && !config->flags.reserve_sibling);
    if (injectFailure == 1) return ESP_FAIL;
    for (int i = 0; i < 5; ++i) if (!pool[i].allocated) {
        if (references++ == 0) {
            clockOn = true;
        }
        pool[i].allocated = true; pool[i].id = i;
        *result = &pool[i]; return ESP_OK;
    }
    return ESP_ERR_NOT_FOUND;
}
esp_err_t gdma_get_channel_id(gdma_channel_handle_t channel, int* id) {
    assert(channel && channel->allocated);
    if (injectFailure == 2) return ESP_FAIL;
    *id = channel->id; return ESP_OK;
}
esp_err_t gdma_connect(gdma_channel_handle_t channel, gdma_trigger_t trigger) {
    assert(channel && channel->allocated && !channel->connected);
    assert(trigger.periph == GDMA_TRIG_PERIPH_CAM && trigger.instance_id == 0);
    if (injectFailure == 3) return ESP_FAIL;
    channel->connected = true; return ESP_OK;
}
esp_err_t gdma_disconnect(gdma_channel_handle_t channel) {
    assert(channel && channel->allocated && channel->connected);
    if (injectFailure == 4) return ESP_FAIL;
    channel->connected = false; return ESP_OK;
}
esp_err_t gdma_del_channel(gdma_channel_handle_t channel) {
    assert(channel && channel->allocated && !channel->connected);
    if (injectFailure == 5) return ESP_FAIL;
    channel->allocated = false;
    if (--references == 0) {
        // IDF 4.4 gdma_release_group_handle -> periph_module_disable:
        // last registered client disables the clock and asserts reset.
        clockOn = false; ++clockResets; unmanagedCameraRunning = false;
    }
    return ESP_OK;
}

static gdma_channel_handle_t otherClient() {
    gdma_channel_alloc_config_t config{};
    config.direction = GDMA_CHANNEL_DIRECTION_RX;
    gdma_channel_handle_t handle = nullptr;
    assert(gdma_new_channel(&config, &handle) == ESP_OK);
    return handle;
}

int main() {
    // Reproduce the old ownership defect: releasing the last registered
    // client disables a manually programmed camera that IDF cannot see.
    unmanagedCameraRunning = true; clockOn = true;
    auto crypto = otherClient();
    CHECK(unmanagedCameraRunning && clockOn);
    CHECK(gdma_del_channel(crypto) == ESP_OK && !clockOn);
    CHECK(!unmanagedCameraRunning);

    native_dma_channel_t camera{};
    CHECK(native_dma_acquire(&camera) == ESP_OK);
    CHECK(camera.handle && camera.connected && references == 1 && clockOn);
    const int resets = clockResets;
    crypto = otherClient();
    CHECK(crypto != camera.handle && clockResets == resets);
    CHECK(gdma_del_channel(crypto) == ESP_OK && clockOn && camera.connected);
    CHECK(native_dma_acquire(&camera) == ESP_ERR_INVALID_STATE && references == 1);
    CHECK(native_dma_release(&camera) == ESP_OK && !clockOn && references == 0);
    CHECK(native_dma_release(&camera) == ESP_OK && !camera.handle && camera.id == -1);

    // Camera init with existing Wi-Fi/crypto clients must not select their RX.
    crypto = otherClient();
    CHECK(native_dma_acquire(&camera) == ESP_OK && camera.id != crypto->id);
    CHECK(native_dma_release(&camera) == ESP_OK && clockOn && crypto->allocated);
    CHECK(gdma_del_channel(crypto) == ESP_OK);

    for (int error = 1; error <= 3; ++error) {
        injectFailure = error;
        CHECK(native_dma_acquire(&camera) == ESP_FAIL);
        CHECK(!camera.handle && references == 0 && !clockOn);
    }
    injectFailure = 0;
    CHECK(native_dma_acquire(&camera) == ESP_OK);
    injectFailure = 4;
    CHECK(native_dma_release(&camera) == ESP_FAIL && camera.handle && camera.connected);
    injectFailure = 5;
    CHECK(native_dma_release(&camera) == ESP_FAIL && camera.handle && !camera.connected);
    injectFailure = 0;
    CHECK(native_dma_release(&camera) == ESP_OK && references == 0);

    gdma_channel_handle_t busy[5];
    for (auto& handle : busy) handle = otherClient();
    CHECK(native_dma_acquire(&camera) == ESP_ERR_NOT_FOUND && !camera.handle && references == 5);
    for (auto handle : busy) CHECK(gdma_del_channel(handle) == ESP_OK);
    for (int i = 0; i < 100; ++i) {
        CHECK(native_dma_acquire(&camera) == ESP_OK && references == 1);
        CHECK(native_dma_release(&camera) == ESP_OK && references == 0);
    }
    std::printf("native_dma: %d checks passed (ownership, shared clock, failure cleanup, reopen)\n", checks);
}
