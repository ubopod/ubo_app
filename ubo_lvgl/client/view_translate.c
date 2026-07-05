#include "view_translate.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include <pb_decode.h>

#include "client_log.h"
#include "ubo_client.pb.h"
#include "ubo_lvgl.h"

/* A pb_decode failure here is the classic signature of curated-proto tag
 * drift (core rebased, oneof tags shifted): the client silently renders
 * nothing. Always log the type so the symptom is visible in the serial/stderr
 * log; the fix is the lvgl-maintenance skill (sync_tags.sh + regen.sh). */
#define DECODE_FAIL(type_name_str)                                             \
    UBO_CLIENT_LOGW("pb_decode failed: %s (curated proto tag drift? "          \
                    "run lvgl-maintenance)",                                   \
                    type_name_str)

/* ── scratch arena: frees all transformed strings/arrays after a render ── */
typedef struct {
    void **p;
    size_t n, cap;
} arena;

static void arena_init(arena *a) {
    a->p = NULL;
    a->n = a->cap = 0;
}

static void *arena_take(arena *a, void *ptr) {
    if (!ptr) {
        return NULL;
    }
    if (a->n == a->cap) {
        size_t cap = a->cap ? a->cap * 2 : 16;
        void **np = realloc(a->p, cap * sizeof(void *));
        if (!np) {
            return ptr; /* leak rather than lose the pointer */
        }
        a->p = np;
        a->cap = cap;
    }
    a->p[a->n++] = ptr;
    return ptr;
}

static void arena_free(arena *a) {
    for (size_t i = 0; i < a->n; i++) {
        free(a->p[i]);
    }
    free(a->p);
    a->p = NULL;
    a->n = a->cap = 0;
}

static char *arena_strdup(arena *a, const char *s) {
    return s ? arena_take(a, strdup(s)) : NULL;
}

/* ── string transforms (mirror view_translator.py) ── */
static char *trim_take(arena *a, char *s, size_t len) {
    size_t i = 0, j = len;
    while (i < j && isspace((unsigned char)s[i])) {
        i++;
    }
    while (j > i && isspace((unsigned char)s[j - 1])) {
        j--;
    }
    if (j <= i) {
        free(s);
        return NULL;
    }
    memmove(s, s + i, j - i);
    s[j - i] = '\0';
    return arena_take(a, s);
}

/* Drop Kivy markup tags, keep the text between them; NULL if empty. */
static char *strip_markup(arena *a, const char *src) {
    if (!src) {
        return NULL;
    }
    size_t n = strlen(src);
    char *out = malloc(n + 1);
    if (!out) {
        return NULL;
    }
    size_t j = 0;
    int depth = 0;
    for (size_t i = 0; i < n; i++) {
        char ch = src[i];
        if (ch == '[') {
            depth++;
        } else if (ch == ']') {
            if (depth > 0) {
                depth--;
            }
        } else if (depth == 0) {
            out[j++] = ch;
        }
    }
    return trim_take(a, out, j);
}

static bool is_6hex(const char *s) {
    for (int i = 0; i < 6; i++) {
        if (!isxdigit((unsigned char)s[i])) {
            return false;
        }
    }
    return true;
}

/* Convert Kivy color markup to LVGL recolor syntax ("#RRGGBB text#"); drop
 * other tags. Unlike strip_markup, the result is not trimmed (matches Python).*/
static char *recolor(arena *a, const char *src) {
    if (!src) {
        return NULL;
    }
    size_t n = strlen(src);
    char *out = malloc(n + 1);
    if (!out) {
        return NULL;
    }
    size_t j = 0;
    for (size_t i = 0; i < n;) {
        if (src[i] != '[') {
            out[j++] = src[i++];
            continue;
        }
        size_t k = i + 1;
        while (k < n && src[k] != ']') {
            k++;
        }
        const char *tag = src + i + 1;
        size_t tlen = k - (i + 1);
        if (tlen >= 6 && strncmp(tag, "color=", 6) == 0) {
            const char *h = tag + 6;
            size_t hl = tlen - 6;
            if (hl > 0 && h[0] == '#') {
                h++;
                hl--;
            }
            if (hl >= 6 && is_6hex(h)) {
                out[j++] = '#';
                memcpy(out + j, h, 6);
                j += 6;
                out[j++] = ' ';
            }
        } else if (tlen == 6 && strncmp(tag, "/color", 6) == 0) {
            out[j++] = '#';
        }
        /* else: drop the tag */
        i = (k < n) ? k + 1 : k;
    }
    out[j] = '\0';
    if (j == 0) {
        free(out);
        return NULL;
    }
    return arena_take(a, out);
}

