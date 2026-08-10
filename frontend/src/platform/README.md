# Platform Abstraction Layer

## Purpose

The `platform/` module ensures the ASTRA core never directly imports browser APIs such as `navigator.mediaDevices`, `Notification`, or `window.open`.

All platform-specific capabilities — audio, notifications, window management, system interaction — are accessed through the `PlatformAdapter` interface.

## Why This Matters

ASTRA is designed to eventually run as a desktop application (Electron, Tauri) and potentially as a system-level notch interface. If core components directly imported browser APIs:

- Desktop builds would require polyfills or conditional checks everywhere
- The notch/overlay interface would be impossible without major refactoring
- Testing would require mocking dozens of browser globals

With this abstraction, moving to a desktop runtime means implementing one new adapter file. Nothing else changes.

## Structure

- `types.ts` — `PlatformAdapter` interface and sub-interfaces
- `browser.ts` — Browser implementation using Web APIs
- `index.ts` — Platform detection and adapter export

## Future Adapters

- `electron.ts` — Uses Electron IPC for native audio, window control, system tray
- `tauri.ts` — Uses Tauri commands for native capabilities

## Rules

1. **Core components import from `@/platform`, never from browser globals**
2. Only `platform/*.ts` files may use `navigator`, `Notification`, `window.*`
3. New platform capabilities are added to the interface first, then implemented per adapter
