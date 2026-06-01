/**
 * @file ubo_internal.h
 * Internal helpers shared between ubo_lvgl.c and the view modules.
 */
#ifndef UBO_INTERNAL_H
#define UBO_INTERNAL_H

#include "lvgl.h"

/* Serialize LVGL access against the loop thread. Render code that builds the
 * widget tree off the loop thread must hold this lock. */
void ubo_lock(void);
void ubo_unlock(void);

/* Forward an input event (from a display backend) to the registered callback.
 * `key` is one of "UP","DOWN","BACK","HOME","L1","L2","L3". */
void ubo_emit_input(const char *key, bool pressed);

#endif /* UBO_INTERNAL_H */
