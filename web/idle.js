// Demo (attract) mode timer: starts after IDLE_SECONDS without input. Frames longer than MAX_FRAME_SECONDS
// (tab switch, shader warm-up, a replay or policy download) do not count as idle time. Tested by web/idle.test.mjs.
export const IDLE_SECONDS = 30;
export const MAX_FRAME_SECONDS = 0.25;
export const DWELL_SECONDS = 8; // each replay / camera stays this long in demo mode

export class IdleTimer {
  constructor(threshold = IDLE_SECONDS, maxFrame = MAX_FRAME_SECONDS) {
    this.threshold = threshold;
    this.maxFrame = maxFrame;
    this.idle = 0;
    this.active = false;
  }

  /** Any input: back to manual control. Returns true when this ended demo mode. */
  input() {
    const was = this.active;
    this.idle = 0;
    this.active = false;
    return was;
  }

  /** Advance by one frame of dt seconds. Returns true on the frame demo mode starts. */
  tick(dt) {
    if (dt > 0 && dt <= this.maxFrame) this.idle += dt;
    if (!this.active && this.idle >= this.threshold) {
      this.active = true;
      return true;
    }
    return false;
  }
}
