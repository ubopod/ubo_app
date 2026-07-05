/**
 * @file ubo_lvgl.h
 *
 * Public C API for the Ubo LVGL GUI renderer (libubo_lvgl).
 *
 * This header is the STABLE SEAM between the data source and the renderer.
 *
 *   Phase 1: a Python bridge decodes gRPC `ViewData`/`StatusBarData` and calls
 *            these functions via CFFI.
 *   Phase 2: a C gRPC/proto decoder on a microcontroller calls the SAME
 *            functions. All rendering code below this seam is reused verbatim.
 *
 * The view-model structs mirror the core's `ViewData` / `StatusBarData` proto
 * messages field-for-field so the phase-2 decoder maps onto them directly.
 *
 * Threading: the renderer runs LVGL on its own loop (see ubo_lvgl_run). All
 * `ubo_lvgl_*` entry points are safe to call from another thread; they take an
 * internal lock and build the LVGL widget tree synchronously. Strings passed in
 * are only read during the call (LVGL copies what it needs), so the caller may
 * free/reuse them after the call returns.
 */

#ifndef UBO_LVGL_H
#define UBO_LVGL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------------- */
/* Configuration                                                             */
/* ------------------------------------------------------------------------- */

typedef enum {
    UBO_BACKEND_SDL = 0,    /* desktop dev window (macOS/Linux)            */
    UBO_BACKEND_ST7789 = 1, /* Raspberry Pi ST7789 SPI panel              */
    UBO_BACKEND_BUFFER = 2, /* offscreen RGB565 framebuffer (headless,     */
                            /* for snapshot tests). See ubo_lvgl_snapshot. */
    UBO_BACKEND_SH8601 = 3, /* ESP32-C6 SH8601 368x448 AMOLED (QSPI). The  */
                            /* panel handle is supplied by the firmware    */
                            /* via ubo_backend_sh8601_set_panel().         */
} ubo_backend_t;

typedef struct {
    ubo_backend_t backend;
    int32_t width;  /* panel width  in px (default 240) */
    int32_t height; /* panel height in px (default 240) */
} ubo_lvgl_config;

/* ------------------------------------------------------------------------- */
/* View model (mirrors gRPC ViewData / StatusBarData)                        */
/* ------------------------------------------------------------------------- */

/* A single selectable menu/action item. Colors are "#RRGGBB" strings (or NULL
 * to use the theme default), matching what the core emits. `icon` is a unicode
 * glyph string (Material Design Icons / Nerd Font), or NULL. */
typedef struct {
    const char *key;
    const char *label;
    const char *icon;
    const char *color;            /* foreground, "#RRGGBB" or NULL */
    const char *background_color; /* "#RRGGBB" or NULL             */
    bool is_short;
    bool is_selected;
} ubo_menu_item;

typedef struct {
    bool show_status_bar;
    const ubo_menu_item *items;
    int item_count;
    double cpu_percent; /* 0..100 */
    double ram_percent; /* 0..100 */
    double volume_level; /* 0..1  */
} ubo_home_view;

typedef struct {
    bool show_status_bar;
    const char *title;
    const char *heading;
    const char *sub_heading;
    const char *placeholder; /* shown centred when the menu is empty, or NULL */
    const ubo_menu_item *items;
    int item_count;
    int page_index; /* 0-based            */
    int total_pages;
    int stack_depth;
} ubo_menu_view;

typedef struct {
    bool show_status_bar;
    const char *notification_id;
    const char *title;
    const char *content;
    const char *icon;
    const char *color;
    const ubo_menu_item *items; /* action items */
    int item_count;
    int page_index;
    int total_pages;
} ubo_notification_view;

typedef struct {
    bool show_status_bar;
    const char *title;
    const char *instruction;
    const char *icon;
    bool spinner;
    const char *progress_text;
    const char *footer_text;
} ubo_instruction_view;

