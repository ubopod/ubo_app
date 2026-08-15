/* Command-line / environment configuration for the native C LVGL client. */
#ifndef UBO_CLIENT_CONFIG_H
#define UBO_CLIENT_CONFIG_H

#include <stdbool.h>

#define UBO_CLIENT_URL_MAX 256

typedef struct {
    char backend[16];                    /* "sdl" | "st7789" | "buffer" */
    char host[128];                      /* host used to derive the default url */
    char web_grpc_url[UBO_CLIENT_URL_MAX]; /* Envoy "/grpc" base url */
    bool verbose;
} ubo_client_config;

/* Parse argv (and the UBO_LVGL_GUI_WEB_GRPC_URL env var) into `out`.
 * Returns false on a usage error (message already printed to stderr).
 *
 * Flags: --backend {sdl,st7789,buffer}  --host HOST  --web-grpc-url URL  -v
 * If --web-grpc-url is unset, defaults to http://<host>:50052/grpc.
 */
bool ubo_client_config_parse(int argc, char **argv, ubo_client_config *out);

#endif /* UBO_CLIENT_CONFIG_H */