/* Map a color name/hex to "#RRGGBB" (named -> static literal; "#.." passes
 * through pointing into the decoded message); NULL if unknown. */
static const char *color_map(const char *src) {
    if (!src || !src[0]) {
        return NULL;
    }
    if (src[0] == '#') {
        return src;
    }
    if (!strcasecmp(src, "white")) return "#ffffff";
    if (!strcasecmp(src, "black")) return "#000000";
    if (!strcasecmp(src, "red")) return "#f44336";
    if (!strcasecmp(src, "green")) return "#4caf50";
    if (!strcasecmp(src, "blue")) return "#2196f3";
    if (!strcasecmp(src, "yellow")) return "#ffeb3b";
    if (!strcasecmp(src, "orange")) return "#ff9800";
    if (!strcasecmp(src, "gray") || !strcasecmp(src, "grey")) return "#808080";
    return NULL;
}

/* ── menu items ── */
static void fill_item(arena *a, ubo_menu_item *dst,
                      const ubo_client_MenuItemData *it) {
    memset(dst, 0, sizeof(*dst));
    if (!it) {
        return; /* blank notification slot */
    }
    dst->key = it->key ? it->key : "";
    char *label = strip_markup(a, it->label);
    dst->label = label ? label : "";
    dst->icon = strip_markup(a, it->icon);
    dst->color = color_map(it->color);
    dst->background_color = color_map(it->background_color);
    dst->is_short = it->is_short ? *it->is_short : false;
}

static ubo_menu_item *items_single(arena *a, const ubo_client_MenuItemData *src,
                                   size_t n, int *out_count) {
    *out_count = 0;
    if (n == 0) {
        return NULL;
    }
    ubo_menu_item *arr = arena_take(a, malloc(n * sizeof(ubo_menu_item)));
    if (!arr) {
        return NULL;
    }
    for (size_t i = 0; i < n; i++) {
        fill_item(a, &arr[i], &src[i]);
    }
    *out_count = (int)n;
    return arr;
}

/* ── BasicType / props stringification ── */
static char *basic_to_str(arena *a, const ubo_client_BasicType *b) {
    if (!b) {
        return NULL;
    }
    char buf[32];
    switch (b->which_basic_type) {
    case ubo_client_BasicType_bool_value_tag:
        return b->basic_type.bool_value
                   ? arena_strdup(a, *b->basic_type.bool_value ? "true" : "false")
                   : NULL;
    case ubo_client_BasicType_float_value_tag:
        if (!b->basic_type.float_value) {
            return NULL;
        }
        snprintf(buf, sizeof(buf), "%g", (double)*b->basic_type.float_value);
        return arena_strdup(a, buf);
    case ubo_client_BasicType_int64_value_tag:
        if (!b->basic_type.int64_value) {
            return NULL;
        }
        snprintf(buf, sizeof(buf), "%lld", (long long)*b->basic_type.int64_value);
        return arena_strdup(a, buf);
    case ubo_client_BasicType_string_value_tag:
        return arena_strdup(a, b->basic_type.string_value);
    default: /* bytes or unset */
        return NULL;
    }
}

static char *list_to_str(arena *a, const ubo_client_RenderViewData_PropsValue2 *lst) {
    if (!lst || lst->items_count == 0) {
        return arena_strdup(a, "");
    }
    char **parts = calloc(lst->items_count, sizeof(char *));
    if (!parts) {
        return NULL;
    }
    size_t np = 0, total = 0;
    for (size_t i = 0; i < lst->items_count; i++) {
        char *s = basic_to_str(a, &lst->items[i]);
        if (s) {
            parts[np++] = s;
            total += strlen(s);
        }
    }
    if (np == 0) {
        free(parts);
        return arena_strdup(a, "");
    }
    total += np - 1; /* separators */
    char *out = malloc(total + 1);
    if (!out) {
        free(parts);
        return NULL;
    }
    size_t j = 0;
    for (size_t i = 0; i < np; i++) {
        if (i) {
            out[j++] = '\n';
        }
        size_t l = strlen(parts[i]);
        memcpy(out + j, parts[i], l);
        j += l;
    }
    out[j] = '\0';
    free(parts);
    return arena_take(a, out);
}

