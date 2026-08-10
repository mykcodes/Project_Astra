/**
 * ASTRA — Browser Platform Adapter
 *
 * Browser implementation of PlatformAdapter.
 * Uses Web APIs (navigator, Notification, window).
 * Desktop-only features are no-ops that log warnings.
 */

import type {
  PlatformAdapter,
  PlatformAudio,
  PlatformNotifications,
  PlatformWindow,
  PlatformSystem,
  AudioInputStream,
  DisplayMode,
} from './types.ts';

// ============================================================
// Audio
// ============================================================

class BrowserAudioInputStream implements AudioInputStream {
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;
  private dataCallback: ((data: Float32Array) => void) | null = null;
  private _active = false;

  constructor(stream: MediaStream) {
    this.stream = stream;
  }

  get active(): boolean {
    return this._active;
  }

  start(): void {
    if (!this.stream) return;

    this.context = new AudioContext();
    const source = this.context.createMediaStreamSource(this.stream);
    // ScriptProcessorNode is deprecated but widely supported.
    // Future: migrate to AudioWorklet when implementing real voice.
    this.processor = this.context.createScriptProcessor(4096, 1, 1);

    this.processor.onaudioprocess = (event: AudioProcessingEvent) => {
      if (this.dataCallback) {
        const inputData = event.inputBuffer.getChannelData(0);
        this.dataCallback(new Float32Array(inputData));
      }
    };

    source.connect(this.processor);
    this.processor.connect(this.context.destination);
    this._active = true;
  }

  stop(): void {
    this.processor?.disconnect();
    this.context?.close();
    this._active = false;
  }

  onData(callback: (data: Float32Array) => void): void {
    this.dataCallback = callback;
  }

  destroy(): void {
    this.stop();
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.processor = null;
    this.context = null;
    this.dataCallback = null;
  }
}

const browserAudio: PlatformAudio = {
  async requestMicrophoneAccess(): Promise<boolean> {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
      return true;
    } catch {
      return false;
    }
  },

  async createAudioStream(): Promise<AudioInputStream | null> {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: 16000,
        },
      });
      return new BrowserAudioInputStream(stream);
    } catch {
      return null;
    }
  },

  async playAudio(data: ArrayBuffer): Promise<void> {
    const context = new AudioContext();
    const buffer = await context.decodeAudioData(data);
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    source.start(0);
  },

  stopAudio(): void {
    // Future: track active audio sources for cancellation
  },
};

// ============================================================
// Notifications
// ============================================================

const browserNotifications: PlatformNotifications = {
  async requestPermission(): Promise<boolean> {
    if (!('Notification' in window)) return false;
    const result = await Notification.requestPermission();
    return result === 'granted';
  },

  show(title: string, body: string): void {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification(title, { body });
    }
  },
};

// ============================================================
// Window (limited in browser)
// ============================================================

const browserWindow: PlatformWindow = {
  isAlwaysOnTop(): boolean {
    return false; // Not possible in browser
  },

  setAlwaysOnTop(_value: boolean): void {
    console.warn('[Platform] setAlwaysOnTop is not available in browser mode');
  },

  minimize(): void {
    console.warn('[Platform] minimize is not available in browser mode');
  },

  setSize(_width: number, _height: number): void {
    console.warn('[Platform] setSize is not available in browser mode');
  },

  getDisplayMode(): DisplayMode {
    return 'windowed';
  },
};

// ============================================================
// System
// ============================================================

const browserSystem: PlatformSystem = {
  getPlatformName() {
    return 'browser' as const;
  },

  openExternal(url: string): void {
    window.open(url, '_blank', 'noopener,noreferrer');
  },

  async getClipboardText(): Promise<string> {
    try {
      return await navigator.clipboard.readText();
    } catch {
      return '';
    }
  },

  async setClipboardText(text: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      console.warn('[Platform] Failed to write to clipboard');
    }
  },
};

// ============================================================
// Adapter
// ============================================================

export const browserPlatform: PlatformAdapter = {
  audio: browserAudio,
  notifications: browserNotifications,
  window: browserWindow,
  system: browserSystem,
};
