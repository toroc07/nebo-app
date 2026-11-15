// Sound for the interface, synthesised with the Web Audio API so there are no files to ship or
// license. Every sound is a short envelope over an oscillator or filtered noise.
//
// Rules the module enforces for the whole app:
//  - Nothing plays before the first user gesture (browsers block it and warn otherwise).
//  - Muted is the saved preference; `prefers-reduced-motion` does not mute, but the ambient
//    music stays off unless the visitor turns sound on explicitly.
//  - Sounds are fire-and-forget: if audio is unavailable every call is a silent no-op.
//
// Optional samples: if `public/audio/ambient.mp3` exists it replaces the synthesised pad.

const STORAGE_KEY = "nebo.audio";
const MASTER_GAIN = 1;
const MUSIC_GAIN = 0.6;

type Saved = { muted: boolean };

let ctx: AudioContext | null = null;
let master: GainNode | null = null;
let muted = true; // Off until the visitor opts in: autoplay with sound is hostile.
let loaded = false;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((fn) => fn());
}

function load() {
  if (loaded || typeof window === "undefined") return;
  loaded = true;
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null") as Saved | null;
    if (saved) muted = saved.muted === true;
  } catch {
    /* Storage can be disabled; the default applies for this session. */
  }
}

function save() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ muted } satisfies Saved));
  } catch {
    /* Ignored: the choice still holds until the page closes. */
  }
}

/** The audio graph, created lazily from a user gesture. Null when unsupported or muted. */
function engine(): { ctx: AudioContext; out: GainNode } | null {
  load();
  if (muted || typeof window === "undefined") return null;
  if (!ctx) {
    const Ctor =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return null;
    ctx = new Ctor();
    master = ctx.createGain();
    master.gain.value = MASTER_GAIN;
    // A limiter at the end: the tunnel, the music and a click can overlap without distorting.
    const limiter = ctx.createDynamicsCompressor();
    limiter.threshold.value = -12;
    limiter.knee.value = 10;
    limiter.ratio.value = 8;
    master.connect(limiter).connect(ctx.destination);
  }
  if (ctx.state === "suspended") void ctx.resume();
  return master ? { ctx, out: master } : null;
}

/** A tone with a fast attack and an exponential decay: the base of every click and bleep. */
function tone(
  freq: number,
  duration: number,
  { type = "sine", gain = 0.2, slideTo, delay = 0 }: {
    type?: OscillatorType;
    gain?: number;
    slideTo?: number;
    delay?: number;
  } = {},
) {
  const e = engine();
  if (!e) return;
  const t0 = e.ctx.currentTime + delay;
  const osc = e.ctx.createOscillator();
  const amp = e.ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t0);
  if (slideTo) osc.frequency.exponentialRampToValueAtTime(slideTo, t0 + duration);
  amp.gain.setValueAtTime(0.0001, t0);
  amp.gain.exponentialRampToValueAtTime(gain, t0 + 0.006);
  amp.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);
  osc.connect(amp).connect(e.out);
  osc.start(t0);
  osc.stop(t0 + duration + 0.02);
}

/** One shared buffer of white noise, reused by every whoosh. */
let noiseBuffer: AudioBuffer | null = null;
function noise(c: AudioContext): AudioBuffer {
  if (!noiseBuffer) {
    noiseBuffer = c.createBuffer(1, c.sampleRate * 2, c.sampleRate);
    const data = noiseBuffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
  }
  return noiseBuffer;
}

// ---- UI sounds ---------------------------------------------------------------------------

/** A burst of filtered noise that sweeps in frequency: whooshes, risers and impacts. */
function sweep(
  from: number,
  to: number,
  duration: number,
  { gain = 0.5, type = "bandpass", delay = 0, attack = 0.02 }: {
    gain?: number;
    type?: BiquadFilterType;
    delay?: number;
    attack?: number;
  } = {},
) {
  const e = engine();
  if (!e) return;
  const t0 = e.ctx.currentTime + delay;
  const src = e.ctx.createBufferSource();
  src.buffer = noise(e.ctx);
  const filter = e.ctx.createBiquadFilter();
  filter.type = type;
  filter.Q.value = 1.2;
  filter.frequency.setValueAtTime(from, t0);
  filter.frequency.exponentialRampToValueAtTime(to, t0 + duration);
  const amp = e.ctx.createGain();
  amp.gain.setValueAtTime(0.0001, t0);
  amp.gain.exponentialRampToValueAtTime(gain, t0 + attack);
  amp.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);
  src.connect(filter).connect(amp).connect(e.out);
  src.start(t0, Math.random());
  src.stop(t0 + duration + 0.05);
}