static char *prop_value_to_str(arena *a,
                               const ubo_client_RenderViewData_PropsValue *pv) {
    if (!pv) {
        return NULL;
    }
    if (pv->which_props_value ==
        ubo_client_RenderViewData_PropsValue_basic_type_tag) {
        return basic_to_str(a, pv->props_value.basic_type);
    }
    if (pv->which_props_value == ubo_client_RenderViewData_PropsValue_list_tag) {
        return list_to_str(a, pv->props_value.list);
    }
    return NULL;
}

static const ubo_client_RenderViewData_PropsValue *
prop_find(const ubo_client_RenderViewData_PropsDict *props, const char *key) {
    if (!props) {
        return NULL;
    }
    for (size_t i = 0; i < props->items_count; i++) {
        if (props->items[i].key && strcmp(props->items[i].key, key) == 0) {
            return props->items[i].value;
        }
    }
    return NULL;
}

/* ── view builders ── */
static const char *type_name(const char *type_url) {
    const char *dot = type_url ? strrchr(type_url, '.') : NULL;
    return dot ? dot + 1 : (type_url ? type_url : "");
}

static void render_home(arena *a, const uint8_t *value, size_t len) {
    ubo_client_HomeViewData m = ubo_client_HomeViewData_init_zero;
    pb_istream_t is = pb_istream_from_buffer(value, len);
    if (pb_decode(&is, ubo_client_HomeViewData_fields, &m)) {
        ubo_home_view v;
        memset(&v, 0, sizeof(v));
        v.show_status_bar = m.show_status_bar ? *m.show_status_bar : false;
        if (m.menu_items) {
            v.items = items_single(a, m.menu_items->items,
                                   m.menu_items->items_count, &v.item_count);
        }
        v.cpu_percent = m.cpu_percent ? *m.cpu_percent : 0.0;
        v.ram_percent = m.ram_percent ? *m.ram_percent : 0.0;
        v.volume_level = m.volume_level ? *m.volume_level : 0.0;
        ubo_lvgl_render_home(&v);
    } else {
        DECODE_FAIL("HomeViewData");
    }
    pb_release(ubo_client_HomeViewData_fields, &m);
}

static void render_menu(arena *a, const uint8_t *value, size_t len) {
    ubo_client_MenuViewData m = ubo_client_MenuViewData_init_zero;
    pb_istream_t is = pb_istream_from_buffer(value, len);
    if (pb_decode(&is, ubo_client_MenuViewData_fields, &m)) {
        ubo_menu_view v;
        memset(&v, 0, sizeof(v));
        v.show_status_bar = m.show_status_bar ? *m.show_status_bar : false;
        char *title = strip_markup(a, m.title);
        v.title = title ? title : "";
        v.heading = recolor(a, m.heading);
        v.sub_heading = recolor(a, m.sub_heading);
        v.placeholder = strip_markup(a, m.placeholder);
        if (m.items) {
            /* double-wrapped; drop empty (None) slots */
            ubo_menu_item *arr =
                arena_take(a, malloc((m.items->items_count + 1) * sizeof(*arr)));
            int count = 0;
            for (size_t i = 0; arr && i < m.items->items_count; i++) {
                const ubo_client_MenuItemData *leaf = m.items->items[i].items;
                if (leaf) {
                    fill_item(a, &arr[count++], leaf);
                }
            }
            v.items = arr;
            v.item_count = count;
        }
        v.page_index = m.page_index ? (int)*m.page_index : 0;
        v.total_pages = m.total_pages ? (int)*m.total_pages : 1;
        v.stack_depth = m.stack_depth ? (int)*m.stack_depth : 1;
        ubo_lvgl_render_menu(&v);
    } else {
        DECODE_FAIL("MenuViewData");
    }
    pb_release(ubo_client_MenuViewData_fields, &m);
}

