/**
 * Engine-running detector from the phone accelerometer (phone mounted in the cab).
 * A running diesel shakes the cab at the firing frequency and its harmonics (4-cyl at idle
 * ≈ 27 Hz, at 2000 rpm ≈ 67 Hz); an engine-off machine is still apart from people moving.
 * Gravity and slow tilts are removed with a per-axis moving average; the RMS of the rest over
 * 2-second windows is compared with an adaptive noise floor, with hysteresis in time.
 * The estimate is always calibrated against dashboard readings on the server.
 */
export class EngineDetector {
  private ema = [0, 0, 0];
  private init = false;
  private sumSq = 0;
  private n = 0;
  private winStart = 0;
  private history: number[] = [];
  private aboveSince: number | null = null;
  private belowSince: number | null = null;
  running = false;
  lastRms = 0;
  onChange?: (running: boolean, t: number) => void;

  sample(ax: number, ay: number, az: number, t: number) {
    const a = 0.12; // ~0.5 s time constant at 60 Hz
    if (!this.init) {
      this.ema = [ax, ay, az];
      this.init = true;
      this.winStart = t;
    }
    const v = [ax, ay, az].map((x, i) => {
      this.ema[i] += a * (x - this.ema[i]);
      return x - this.ema[i];
    });
    this.sumSq += v[0] ** 2 + v[1] ** 2 + v[2] ** 2;
    this.n++;
    if (t - this.winStart >= 2000) this.window(t);
  }

  private window(t: number) {
    const rms = Math.sqrt(this.sumSq / Math.max(1, this.n));
    this.sumSq = 0;
    this.n = 0;
    this.winStart = t;
    this.lastRms = rms;
    this.history.push(rms);
    if (this.history.length > 1800) this.history.shift(); // last hour
    const sorted = [...this.history].sort((x, y) => x - y);
    const floor = sorted[Math.floor(sorted.length * 0.1)] ?? rms;
    const on = Math.max(0.03, floor * 4);
    const off = Math.max(0.02, floor * 2.5);
    if (rms >= on) {
      this.belowSince = null;
      this.aboveSince ??= t;
      if (!this.running && t - this.aboveSince >= 10_000) this.set(true, this.aboveSince);
    } else if (rms < off) {
      this.aboveSince = null;
      this.belowSince ??= t;
      if (this.running && t - this.belowSince >= 30_000) this.set(false, this.belowSince);
    }
  }

  private set(r: boolean, t: number) {
    this.running = r;
    this.onChange?.(r, t);
  }
}
