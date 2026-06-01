/**
 * @file backend_st7789.c
 * Raspberry Pi backend: ST7789 240x240 panel over SPI. Uses the Linux spidev
 * and GPIO character-device uapi directly (no libgpiod/Adafruit needed).
 *
 * Wiring (BCM numbering, from ubo_gui_client/display.py):
 *   CS  = GPIO8  (CE0; driven manually because the device uses dtoverlay
 *                 spi0-0cs, i.e. no hardware chip-select)
 *   DC  = GPIO25
 *   BL  = GPIO26 (backlight, active-high)
 * SPI: /dev/spidev0.0, mode 0, 60 MHz. Panel: RGB565, INVON, y_offset 80.
 *
 * Orientation is fiddly per panel, so MADCTL and the column/row offsets are
 * tunable at runtime via env vars to allow quick iteration on the device:
 *   UBO_ST7789_MADCTL (hex, default C0)  UBO_ST7789_XOFF (default 0)
 *   UBO_ST7789_YOFF   (default 80)       UBO_ST7789_SPI_HZ (default 60000000)
 */
#include "backend.h"

#ifdef UBO_WITH_ST7789

#include <errno.h>
#include <fcntl.h>
#include <linux/gpio.h>
#include <linux/spi/spidev.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

/* GPIO line offsets (BCM) on gpiochip0. */
#define LINE_CS 8
#define LINE_DC 25
#define LINE_BL 26

static int s_spi = -1;
static int s_gpio = -1; /* gpiohandle fd controlling CS, DC, BL */
static uint32_t s_spi_hz = 60000000;
static uint8_t s_madctl = 0xC0;
static int s_xoff = 0;
static int s_yoff = 80;

/* Cached GPIO output values: index 0=CS, 1=DC, 2=BL. */
static struct gpiohandle_data s_gpio_vals;

static int env_int(const char *name, int fallback, int base)
{
    const char *v = getenv(name);
    if (!v || !v[0]) {
        return fallback;
    }
    return (int)strtol(v, NULL, base);
}

static void msleep(long ms)
{
    struct timespec ts = {.tv_sec = ms / 1000, .tv_nsec = (ms % 1000) * 1000000L};
    nanosleep(&ts, NULL);
}

static void gpio_set(int idx, int value)
{
    s_gpio_vals.values[idx] = (uint8_t)(value ? 1 : 0);
    ioctl(s_gpio, GPIOHANDLE_SET_LINE_VALUES_IOCTL, &s_gpio_vals);
}

#define cs_low() gpio_set(0, 0)
#define cs_high() gpio_set(0, 1)
#define dc_cmd() gpio_set(1, 0)
#define dc_data() gpio_set(1, 1)

/* spidev caps a single transfer at the module's bufsiz (4096 by default), so
 * chunk large writes. CS stays asserted across the chunks. */
static void spi_xfer(const uint8_t *data, size_t len)
{
    size_t off = 0;
    while (off < len) {
        size_t chunk = len - off;
        if (chunk > 4096) {
            chunk = 4096;
        }
        struct spi_ioc_transfer tr;
        memset(&tr, 0, sizeof(tr));
        tr.tx_buf = (unsigned long)(data + off);
        tr.len = (uint32_t)chunk;
        tr.speed_hz = s_spi_hz;
        tr.bits_per_word = 8;
        if (ioctl(s_spi, SPI_IOC_MESSAGE(1), &tr) < 0) {
            static int warned;
            if (!warned) {
                warned = 1;
                LV_LOG_ERROR("ST7789: SPI transfer failed (errno=%d)", errno);
            }
        }
        off += chunk;
    }
}

/* Match the adafruit driver: DC set first, then CS toggled around each command
 * / data block (some ST7789 panels need CS to toggle per transaction). */
static void write_cmd(uint8_t cmd)
{
    dc_cmd();
    cs_low();
    spi_xfer(&cmd, 1);
    cs_high();
}

static void write_data(const uint8_t *data, size_t len)
{
    dc_data();
    cs_low();
    spi_xfer(data, len);
    cs_high();
}

