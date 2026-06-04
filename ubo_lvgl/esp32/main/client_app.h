/**
 * @file client_app.h
 * Device-side orchestration of the web-grpc client (FreeRTOS-task equivalent of
 * the desktop client_main.c): store-stream -> translate -> render, event-stream
 * (scroll / menu-choose; frame_stream/viewfinder deferred), and a dispatch
 * worker fed by enqueued key names.
 */
#ifndef UBO_CLIENT_APP_H
#define UBO_CLIENT_APP_H

#ifdef __cplusplus
extern "C" {
#endif

/* Create the RPC client for `web_grpc_url` and spawn the store / event /
 * dispatch tasks. Call once, after WiFi is up. */
void ubo_client_start(const char *web_grpc_url);

/* Queue a renderer key name ("UP"/"DOWN"/"L1".."L3"/"BACK"/"HOME"/"M") for the
 * dispatch worker to POST as an Action. Non-blocking; safe from any task / the
 * input callback. */
void ubo_client_enqueue_key(const char *key);

#ifdef __cplusplus
}
#endif
#endif /* UBO_CLIENT_APP_H */
