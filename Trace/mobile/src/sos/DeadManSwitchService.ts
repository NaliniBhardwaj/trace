import { Accelerometer } from 'expo-sensors';

type Subscription = { remove: () => void };

/**
 * Phase 18 — dead man's switch (feature 5). H2S causes olfactory fatigue
 * (you stop smelling it right as it gets dangerous) and can cause sudden
 * collapse at high concentrations, so this does not wait for the worker to
 * press anything: it watches the phone's accelerometer for two patterns and
 * hands off to DeadmanContext, which runs a cancellable "are you okay?"
 * countdown before actually firing the SOS pipeline. This service only
 * *detects*; it never calls the API directly, so it stays testable and the
 * countdown/cancel UX lives in one place (the context).
 *
 * Detection is a simple heuristic, not medical-grade fall detection — a
 * deliberately conservative false-positive rate matters more than
 * sophistication here, since a worker mid-task will trigger the "are you
 * okay?" prompt occasionally and just dismiss it.
 */

const SAMPLE_HZ = 2; // ~2 samples/sec is plenty for "is this phone moving at all"
const STILLNESS_MAGNITUDE_DELTA = 0.03; // g; below this, treat the sample as "no movement"
const FALL_SPIKE_G = 2.2; // g; a sudden jolt/impact
const POST_FALL_STILL_SAMPLES = 4; // ~2s of stillness right after a spike looks like a fall, not a bump

export type DeadmanEvent = 'NO_MOTION' | 'FALL_DETECTED';

export interface DeadmanServiceOptions {
  noMotionMinutes: number; // how long of continuous stillness before firing NO_MOTION
  onEvent: (event: DeadmanEvent) => void;
}

class DeadManSwitchService {
  private sub: Subscription | null = null;
  private lastMagnitude: number | null = null;
  private stillSince: number | null = null;
  private noMotionFired = false;
  private postSpikeStillCount = 0;
  private awaitingFallConfirmation = false;
  private options: DeadmanServiceOptions | null = null;

  start(options: DeadmanServiceOptions) {
    this.stop();
    this.options = options;
    this.lastMagnitude = null;
    this.stillSince = null;
    this.noMotionFired = false;
    this.postSpikeStillCount = 0;
    this.awaitingFallConfirmation = false;

    Accelerometer.setUpdateInterval(Math.round(1000 / SAMPLE_HZ));
    this.sub = Accelerometer.addListener(({ x, y, z }) => {
      const magnitude = Math.sqrt(x * x + y * y + z * z); // ~1.0g at rest
      this.handleSample(magnitude);
    });
  }

  stop() {
    this.sub?.remove();
    this.sub = null;
  }

  /** Call when the worker interacts with the app / dismisses a prompt — resets the stillness clock. */
  resetActivity() {
    this.stillSince = null;
    this.noMotionFired = false;
    this.lastMagnitude = null;
    this.awaitingFallConfirmation = false;
    this.postSpikeStillCount = 0;
  }

  private handleSample(magnitude: number) {
    if (!this.options) return;
    const now = Date.now();

    // --- Fall heuristic: sudden spike, then stillness ---
    if (this.awaitingFallConfirmation) {
      const delta = this.lastMagnitude == null ? 0 : Math.abs(magnitude - this.lastMagnitude);
      if (delta < STILLNESS_MAGNITUDE_DELTA) {
        this.postSpikeStillCount += 1;
        if (this.postSpikeStillCount >= POST_FALL_STILL_SAMPLES) {
          this.awaitingFallConfirmation = false;
          this.postSpikeStillCount = 0;
          this.options.onEvent('FALL_DETECTED');
        }
      } else {
        // kept moving after the spike — probably just set the phone down hard, not a fall
        this.awaitingFallConfirmation = false;
        this.postSpikeStillCount = 0;
      }
    } else if (magnitude >= FALL_SPIKE_G) {
      this.awaitingFallConfirmation = true;
      this.postSpikeStillCount = 0;
    }

    // --- No-motion heuristic: continuous stillness for N minutes ---
    const delta = this.lastMagnitude == null ? 1 : Math.abs(magnitude - this.lastMagnitude);
    if (delta < STILLNESS_MAGNITUDE_DELTA) {
      if (this.stillSince == null) this.stillSince = now;
      const stillMs = now - this.stillSince;
      if (!this.noMotionFired && stillMs >= this.options.noMotionMinutes * 60_000) {
        this.noMotionFired = true;
        this.options.onEvent('NO_MOTION');
      }
    } else {
      this.stillSince = now;
      this.noMotionFired = false;
    }

    this.lastMagnitude = magnitude;
  }
}

export const deadManSwitchService = new DeadManSwitchService();
