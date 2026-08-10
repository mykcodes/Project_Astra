/**
 * ASTRA — Feature Flags
 *
 * Controls which features are enabled at runtime.
 * Read from environment variables; all default to false.
 */

export const features = {
  voice: import.meta.env.VITE_FEATURE_VOICE === 'true',
  memory: import.meta.env.VITE_FEATURE_MEMORY === 'true',
  knowledge: import.meta.env.VITE_FEATURE_KNOWLEDGE === 'true',
  tools: import.meta.env.VITE_FEATURE_TOOLS === 'true',
  agents: import.meta.env.VITE_FEATURE_AGENTS === 'true',
  notch: import.meta.env.VITE_FEATURE_NOTCH === 'true',
  chat: import.meta.env.VITE_FEATURE_CHAT === 'true',
} as const;

export type FeatureFlag = keyof typeof features;

/** Check if a feature is enabled */
export function isFeatureEnabled(flag: FeatureFlag): boolean {
  return features[flag];
}