static void render_notification(arena *a, const uint8_t *value, size_t len) {
    ubo_client_NotificationViewData m = ubo_client_NotificationViewData_init_zero;
    pb_istream_t is = pb_istream_from_buffer(value, len);
    if (pb_decode(&is, ubo_client_NotificationViewData_fields, &m)) {
        ubo_notification_view v;
        memset(&v, 0, sizeof(v));
        v.show_status_bar = m.show_status_bar ? *m.show_status_bar : false;
        v.notification_id = m.notification_id ? m.notification_id : "";
        char *title = strip_markup(a, m.title);
        v.title = title ? title : "";
        char *content = strip_markup(a, m.content);
        v.content = content ? content : "";
        v.icon = strip_markup(a, m.icon);
        v.color = color_map(m.color);
        if (m.items) {
            /* double-wrapped; KEEP empty slots as blank items (alignment) */
            ubo_menu_item *arr =
                arena_take(a, malloc((m.items->items_count + 1) * sizeof(*arr)));
            int count = 0;
            for (size_t i = 0; arr && i < m.items->items_count; i++) {
                fill_item(a, &arr[count++], m.items->items[i].items);
            }
            v.items = arr;
            v.item_count = count;
        }
        v.page_index = m.page_index ? (int)*m.page_index : 0;
        v.total_pages = m.total_pages ? (int)*m.total_pages : 1;
        ubo_lvgl_render_notification(&v);
    } else {
        DECODE_FAIL("NotificationViewData");
    }
    pb_release(ubo_client_NotificationViewData_fields, &m);
}

static void render_instruction(arena *a, const uint8_t *value, size_t len) {
    ubo_client_InstructionViewData m = ubo_client_InstructionViewData_init_zero;
    pb_istream_t is = pb_istream_from_buffer(value, len);
    if (pb_decode(&is, ubo_client_InstructionViewData_fields, &m)) {
        ubo_instruction_view v;
        memset(&v, 0, sizeof(v));
        v.show_status_bar = m.show_status_bar ? *m.show_status_bar : false;
        char *title = strip_markup(a, m.title);
        v.title = title ? title : "";
        char *instr = strip_markup(a, m.instruction);
        v.instruction = instr ? instr : "";
        v.icon = strip_markup(a, m.icon);
        v.spinner = m.spinner ? *m.spinner : false;
        v.progress_text = strip_markup(a, m.progress_text);
        v.footer_text = strip_markup(a, m.footer_text);
        ubo_lvgl_render_instruction(&v);
    } else {
        DECODE_FAIL("InstructionViewData");
    }
    pb_release(ubo_client_InstructionViewData_fields, &m);
}

static void render_prompt(arena *a, const uint8_t *value, size_t len) {
    ubo_client_PromptViewData m = ubo_client_PromptViewData_init_zero;
    pb_istream_t is = pb_istream_from_buffer(value, len);
    if (pb_decode(&is, ubo_client_PromptViewData_fields, &m)) {
        ubo_prompt_view v;
        memset(&v, 0, sizeof(v));
        v.show_status_bar = m.show_status_bar ? *m.show_status_bar : false;
        char *title = strip_markup(a, m.title);
        v.title = title ? title : "";
        char *prompt = strip_markup(a, m.prompt);
        v.prompt = prompt ? prompt : "";
        v.icon = strip_markup(a, m.icon);
        if (m.items) {
            v.items = items_single(a, m.items->items, m.items->items_count,
                                   &v.item_count);
        }
        ubo_lvgl_render_prompt(&v);
    } else {
        DECODE_FAIL("PromptViewData");
    }
    pb_release(ubo_client_PromptViewData_fields, &m);
}

static void render_application(arena *a, const uint8_t *value, size_t len) {
    (void)a;
    ubo_client_ApplicationViewData m = ubo_client_ApplicationViewData_init_zero;
    pb_istream_t is = pb_istream_from_buffer(value, len);
    if (pb_decode(&is, ubo_client_ApplicationViewData_fields, &m)) {
        ubo_application_view v;
        memset(&v, 0, sizeof(v));
        v.show_status_bar = m.show_status_bar ? *m.show_status_bar : false;
        v.application_id = m.application_id ? m.application_id : "";
        ubo_lvgl_render_application(&v);
    } else {
        DECODE_FAIL("ApplicationViewData");
    }
    pb_release(ubo_client_ApplicationViewData_fields, &m);
}