typedef struct {
    bool show_status_bar;
    const char *title;
    const char *prompt;
    const char *icon;
    const ubo_menu_item *items; /* options, typically 2 */
    int item_count;
} ubo_prompt_view;

typedef struct {
    bool show_status_bar;
    const char *application_id;
} ubo_application_view;

/* One chat speech bubble (ChatBubbleData). Everything needed to draw it is
 * precomputed by the core: alignment ("left"=assistant / "right"=user), colors,
 * and (for kind=="audio") a normalized 0..1 waveform. */
typedef struct {
    const char *role;             /* "user" | "assistant" */
    const char *alignment;        /* "left" | "right" */
    const char *kind;             /* "text" | "audio" */
    const char *text;
    const char *color;            /* "#RRGGBB" foreground (text / waveform) */
    const char *background_color; /* "#RRGGBB" bubble fill */
    const char *pointer_key;      /* "" | "L1" | "L2" | "L3" */
    bool is_playing;
    const float *waveform;        /* normalized 0..1 bar heights (audio kind) */
    int waveform_count;
} ubo_chat_bubble;

/* The chat overlay (ChatViewData): a scrollable conversation of bubbles, newest
 * at the bottom, plus up to three L1/L2/L3 button bindings. */
typedef struct {
    bool show_status_bar;
    const ubo_chat_bubble *bubbles;
    int bubble_count;
    const ubo_menu_item *items; /* L1/L2/L3 bindings */
    int item_count;
    int scroll_offset;
    int total_bubbles;
} ubo_chat_view;

/* One generic render-widget property. Values are stringified ("42", "true");
 * list-valued props are newline-joined. Binary props (image bytes) are not
 * carried here — image/frame data uses dedicated paths. */
typedef struct {
    const char *key;
    const char *value;
} ubo_render_prop;

/* A generic render view (RenderViewData): the core dispatches on `kind`
 * (e.g. "text_viewer", "status", "qr_code", "qr_code_carousel"). */
typedef struct {
    bool show_status_bar;
    const char *kind;
    const char *title;
    const ubo_render_prop *props;
    int prop_count;
    const ubo_menu_item *items;
    int item_count;
    const char *stream_id;
} ubo_render_view;

/* ------------------------------------------------------------------------- */
/* Status bar                                                                */
/* ------------------------------------------------------------------------- */

typedef struct {
    const char *symbol; /* unicode glyph */
    const char *color;  /* "#RRGGBB" or NULL */
} ubo_status_icon;

typedef struct {
    const char *id;
    bool has_progress;  /* false => indeterminate spinner */
    double progress;    /* 0..1 when has_progress         */
    const char *color;  /* "#RRGGBB" or NULL              */
} ubo_progress_notification;

typedef struct {
    const char *title;
    bool is_recording;
    bool is_replaying;
    bool is_recording_audio;
    const ubo_progress_notification *progress_notifications;
    int progress_count;
    const char *clock; /* "HH:MM" */
    bool has_temperature;
    double temperature; /* celsius */
    bool has_light;
    double light_level; /* 0..1 */
    const ubo_status_icon *icons;
    int icon_count;
} ubo_status_bar;

/* ------------------------------------------------------------------------- */
/* Input                                                                     */
/* ------------------------------------------------------------------------- */

/* Called when a key is pressed/released. `key` is one of:
 * "UP", "DOWN", "BACK", "HOME", "L1", "L2", "L3". The bridge maps these to the
 * core's KeypadKey* actions over gRPC. */
typedef void (*ubo_input_cb)(const char *key, bool pressed, void *user);

/* ------------------------------------------------------------------------- */
/* Lifecycle & rendering                                                     */
/* ------------------------------------------------------------------------- */

/* Initialize LVGL and the display backend. Returns 0 on success. */
int ubo_lvgl_init(const ubo_lvgl_config *cfg);

void ubo_lvgl_set_input_cb(ubo_input_cb cb, void *user);

