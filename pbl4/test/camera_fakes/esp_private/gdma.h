#pragma once
#include <stddef.h>
typedef int esp_err_t;
enum { ESP_OK = 0, ESP_FAIL = -1, ESP_ERR_INVALID_STATE = 2, ESP_ERR_NOT_FOUND = 3 };
enum { GDMA_CHANNEL_DIRECTION_RX, GDMA_CHANNEL_DIRECTION_TX, GDMA_TRIG_PERIPH_CAM = 5 };
struct FakeDma;
typedef FakeDma* gdma_channel_handle_t;
struct gdma_channel_alloc_config_t {
    gdma_channel_handle_t sibling_chan;
    int direction;
    struct { int reserve_sibling; } flags;
};
struct gdma_trigger_t { int periph; int instance_id; };
#define GDMA_MAKE_TRIGGER(peripheral, instance) gdma_trigger_t{peripheral, instance}
esp_err_t gdma_new_channel(const gdma_channel_alloc_config_t*, gdma_channel_handle_t*);
esp_err_t gdma_get_channel_id(gdma_channel_handle_t, int*);
esp_err_t gdma_connect(gdma_channel_handle_t, gdma_trigger_t);
esp_err_t gdma_disconnect(gdma_channel_handle_t);
esp_err_t gdma_del_channel(gdma_channel_handle_t);