static void render_chat(arena *a, const uint8_t *value, size_t len) {
    ubo_client_ChatViewData m = ubo_client_ChatViewData_init_zero;
    pb_istream_t is = pb_istream_from_buffer(value, len);
    if (pb_decode(&is, ubo_client_ChatViewData_fields, &m)) {
        ubo_chat_view v;
        memset(&v, 0, sizeof(v));
        v.show_status_bar = m.show_status_bar ? *m.show_status_bar : false;
        v.scroll_offset = m.scroll_offset ? (int)*m.scroll_offset : 0;
        v.total_bubbles = m.total_bubbles ? (int)*m.total_bubbles : 0;
        if (m.bubbles) {
            size_t n = m.bubbles->items_count;
            ubo_chat_bubble *arr =
                arena_take(a, malloc((n ? n : 1) * sizeof(*arr)));
            int count = 0;
            for (size_t i = 0; arr && i < n; i++) {
                const ubo_client_ChatBubbleData *src = &m.bubbles->items[i];
                ubo_chat_bubble *d = &arr[count++];
                memset(d, 0, sizeof(*d));
                d->role = src->role ? src->role : "assistant";
                d->alignment = src->alignment ? src->alignment : "left";
                d->kind = src->kind ? src->kind : "text";
                d->text = strip_markup(a, src->text);
                if (!d->text) {
                    d->text = "";
                }
                d->color = color_map(src->color);
                d->background_color = color_map(src->background_color);
                d->pointer_key = src->pointer_key ? src->pointer_key : "";
                d->is_playing = src->is_playing ? *src->is_playing : false;
                if (src->waveform && src->waveform->items_count) {
                    /* Valid until pb_release below; the renderer copies it. */
                    d->waveform = src->waveform->items;
                    d->waveform_count = (int)src->waveform->items_count;
                }
            }
            v.bubbles = arr;
            v.bubble_count = count;
        }
        if (m.items) {
            size_t n = m.items->items_count;
            ubo_menu_item *arr =
                arena_take(a, malloc((n ? n : 1) * sizeof(*arr)));
            int count = 0;
            for (size_t i = 0; arr && i < n; i++) {
                fill_item(a, &arr[count++], &m.items->items[i]);
            }
            v.items = arr;
            v.item_count = count;
        }
        ubo_lvgl_render_chat(&v);
    } else {
        DECODE_FAIL("ChatViewData");
    }
    pb_release(ubo_client_ChatViewData_fields, &m);
}

static void render_render(arena *a, const uint8_t *value, size_t len,
                          char **out_stream_id) {
    ubo_client_RenderViewData m = ubo_client_RenderViewData_init_zero;
    pb_istream_t is = pb_istream_from_buffer(value, len);
    if (pb_decode(&is, ubo_client_RenderViewData_fields, &m)) {
        ubo_render_view v;
        memset(&v, 0, sizeof(v));
        v.show_status_bar = m.show_status_bar ? *m.show_status_bar : false;
        v.kind = m.kind ? m.kind : "";
        char *title = strip_markup(a, m.title);
        v.title = title ? title : "";
        v.stream_id = m.stream_id;
        if (m.props && m.props->items_count) {
            ubo_render_prop *props =
                arena_take(a, malloc(m.props->items_count * sizeof(*props)));
            int count = 0;
            for (size_t i = 0; props && i < m.props->items_count; i++) {
                char *val = prop_value_to_str(a, m.props->items[i].value);
                if (val) {
                    props[count].key = m.props->items[i].key
                                           ? m.props->items[i].key
                                           : "";
                    props[count].value = val;
                    count++;
                }
            }
            v.props = props;
            v.prop_count = count;
        }
        if (m.items) {
            v.items = items_single(a, m.items->items, m.items->items_count,
                                   &v.item_count);
        }
        ubo_lvgl_render_render(&v);

        /* image_viewer ships its image inline (a bytes prop); push it now. */
        if (strcmp(v.kind, "image_viewer") == 0) {
            const ubo_client_RenderViewData_PropsValue *img =
                prop_find(m.props, "image");
            char *ws = prop_value_to_str(a, prop_find(m.props, "width"));
            char *hs = prop_value_to_str(a, prop_find(m.props, "height"));
            if (img &&
                img->which_props_value ==
                    ubo_client_RenderViewData_PropsValue_basic_type_tag &&
                img->props_value.basic_type &&
                img->props_value.basic_type->which_basic_type ==
                    ubo_client_BasicType_bytes_value_tag &&
                img->props_value.basic_type->basic_type.bytes_value && ws && hs) {
                pb_bytes_array_t *bytes =
                    img->props_value.basic_type->basic_type.bytes_value;
                int w = atoi(ws), h = atoi(hs);
                if (w > 0 && h > 0) {
                    ubo_lvgl_update_frame(bytes->bytes, bytes->size, w, h);
                }
            }
        }
        if (out_stream_id && strcmp(v.kind, "frame_stream") == 0 && m.stream_id &&
            m.stream_id[0]) {
            *out_stream_id = strdup(m.stream_id);
        }
    } else {
        DECODE_FAIL("RenderViewData");
    }
    pb_release(ubo_client_RenderViewData_fields, &m);
}