void ubo_lvgl_render_home(const ubo_home_view *v);
void ubo_lvgl_render_menu(const ubo_menu_view *v);
void ubo_lvgl_render_notification(const ubo_notification_view *v);
void ubo_lvgl_render_instruction(const ubo_instruction_view *v);
void ubo_lvgl_render_prompt(const ubo_prompt_view *v);
void ubo_lvgl_render_application(const ubo_application_view *v);
void ubo_lvgl_render_render(const ubo_render_view *v);
void ubo_lvgl_render_chat(const ubo_chat_view *v);

/* Push a raw RGB888 (3 bytes/px, top-to-bottom) frame into the current
 * image_viewer/frame_stream view. One-shot for an image, repeated for a live
 * stream. No-op unless such a view is being shown. `rgb_len` is the size of the
 * `rgb` buffer in bytes; the frame is dropped unless rgb_len >= width*height*3
 * (width/height come from the wire and must never be trusted over the actual
 * payload size). */
void ubo_lvgl_update_frame(const uint8_t *rgb, size_t rgb_len, int32_t width,
                           int32_t height);

/* Local interaction on the current generic render widget (from the core's
 * ApplicationScroll / MenuChooseByIndex events): scroll/cycle/zoom on
 * "up"/"down", and L1/L2/L3 (index 0/1/2) for the image viewer's mode. No-op
 * unless a render widget is showing. */
void ubo_lvgl_render_scroll(const char *direction);
void ubo_lvgl_render_choose(int index);

/* Hit-test a touch point against the currently-drawn selectable item bars.
 * Returns the slot index 0/1/2 (→ L1/L2/L3) of the item under (x,y), or -1 if
 * the point is not on any item (e.g. the empty centre of the home screen). Lets
 * a touch client map taps to keypad selects only where items are actually
 * rendered. Thread-safe. */
int ubo_lvgl_hit_test(int x, int y);

/* Hit-test a touch point against the home-screen volume bar. Returns the volume
 * level 0..100 the point corresponds to (top=100%, bottom=0%), or -1 if the
 * point is not on/near the bar (or no bar is shown). Lets a touch client
 * set the volume by tapping/sliding the bar. Thread-safe. */
int ubo_lvgl_hit_volume(int x, int y);

void ubo_lvgl_set_status_bar(const ubo_status_bar *s);
void ubo_lvgl_set_blanked(bool blanked);    /* backlight off + black overlay */
void ubo_lvgl_set_connected(bool connected); /* show/hide disconnect overlay  */
/* Show the disconnect overlay with a reconnect countdown subtitle. The client
 * retries forever (an appliance must self-heal when the core comes back), so
 * there is no attempt cap to display. */
void ubo_lvgl_set_disconnect_status(int attempt, int seconds);
/* Show the WiFi-setup cover: "Join '<ap_ssid>' then open http://<ip>". Used by
 * the ESP32 firmware while the captive portal is up. */
void ubo_lvgl_set_provisioning_status(const char *ap_ssid, const char *ip);

/* Run the LVGL loop.
 *   threaded=false: block on the calling thread until quit (sim / tests).
 *   threaded=true : spawn an internal loop thread and return immediately.
 * Returns 0 on success. */
int ubo_lvgl_run(bool threaded);

void ubo_lvgl_shutdown(void);

/* Headless snapshot: flush the current screen and write the offscreen
 * framebuffer to a 24-bit BMP at `path`. Only valid with UBO_BACKEND_BUFFER.
 * Returns 0 on success. Used for snapshot verification/tests on machines with
 * no display (this agent, CI). */
int ubo_lvgl_snapshot(const char *path);

/* Flush the current screen and expose the offscreen RGB565 (little-endian)
 * framebuffer. Only valid with UBO_BACKEND_BUFFER. Returns 0 on success. Backs
 * the gRPC screenshot facility (the Python side encodes PNG + hash). */
int ubo_lvgl_get_framebuffer(const uint8_t **data, int32_t *width,
                             int32_t *height);

#ifdef __cplusplus
}
#endif
#endif /* UBO_LVGL_H */