export const sfx = {
  /** Pointer enters a control: light, so a sweep across a toolbar is not noisy. */
  hover: () => tone(1900, 0.05, { type: "sine", gain: 0.1 }),
  /** Press on a button or control. */
  click: () => {
    tone(900, 0.09, { type: "square", gain: 0.2, slideTo: 560 });
    tone(1600, 0.07, { type: "sine", gain: 0.25, delay: 0.012 });
  },
  /** A switch or toggle changes state. */
  toggle: (on: boolean) =>
    tone(on ? 700 : 520, 0.12, { type: "triangle", gain: 0.3, slideTo: on ? 1100 : 340 }),
  /** Screen powers on: a rising chirp with a bright second note. */
  powerOn: () => {
    tone(320, 0.22, { type: "sawtooth", gain: 0.2, slideTo: 960 });
    tone(1320, 0.18, { type: "sine", gain: 0.25, delay: 0.18 });
  },
  /** Screen powers off: the same gesture, falling. */
  powerOff: () => {
    tone(960, 0.28, { type: "sawtooth", gain: 0.2, slideTo: 160 });
    sweep(3000, 300, 0.3, { gain: 0.2 });
  },
  /**
   * One step of the blink comparator. The pitch follows the epoch so the ear can track which
   * image is on screen, and it stays within one octave to avoid fatigue at fast blink speeds.
   */
  blink: (epoch: number, count: number) => {
    const span = Math.max(count - 1, 1);
    const freq = 520 * Math.pow(2, Math.min(epoch, span) / span);
    tone(freq, 0.08, { type: "triangle", gain: 0.3 });
    tone(freq * 2, 0.05, { type: "sine", gain: 0.12 });
  },
  /** A line of the boot checklist appearing. */
  tick: () => {
    tone(1400, 0.05, { type: "square", gain: 0.12 });
    tone(2100, 0.04, { type: "sine", gain: 0.16, delay: 0.03 });
  },
  /** A data chirp while something loads: varies a little so it reads as activity, not a beep. */
  data: () => tone(900 + Math.random() * 900, 0.06, { type: "square", gain: 0.1 }),
  /** Success: system ready, field loaded. A rising major arpeggio. */
  chime: () =>
    [660, 880, 1320].forEach((f, i) =>
      tone(f, 0.28, { type: "sine", gain: 0.3, delay: i * 0.09 }),
    ),
  /** Something failed: two low, flat pulses. */
  error: () => {
    tone(180, 0.16, { type: "sawtooth", gain: 0.25 });
    tone(150, 0.2, { type: "sawtooth", gain: 0.25, delay: 0.19 });
  },
  /** A chat message sent and received. */
  send: () => tone(700, 0.1, { type: "triangle", gain: 0.25, slideTo: 1200 }),
  receive: () => {
    tone(1000, 0.1, { type: "sine", gain: 0.28 });
    tone(1500, 0.14, { type: "sine", gain: 0.26, delay: 0.09 });
  },
  /** The camera turns between cockpit and analysis screen. */
  swoosh: () => {
    sweep(300, 2800, 0.7, { gain: 0.6, attack: 0.25 });
    tone(90, 0.6, { type: "sine", gain: 0.3, slideTo: 45 });
  },
  /** Engines spooling up at the start of the jump. */
  charge: () => {
    sweep(120, 3500, 1.4, { gain: 0.7, attack: 1.1 });
    tone(55, 1.4, { type: "sawtooth", gain: 0.3, slideTo: 220 });
  },
  /** Arrival: the tunnel drops out and the sky appears. */
  impact: () => {
    tone(120, 0.7, { type: "sine", gain: 0.7, slideTo: 38 });
    sweep(4000, 200, 0.9, { gain: 0.6 });
    [880, 1320, 1760].forEach((f, i) => tone(f, 0.5, { type: "sine", gain: 0.18, delay: 0.25 + i * 0.1 }));
  },
};

// ---- Tunnel ------------------------------------------------------------------------------

type Whoosh = { setSpeed: (speed: number) => void; stop: () => void };
const SILENT_WHOOSH: Whoosh = { setSpeed: () => {}, stop: () => {} };

/**
 * The hyperspace tunnel: filtered noise plus a low rumble whose pitch and brightness follow the
 * warp speed (0..1) that the animation already computes every frame. Returns a handle to drive
 * and end it; if audio is off the handle does nothing.
 */
