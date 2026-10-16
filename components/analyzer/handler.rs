use crate::container::{Callbacks, Context, Result};
use crate::types::{analysis::Analysis, vibration_signal::SignalBlock};
#[path = "math.rs"]
mod math;

#[derive(Default)]
pub struct Handler;

impl Callbacks for Handler {
    fn on_input(&mut self, ctx: &mut Context, message: &SignalBlock) -> Result {
        let (rms, peak) = math::summarize(&message.samples)?;
        ctx.publish_result(&Analysis {
            machine_id: message.machine_id,
            sequence: message.sequence,
            time_ns: message.time_ns,
            rms,
            peak,
        })
    }
}
