/* Per-task CPU profiler.
 *
 * Added to test whether rendering starves audio: streamed assistant text drives
 * a chat-widget redraw per token, and the symptom is that TTS breaks up only
 * while that redraw is running, then plays cleanly once the text settles. The
 * playback ring is fed by the event task and drained by the play task, so if
 * LVGL/rendering monopolises the CPU the ring runs *empty* -- an underrun,
 * which no drop counter sees because nothing is ever refused.
 *
 * Samples the FreeRTOS run-time counters and reports each task's share of the
 * interval, so a starved feeder shows up directly.
 */

#include "cpu_probe.h"

#ifdef CONFIG_UBO_CPU_PROBE

#include <stdlib.h>
#include <string.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "ubo_cpu";

#define PROBE_MAX_TASKS 32
#define PROBE_PERIOD_MS 1000
/* Only tasks above this share of the interval are listed, so the line stays
 * readable; the total is always reported. */
#define PROBE_REPORT_PERCENT 3

struct sample {
    TaskHandle_t handle;
    uint32_t runtime;
};

static struct sample s_previous[PROBE_MAX_TASKS];
static size_t s_previous_count;
static uint32_t s_previous_total;

static uint32_t previous_runtime_of(TaskHandle_t handle)
{
    for (size_t i = 0; i < s_previous_count; i++) {
        if (s_previous[i].handle == handle) {
            return s_previous[i].runtime;
        }
    }
    return 0;
}

static void probe_task(void *arg)
{
    (void)arg;
    TaskStatus_t *status = malloc(PROBE_MAX_TASKS * sizeof(*status));
    if (!status) {
        ESP_LOGE(TAG, "probe: out of memory");
        vTaskDelete(NULL);
        return;
    }
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(PROBE_PERIOD_MS));

        uint32_t total = 0;
        const UBaseType_t count =
            uxTaskGetSystemState(status, PROBE_MAX_TASKS, &total);
        const uint32_t elapsed = total - s_previous_total;
        if (elapsed == 0) {
            continue;
        }

        /* One line per interval: "cpu: idle 42% | lvgl 31% ubo_event 12% ..." */
        char line[256];
        int used = 0;
        unsigned busiest = 0;
        for (UBaseType_t i = 0; i < count; i++) {
            const uint32_t delta =
                status[i].ulRunTimeCounter - previous_runtime_of(status[i].xHandle);
            const unsigned percent = (unsigned)((uint64_t)delta * 100 / elapsed);
            if (percent < PROBE_REPORT_PERCENT) {
                continue;
            }
            if (strncmp(status[i].pcTaskName, "IDLE", 4) != 0 &&
                percent > busiest) {
                busiest = percent;
            }
            const int written =
                snprintf(line + used, sizeof(line) - (size_t)used, "%s %u%% ",
                         status[i].pcTaskName, percent);
            if (written <= 0 || (size_t)(used + written) >= sizeof(line)) {
                break;
            }
            used += written;
        }
        ESP_LOGI(TAG, "cpu: %s", line);

        s_previous_count = count < PROBE_MAX_TASKS ? count : PROBE_MAX_TASKS;
        for (size_t i = 0; i < s_previous_count; i++) {
            s_previous[i].handle = status[i].xHandle;
            s_previous[i].runtime = status[i].ulRunTimeCounter;
        }
        s_previous_total = total;
    }
}

void ubo_cpu_probe_start(void)
{
    /* Low priority: the probe must never itself displace the work it measures. */
    xTaskCreate(probe_task, "ubo_cpu", 4096, NULL, 1, NULL);
}

#else  /* !CONFIG_UBO_CPU_PROBE */

void ubo_cpu_probe_start(void) {}

#endif
