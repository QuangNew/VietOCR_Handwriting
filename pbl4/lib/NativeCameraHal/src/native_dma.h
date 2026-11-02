// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include "esp_private/gdma.h"

// Own the RX channel through ESP-IDF, including its clock reference. Looking
// for an empty GDMA link register does not reserve that channel or its clock.
typedef struct {
    gdma_channel_handle_t handle;
    int id;
    bool connected;
} native_dma_channel_t;

static inline esp_err_t native_dma_release(native_dma_channel_t *channel)
{
    if (!channel->handle) return ESP_OK;
    if (channel->connected) {
        esp_err_t error = gdma_disconnect(channel->handle);
        if (error != ESP_OK) return error;
        channel->connected = false;
    }
    esp_err_t error = gdma_del_channel(channel->handle);
    if (error == ESP_OK) {
        channel->handle = NULL;
        channel->id = -1;
    }
    return error;
}

static inline esp_err_t native_dma_acquire(native_dma_channel_t *channel)
{
    if (channel->handle) return ESP_ERR_INVALID_STATE;
    channel->id = -1;
    channel->connected = false;
    gdma_channel_alloc_config_t config;
    memset(&config, 0, sizeof(config));
    config.direction = GDMA_CHANNEL_DIRECTION_RX;
    esp_err_t error = gdma_new_channel(&config, &channel->handle);
    if (error != ESP_OK) return error;
    error = gdma_get_channel_id(channel->handle, &channel->id);
    if (error == ESP_OK) {
        error = gdma_connect(channel->handle, GDMA_MAKE_TRIGGER(GDMA_TRIG_PERIPH_CAM, 0));
        channel->connected = error == ESP_OK;
    }
    if (error != ESP_OK) native_dma_release(channel);
    return error;
}
