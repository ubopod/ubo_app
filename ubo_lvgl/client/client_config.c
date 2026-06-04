#include "client_config.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define DEFAULT_ENVOY_PORT 50052

static void copy_str(char *dst, size_t cap, const char *src) {
    snprintf(dst, cap, "%s", src);
}

bool ubo_client_config_parse(int argc, char **argv, ubo_client_config *out) {
    memset(out, 0, sizeof(*out));
    copy_str(out->backend, sizeof(out->backend), "sdl");
    copy_str(out->host, sizeof(out->host), "localhost");
    out->web_grpc_url[0] = '\0';

    const char *env_url = getenv("UBO_LVGL_GUI_WEB_GRPC_URL");
    if (env_url && env_url[0]) {
        copy_str(out->web_grpc_url, sizeof(out->web_grpc_url), env_url);
    }

    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (strcmp(a, "--backend") == 0 && i + 1 < argc) {
            copy_str(out->backend, sizeof(out->backend), argv[++i]);
        } else if (strcmp(a, "--host") == 0 && i + 1 < argc) {
            copy_str(out->host, sizeof(out->host), argv[++i]);
        } else if (strcmp(a, "--web-grpc-url") == 0 && i + 1 < argc) {
            copy_str(out->web_grpc_url, sizeof(out->web_grpc_url), argv[++i]);
        } else if (strcmp(a, "-v") == 0 || strcmp(a, "--verbose") == 0) {
            out->verbose = true;
        } else if (strcmp(a, "-h") == 0 || strcmp(a, "--help") == 0) {
            fprintf(stderr,
                    "usage: %s [--backend sdl|st7789|buffer] [--host HOST]\n"
                    "          [--web-grpc-url URL] [-v]\n",
                    argv[0]);
            return false;
        } else {
            fprintf(stderr, "unknown argument: %s\n", a);
            return false;
        }
    }

    if (strcmp(out->backend, "sdl") != 0 && strcmp(out->backend, "st7789") != 0 &&
        strcmp(out->backend, "buffer") != 0) {
        fprintf(stderr, "invalid --backend '%s'\n", out->backend);
        return false;
    }

    if (out->web_grpc_url[0] == '\0') {
        snprintf(out->web_grpc_url, sizeof(out->web_grpc_url),
                 "http://%s:%d/grpc", out->host, DEFAULT_ENVOY_PORT);
    }
    return true;
}
