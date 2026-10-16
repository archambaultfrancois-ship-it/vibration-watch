#include "component.h"
#include "waveform.h"
#include <errno.h>
#include <stdlib.h>

static uint32_t machine, count, random_state;
static uint64_t sample_index;
static double rate, frequency, amplitude, ramp, noise;
static float *samples;

static int number(const char *name, double *value, double minimum, double maximum) {
    const char *text = getenv(name);
    char *end;
    if (!text || !*text) return 0;
    errno = 0;
    *value = strtod(text, &end);
    return !errno && !*end && isfinite(*value) && *value >= minimum && *value <= maximum;
}

static int on_start(ChainContext *ctx) {
    double id, size, seed;
    (void)ctx;
    if (!number("VW_MACHINE", &id, 1, UINT32_MAX) || floor(id) != id ||
        !number("VW_SAMPLES", &size, 1, 131072) || floor(size) != size ||
        !number("VW_SEED", &seed, 1, UINT32_MAX) || floor(seed) != seed ||
        !number("VW_RATE", &rate, 1, 1000000000) ||
        !number("VW_FREQUENCY", &frequency, 0, rate / 2) ||
        !number("VW_AMPLITUDE", &amplitude, 0, 1000000) ||
        !number("VW_RAMP", &ramp, 0, 1000000) ||
        !number("VW_NOISE", &noise, 0, 1000000)) return 0;
    machine = (uint32_t)id;
    count = (uint32_t)size;
    random_state = (uint32_t)seed;
    sample_index = 0;
    samples = malloc((size_t)count * sizeof(*samples));
    return samples != NULL;
}

static int on_tick(ChainContext *ctx) {
    double level = amplitude + ramp * chain_now(ctx);
    if (!isfinite(level) || level > 1e12) return 0;
    for (uint32_t i = 0; i < count; ++i)
        samples[i] = vibration_sample(sample_index++, rate, frequency, level, noise, &random_state);
    SignalBlock message = {0};
    message.machine_id = machine;
    message.sequence = chain_tick_index(ctx);
    message.time_ns = chain_time_ns(ctx);
    message.sample_rate_hz = rate;
    message.samples_count = count;
    message.samples = samples;
    return publish_signal(ctx, &message);
}

static int on_stop(ChainContext *ctx) {
    (void)ctx;
    free(samples);
    samples = NULL;
    return 1;
}

const ComponentCallbacks component_callbacks = {
    .on_start = on_start, .on_tick = on_tick, .on_stop = on_stop
};
