/**
 * @file backend_st7789.c
 * Raspberry Pi backend: ST7789 240x240 panel over SPI (spidev + gpio).
 * Implemented in Step 6 of the plan. Compiled only when UBO_WITH_ST7789 is set.
 */
#include "backend.h"

#ifdef UBO_WITH_ST7789

lv_display_t *ubo_backend_st7789_create(int32_t width, int32_t height)
{
    (void)width;
    (void)height;
    LV_LOG_ERROR("ST7789 backend not yet implemented");
    return NULL;
}

#endif /* UBO_WITH_ST7789 */
