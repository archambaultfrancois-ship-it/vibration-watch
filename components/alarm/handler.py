from alarm import Alarm
from policy import classify


def process(ctx, message):
    settings = getattr(ctx, f"parameters_detection_{message.machine_id}")()
    threshold = settings.rms_threshold
    ctx.publish_event(Alarm(machine_id=message.machine_id, sequence=message.sequence,
        time_ns=message.time_ns, rms=message.rms, peak=message.peak,
        state=classify(message.rms, threshold)))


def on_machine_1(ctx, message):
    process(ctx, message)


def on_machine_2(ctx, message):
    process(ctx, message)
