/**
 * ASTRA — Health Check API
 */

import { apiRequest } from './client.ts';
import type { HealthResponse } from '@/types/system.ts';

/** Check backend health */
export async function checkHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>('/api/health');
}
