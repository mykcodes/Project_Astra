/**
 * ASTRA — Platform Detection & Adapter Export
 *
 * Detects the current runtime environment and returns the
 * appropriate PlatformAdapter. Currently only browser is implemented.
 *
 * Future: detect Electron (window.electron), Tauri (window.__TAURI__),
 * and return the corresponding adapter.
 */

import type { PlatformAdapter, PlatformName } from './types.ts';
import { browserPlatform } from './browser.ts';

function detectPlatform(): PlatformName {
  // Future: check for desktop runtime globals
  // if (typeof window !== 'undefined' && 'electron' in window) return 'electron';
  // if (typeof window !== 'undefined' && '__TAURI__' in window) return 'tauri';
  return 'browser';
}

function createAdapter(platform: PlatformName): PlatformAdapter {
  switch (platform) {
    case 'browser':
      return browserPlatform;
    // Future:
    // case 'electron': return electronPlatform;
    // case 'tauri': return tauriPlatform;
    default:
      return browserPlatform;
  }
}

/** The detected platform name */
export const platformName = detectPlatform();

/** The platform adapter for the current runtime */
export const platform: PlatformAdapter = createAdapter(platformName);

export type { PlatformAdapter, PlatformName } from './types.ts';