static int open_hw(void)
{
    s_spi = open("/dev/spidev0.0", O_RDWR);
    if (s_spi < 0) {
        LV_LOG_ERROR("ST7789: cannot open /dev/spidev0.0");
        return -1;
    }
    uint8_t mode = 0;
    uint8_t bits = 8;
    ioctl(s_spi, SPI_IOC_WR_MODE, &mode);
    ioctl(s_spi, SPI_IOC_WR_BITS_PER_WORD, &bits);
    ioctl(s_spi, SPI_IOC_WR_MAX_SPEED_HZ, &s_spi_hz);

    int chip = open("/dev/gpiochip0", O_RDONLY);
    if (chip < 0) {
        LV_LOG_ERROR("ST7789: cannot open /dev/gpiochip0");
        return -1;
    }
    struct gpiohandle_request req;
    memset(&req, 0, sizeof(req));
    req.lineoffsets[0] = LINE_CS;
    req.lineoffsets[1] = LINE_DC;
    req.lineoffsets[2] = LINE_BL;
    req.lines = 3;
    req.flags = GPIOHANDLE_REQUEST_OUTPUT;
    req.default_values[0] = 1; /* CS idle high */
    req.default_values[1] = 0; /* DC */
    req.default_values[2] = 1; /* backlight on */
    strncpy(req.consumer_label, "ubo-lvgl", sizeof(req.consumer_label) - 1);
    if (ioctl(chip, GPIO_GET_LINEHANDLE_IOCTL, &req) < 0 || req.fd < 0) {
        LV_LOG_ERROR("ST7789: GPIO line request failed");
        close(chip);
        return -1;
    }
    close(chip);
    s_gpio = req.fd;
    s_gpio_vals.values[0] = 1;
    s_gpio_vals.values[1] = 0;
    s_gpio_vals.values[2] = 1;
    return 0;
}

static void panel_init(void)
{
    write_cmd(0x01); /* SWRESET */
    msleep(150);
    write_cmd(0x11); /* SLPOUT */
    msleep(120);
    uint8_t colmod = 0x55; /* 16-bit RGB565 */
    write_cmd(0x3A);
    write_data(&colmod, 1);
    write_cmd(0x36); /* MADCTL */
    write_data(&s_madctl, 1);
    write_cmd(0x21); /* INVON (ST7789 needs inversion) */
    write_cmd(0x13); /* NORON */
    write_cmd(0x29); /* DISPON */
    msleep(50);
}

static void set_window(int x0, int y0, int x1, int y1)
{
    x0 += s_xoff;
    x1 += s_xoff;
    y0 += s_yoff;
    y1 += s_yoff;
    uint8_t b[4];
    write_cmd(0x2A); /* CASET */
    b[0] = (uint8_t)(x0 >> 8);
    b[1] = (uint8_t)x0;
    b[2] = (uint8_t)(x1 >> 8);
    b[3] = (uint8_t)x1;
    write_data(b, 4);
    write_cmd(0x2B); /* RASET */
    b[0] = (uint8_t)(y0 >> 8);
    b[1] = (uint8_t)y0;
    b[2] = (uint8_t)(y1 >> 8);
    b[3] = (uint8_t)y1;
    write_data(b, 4);
    write_cmd(0x2C); /* RAMWR */
}

static void st7789_flush(lv_display_t *disp, const lv_area_t *area,
                         uint8_t *px_map)
{
    const int w = area->x2 - area->x1 + 1;
    const int h = area->y2 - area->y1 + 1;
    const size_t n = (size_t)w * h;

    /* LVGL stores RGB565 little-endian; ST7789 wants big-endian (MSB first). */
    uint16_t *p = (uint16_t *)px_map;
    for (size_t i = 0; i < n; i++) {
        const uint16_t v = p[i];
        p[i] = (uint16_t)((v >> 8) | (v << 8));
    }

    set_window(area->x1, area->y1, area->x2, area->y2);
    write_data(px_map, n * 2);

    lv_display_flush_ready(disp);
}

lv_display_t *ubo_backend_st7789_create(int32_t width, int32_t height)
{
    s_spi_hz = (uint32_t)env_int("UBO_ST7789_SPI_HZ", 60000000, 10);
    s_madctl = (uint8_t)env_int("UBO_ST7789_MADCTL", 0xC0, 16);
    s_xoff = env_int("UBO_ST7789_XOFF", 0, 10);
    s_yoff = env_int("UBO_ST7789_YOFF", 80, 10);

    if (open_hw() != 0) {
        return NULL;
    }
    panel_init();

    lv_display_t *disp = lv_display_create(width, height);
    lv_display_set_color_format(disp, LV_COLOR_FORMAT_RGB565);

    static uint8_t *buf;
    const size_t buf_px = (size_t)width * height;
    buf = malloc(buf_px * 2);
    if (!buf) {
        return NULL;
    }
    lv_display_set_buffers(disp, buf, NULL, buf_px * 2,
                           LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(disp, st7789_flush);
    LV_LOG_USER("ST7789 ready (madctl=0x%02X xoff=%d yoff=%d %u Hz)", s_madctl,
                s_xoff, s_yoff, s_spi_hz);
    return disp;
}

#endif /* UBO_WITH_ST7789 */