export function startWhoosh(): Whoosh {
  const e = engine();
  if (!e) return SILENT_WHOOSH;
  const { ctx: c, out } = e;
  const src = c.createBufferSource();
  src.buffer = noise(c);
  src.loop = true;
  const band = c.createBiquadFilter();
  band.type = "bandpass";
  band.Q.value = 0.8;
  band.frequency.value = 200;
  const rumble = c.createOscillator();
  rumble.type = "sawtooth";
  rumble.frequency.value = 40;
  const rumbleGain = c.createGain();
  rumbleGain.gain.value = 0.0;
  const amp = c.createGain();
  amp.gain.value = 0.0001;
  src.connect(band).connect(amp);
  rumble.connect(rumbleGain).connect(amp);
  amp.connect(out);
  src.start();
  rumble.start();

  let stopped = false;
  return {
    setSpeed(speed) {
      if (stopped) return;
      const t = c.currentTime;
      // Short ramps hide the 60 Hz stair-stepping of the animation frames.
      band.frequency.linearRampToValueAtTime(200 + speed * 3800, t + 0.08);
      amp.gain.linearRampToValueAtTime(0.0001 + speed * 1.0, t + 0.08);
      rumble.frequency.linearRampToValueAtTime(40 + speed * 70, t + 0.08);
      rumbleGain.gain.linearRampToValueAtTime(speed * 0.7, t + 0.08);
    },
    stop() {
      if (stopped) return;
      stopped = true;
      const t = c.currentTime;
      amp.gain.cancelScheduledValues(t);
      amp.gain.setValueAtTime(amp.gain.value, t);
      amp.gain.linearRampToValueAtTime(0.0001, t + 0.4);
      src.stop(t + 0.45);
      rumble.stop(t + 0.45);
    },
  };
}

// ---- Music -------------------------------------------------------------------------------

let music: { stop: () => void } | null = null;

/** A slow, detuned pad on a minor chord with a long filter sweep: deep-space ambience. */
function startPad(c: AudioContext, out: GainNode): { stop: () => void } {
  const bus = c.createGain();
  bus.gain.value = 0.0001;
  bus.gain.linearRampToValueAtTime(MUSIC_GAIN, c.currentTime + 4);
  const lowpass = c.createBiquadFilter();
  lowpass.type = "lowpass";
  lowpass.frequency.value = 700;
  lowpass.Q.value = 2;
  // The filter drifts open and closed over ~20 s so the pad never sits still.
  const lfo = c.createOscillator();
  const lfoDepth = c.createGain();
  lfo.frequency.value = 0.05;
  lfoDepth.gain.value = 450;
  lfo.connect(lfoDepth).connect(lowpass.frequency);
  bus.connect(lowpass).connect(out);
  lfo.start();

  const notes = [55, 82.41, 110, 130.81, 164.81]; // A1 E2 A2 C3 E3
  const oscillators: OscillatorNode[] = [lfo];
  for (const f of notes) {
    for (const detune of [-7, 7]) {
      const o = c.createOscillator();
      o.type = "sawtooth";
      o.frequency.value = f;
      o.detune.value = detune;
      const g = c.createGain();
      g.gain.value = 0.05;
      o.connect(g).connect(bus);
      o.start();
      oscillators.push(o);
    }
  }
  return {
    stop() {
      const t = c.currentTime;
      bus.gain.cancelScheduledValues(t);
      bus.gain.setValueAtTime(bus.gain.value, t);
      bus.gain.linearRampToValueAtTime(0.0001, t + 1.5);
      oscillators.forEach((o) => o.stop(t + 1.6));
    },
  };
}

/** Plays `public/audio/ambient.mp3` in a loop when it exists, else the synthesised pad. */
async function startMusic() {
  if (music) return;
  const e = engine();
  if (!e) return;
  // Reserve the slot first so two quick calls cannot start two layers.
  music = { stop: () => {} };
  try {
    const res = await fetch("/audio/ambient.mp3");
    if (!res.ok || !(res.headers.get("content-type") || "").includes("audio")) throw new Error();
    const buffer = await e.ctx.decodeAudioData(await res.arrayBuffer());
    const src = e.ctx.createBufferSource();
    const gain = e.ctx.createGain();
    src.buffer = buffer;
    src.loop = true;
    gain.gain.value = MUSIC_GAIN * 2;
    src.connect(gain).connect(e.out);
    src.start();
    music = { stop: () => src.stop(e.ctx.currentTime + 0.1) };
  } catch {
    music = startPad(e.ctx, e.out);
  }
}

function stopMusic() {
  music?.stop();
  music = null;
}

// ---- Mute control ------------------------------------------------------------------------

export const audio = {
  isMuted(): boolean {
    load();
    return muted;
  },
  /** Must be called from a user gesture (a click on the sound button) to be allowed to play. */
  setMuted(next: boolean) {
    load();
    muted = next;
    save();
    if (muted) {
      stopMusic();
      void ctx?.suspend();
    } else {
      void startMusic();
      sfx.powerOn();
    }
    emit();
  },
  toggle() {
    this.setMuted(!this.isMuted());
  },
  /** First gesture of a visit: a visitor who left sound on gets the music back without a click. */
  unlock() {
    if (!this.isMuted()) void startMusic();
  },
  subscribe(fn: () => void): () => void {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
};
