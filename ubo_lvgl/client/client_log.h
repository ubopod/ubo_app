/* Minimal logging seam shared by the platform-neutral client sources.
 * ESP-IDF builds route to esp_log; desktop/Pi builds to stderr. Warnings only —
 * this exists so protocol failures (above all pb_decode failures, the signature
 * of curated-proto tag drift) are never silent. */
#ifndef UBO_CLIENT_LOG_H
#define UBO_CLIENT_LOG_H

#ifdef ESP_PLATFORM
#include "esp_log.h"
#define UBO_CLIENT_LOGW(fmt, ...) ESP_LOGW("ubo_client", fmt, ##__VA_ARGS__)
#else
#include <stdio.h>
#define UBO_CLIENT_LOGW(fmt, ...) \
    fprintf(stderr, "[ubo_client] " fmt "\n", ##__VA_ARGS__)
#endif

#endif /* UBO_CLIENT_LOG_H */