void ubo_view_render(const char *type_url, const uint8_t *value, size_t value_len,
                     char **out_stream_id) {
    if (out_stream_id) {
        *out_stream_id = NULL;
    }
    const char *name = type_name(type_url);
    arena a;
    arena_init(&a);
    if (strcmp(name, "HomeViewData") == 0) {
        render_home(&a, value, value_len);
    } else if (strcmp(name, "MenuViewData") == 0) {
        render_menu(&a, value, value_len);
    } else if (strcmp(name, "NotificationViewData") == 0) {
        render_notification(&a, value, value_len);
    } else if (strcmp(name, "InstructionViewData") == 0) {
        render_instruction(&a, value, value_len);
    } else if (strcmp(name, "PromptViewData") == 0) {
        render_prompt(&a, value, value_len);
    } else if (strcmp(name, "ApplicationViewData") == 0) {
        render_application(&a, value, value_len);
    } else if (strcmp(name, "ChatViewData") == 0) {
        render_chat(&a, value, value_len);
    } else if (strcmp(name, "RenderViewData") == 0) {
        render_render(&a, value, value_len, out_stream_id);
    }
    arena_free(&a);
}

void ubo_view_render_status_bar(const uint8_t *value, size_t value_len) {
    arena a;
    arena_init(&a);
    ubo_client_StatusBarData sb = ubo_client_StatusBarData_init_zero;
    pb_istream_t is = pb_istream_from_buffer(value, value_len);
    if (pb_decode(&is, ubo_client_StatusBarData_fields, &sb)) {
        ubo_status_bar s;
        memset(&s, 0, sizeof(s));
        s.title = sb.title ? sb.title : "";
        s.is_recording = sb.is_recording ? *sb.is_recording : false;
        s.is_replaying = sb.is_replaying ? *sb.is_replaying : false;
        s.is_recording_audio =
            sb.is_recording_audio ? *sb.is_recording_audio : false;
        if (sb.progress_notifications) {
            size_t n = sb.progress_notifications->items_count;
            ubo_progress_notification *pn =
                arena_take(&a, malloc((n ? n : 1) * sizeof(*pn)));
            for (size_t i = 0; pn && i < n; i++) {
                const ubo_client_ProgressNotificationData *p =
                    &sb.progress_notifications->items[i];
                pn[i].id = p->id ? p->id : "";
                pn[i].has_progress = p->progress != NULL;
                pn[i].progress = p->progress ? *p->progress : 0.0;
                pn[i].color = color_map(p->color);
            }
            s.progress_notifications = pn;
            s.progress_count = (int)n;
        }
        s.clock = sb.clock ? sb.clock : "";
        s.has_temperature = sb.temperature != NULL;
        s.temperature = sb.temperature ? *sb.temperature : 0.0;
        s.has_light = sb.light_level != NULL;
        s.light_level = sb.light_level ? *sb.light_level : 0.0;
        if (sb.icons) {
            size_t n = sb.icons->items_count;
            ubo_status_icon *ic = arena_take(&a, malloc((n ? n : 1) * sizeof(*ic)));
            for (size_t i = 0; ic && i < n; i++) {
                char *sym = strip_markup(&a, sb.icons->items[i].symbol);
                ic[i].symbol = sym ? sym : "";
                ic[i].color = color_map(sb.icons->items[i].color);
            }
            s.icons = ic;
            s.icon_count = (int)n;
        }
        ubo_lvgl_set_status_bar(&s);
    } else {
        DECODE_FAIL("StatusBarData");
    }
    pb_release(ubo_client_StatusBarData_fields, &sb);
    arena_free(&a);
}
