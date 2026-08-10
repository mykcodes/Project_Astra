/**
 * ASTRA — Central Configuration
 *
 * Reads from Vite environment variables (import.meta.env).
 * All config access goes through this module.
 */

export const config = {
  /** Application name */
  appName: import.meta.env.VITE_APP_NAME ?? 'ASTRA',

  /** Backend API base URL */
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? '',

  /** Current environment */
  env: import.meta.env.VITE_ENV ?? 'development',

  /** Debug mode */
  debug: import.meta.env.VITE_DEBUG === 'true',
} as const;
