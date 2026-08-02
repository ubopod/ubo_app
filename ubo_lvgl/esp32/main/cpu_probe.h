/* Per-task CPU profiler; see cpu_probe.c for why it exists. */
#ifndef UBO_CPU_PROBE_H
#define UBO_CPU_PROBE_H

/* Start the sampling task. Reports each task's share of the last interval,
 * so a feeder starved by rendering is visible directly. */
void ubo_cpu_probe_start(void);

#endif /* UBO_CPU_PROBE_H */
