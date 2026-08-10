/**
 * ASTRA — Platform Abstraction Types
 *
 * The core application NEVER imports browser APIs directly.
 * All platform-specific capabilities (audio, notifications, window
 * management, system interaction) go through this interface.
 *
 * When ASTRA moves to a desktop runtime (Electron, Tauri),
 * only the platform adapter implementation changes — not the core.
 */

/** Audio input stream abstraction — wraps browser MediaStream or desktop equivalent */
export interface AudioInputStream {
  /** Start capturing audio */
  start(): void;
  /** Stop capturing audio */
  stop(): void;
  /** Whether the stream is currently active */
  readonly active: boolean;
  /** Subscribe to audio data chunks */
  onData(callback: (data: Float32Array) => void): void;
  /** Clean up resources */
  destroy(): void;
}

export interface PlatformAudio {
  /** Request permission to access the microphone */
  requestMicrophoneAccess(): Promise<boolean>;
  /** Create an audio input stream from the default microphone */
  createAudioStream(): Promise<AudioInputStream | null>;
  /** Play audio from raw data */
  playAudio(data: ArrayBuffer): Promise<void>;
  /** Stop any currently playing audio */
  stopAudio(): void;
}

export interface PlatformNotifications {
  /** Request notification permission */
  requestPermission(): Promise<boolean>;
  /** Show a system notification */
  show(title: string, body: string): void;
}

export interface PlatformWindow {
  /** Check if window is in always-on-top mode */
  isAlwaysOnTop(): boolean;
  /** Set always-on-top mode (desktop only) */
  setAlwaysOnTop(value: boolean): void;
  /** Minimize the window */
  minimize(): void;
  /** Set window dimensions */
  setSize(width: number, height: number): void;
  /** Get current display mode */
  getDisplayMode(): DisplayMode;
}

export interface PlatformSystem {
  /** Get the current platform name */
  getPlatformName(): PlatformName;
  /** Open a URL in the system browser */
  openExternal(url: string): void;
  /** Read text from system clipboard */
  getClipboardText(): Promise<string>;
  /** Write text to system clipboard */
  setClipboardText(text: string): Promise<void>;
}

/** Complete platform adapter interface */
export interface PlatformAdapter {
  readonly audio: PlatformAudio;
  readonly notifications: PlatformNotifications;
  readonly window: PlatformWindow;
  readonly system: PlatformSystem;
}

export type PlatformName = 'browser' | 'electron' | 'tauri' | 'unknown';
export type DisplayMode = 'fullscreen' | 'windowed' | 'notch' | 'overlay';
