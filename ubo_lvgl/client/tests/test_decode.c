/* Phase-0 smoke test: decode captured server blobs with the curated nanopb
 * schema and print key fields, proving field numbers / pointer-mode line up.
 *
 * Usage: test_decode <home|menu> <view.bin> [statusbar.bin] [blanked.bin]
 * The .bin files are raw google.protobuf.Any `value` bytes captured from a live
 * SubscribeStore. NOTE: current_view's Any holds the CONCRETE view message
 * (HomeViewData/MenuViewData/...) keyed by Any.type_url, not a ViewData oneof.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <pb_decode.h>

#include "ubo_client.pb.h"

static size_t read_file(const char *path, uint8_t *buf, size_t cap) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", path);
        exit(2);
    }
    size_t n = fread(buf, 1, cap, f);
    fclose(f);
    return n;
}

static const char *str_or(const char *s, const char *dflt) {
    return s ? s : dflt;
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr,
                "usage: %s <home|menu> <view.bin> [statusbar.bin] [blanked.bin]\n",
                argv[0]);
        return 1;
    }

    uint8_t buf[8192];

    /* ── View (concrete message, dispatched by kind / type_url) ── */
    size_t n = read_file(argv[2], buf, sizeof(buf));
    pb_istream_t s = pb_istream_from_buffer(buf, n);
    if (strcmp(argv[1], "home") == 0) {
        ubo_client_HomeViewData h = ubo_client_HomeViewData_init_zero;
        if (!pb_decode(&s, ubo_client_HomeViewData_fields, &h)) {
            fprintf(stderr, "HomeViewData decode failed: %s\n", PB_GET_ERROR(&s));
            return 3;
        }
        int items = (h.menu_items) ? (int)h.menu_items->items_count : 0;
        printf("HomeViewData: cpu=%.1f ram=%.1f vol=%.2f menu_items=%d\n",
               h.cpu_percent ? *h.cpu_percent : -1.0,
               h.ram_percent ? *h.ram_percent : -1.0,
               h.volume_level ? *h.volume_level : -1.0, items);
        pb_release(ubo_client_HomeViewData_fields, &h);
    } else {
        ubo_client_MenuViewData m = ubo_client_MenuViewData_init_zero;
        if (!pb_decode(&s, ubo_client_MenuViewData_fields, &m)) {
            fprintf(stderr, "MenuViewData decode failed: %s\n", PB_GET_ERROR(&s));
            return 3;
        }
        int items = (m.items) ? (int)m.items->items_count : 0;
        printf("MenuViewData: title=%s page=%lld/%lld items=%d\n",
               str_or(m.title, "(none)"),
               m.page_index ? (long long)*m.page_index : -1,
               m.total_pages ? (long long)*m.total_pages : -1, items);
        if (items > 0) {
            ubo_client_MenuItemData *it = m.items->items[0].items;
            if (it)
                printf("  item[0]: key=%s label=%s\n", str_or(it->key, ""),
                       str_or(it->label, ""));
        }
        pb_release(ubo_client_MenuViewData_fields, &m);
    }

    /* ── StatusBarData ── */
    if (argc >= 4) {
        n = read_file(argv[3], buf, sizeof(buf));
        ubo_client_StatusBarData sb = ubo_client_StatusBarData_init_zero;
        s = pb_istream_from_buffer(buf, n);
        if (!pb_decode(&s, ubo_client_StatusBarData_fields, &sb)) {
            fprintf(stderr, "StatusBarData decode failed: %s\n", PB_GET_ERROR(&s));
            return 4;
        }
        int icons = (sb.icons) ? (int)sb.icons->items_count : 0;
        printf("StatusBarData: title=%s clock=%s temp=%.1f icons=%d\n",
               str_or(sb.title, "(none)"), str_or(sb.clock, "(none)"),
               sb.temperature ? *sb.temperature : -1.0, icons);
        pb_release(ubo_client_StatusBarData_fields, &sb);
    }

    /* ── BoolValue (is_blanked) ── */
    if (argc >= 5) {
        n = read_file(argv[4], buf, sizeof(buf));
        ubo_client_BoolValue bv = ubo_client_BoolValue_init_zero;
        s = pb_istream_from_buffer(buf, n);
        if (!pb_decode(&s, ubo_client_BoolValue_fields, &bv)) {
            fprintf(stderr, "BoolValue decode failed: %s\n", PB_GET_ERROR(&s));
            return 5;
        }
        printf("is_blanked = %s\n", bv.value ? "true" : "false");
        pb_release(ubo_client_BoolValue_fields, &bv);
    }

    printf("OK\n");
    return 0;
}
