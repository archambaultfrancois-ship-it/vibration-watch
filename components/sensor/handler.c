#include "component.h"
#include "waveform.h"
#include <errno.h>
#include <stdlib.h>

static uint32_t machine, count, random_state, configured_seed;
static uint64_t sample_index;
static float *samples;

static int valid_settings(const SensorSettings *p) {
    return p && p->samples >= 1 && p->samples <= 131072 && p->seed != 0 &&
        isfinite(p->sample_rate_hz) && p->sample_rate_hz >= 1 && p->sample_rate_hz <= 1e9 &&
        isfinite(p->frequency_hz) && p->frequency_hz >= 0 && p->frequency_hz <= p->sample_rate_hz / 2 &&
        isfinite(p->amplitude) && p->amplitude >= 0 && p->amplitude <= 1e6 &&
        isfinite(p->noise) && p->noise >= 0 && p->noise <= 1e6 &&
        isfinite(p->ramp_per_second) && p->ramp_per_second >= 0 && p->ramp_per_second <= 1e6;
}

static int apply_settings(ChainContext *ctx, const SensorSettings *p) {
    if (!valid_settings(p)) return chain_fail(ctx, "invalid sensor settings");
    if (p->samples != count) {
        float *resized = realloc(samples, (size_t)p->samples * sizeof(*samples));
        if (!resized) return chain_fail(ctx, "cannot allocate sample buffer");
        samples = resized;
        count = p->samples;
    }
    if (p->seed != configured_seed) {
        configured_seed = p->seed;
        random_state = p->seed;
    }
    return 1;
}

static int on_start(ChainContext *ctx) {
    const char *identity = getenv("VW_MACHINE");
    char *end;
    if (!identity || !*identity) return chain_fail(ctx, "missing VW_MACHINE identity");
    errno = 0;
    double id = strtod(identity, &end);
    if (errno || *end || !isfinite(id) || id < 1 || id > UINT32_MAX || floor(id) != id)
        return chain_fail(ctx, "invalid VW_MACHINE identity");
    machine = (uint32_t)id;
    sample_index = 0;
    return apply_settings(ctx, parameters_signal(ctx));
}

static int on_tick(ChainContext *ctx) {
    const SensorSettings *p = parameters_signal(ctx);
    if (!apply_settings(ctx, p)) return 0;
    double level = p->amplitude + p->ramp_per_second * chain_now(ctx);
    if (!isfinite(level) || level > 1e12) return chain_fail(ctx, "sensor amplitude exceeds limit");
    for (uint32_t i = 0; i < count; ++i)
        samples[i] = vibration_sample(sample_index++, p->sample_rate_hz, p->frequency_hz,
                                      level, p->noise, &random_state);
    SignalBlock message = {0};
    message.machine_id = machine;
    message.sequence = chain_tick_index(ctx);
    message.time_ns = chain_time_ns(ctx);
    message.sample_rate_hz = p->sample_rate_hz;
    message.samples_count = count;
    message.samples = samples;
    return publish_signal(ctx, &message);
}

static int on_stop(ChainContext *ctx) {
    (void)ctx;
    free(samples);
    samples = NULL;
    count = configured_seed = random_state = 0;
    return 1;
}

const ComponentCallbacks component_callbacks = {
    .on_start = on_start, .on_tick = on_tick, .on_stop = on_stop
};
