/**
 * ASTRA — API Client
 *
 * Typed fetch wrapper with error normalization.
 * All backend communication goes through this client.
 */

import { config } from '@/config/index.ts';
import type { AppError } from '@/types/common.ts';

/** API request options */
interface RequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

/** Normalized API error */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  toAppError(): AppError {
    return {
      code: this.code,
      message: this.message,
      details: this.details,
      timestamp: new Date().toISOString(),
    };
  }
}

/**
 * Make a typed API request.
 *
 * @param path - API path (e.g., '/api/health')
 * @param options - Request options
 * @returns Parsed response body
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, headers = {}, signal } = options;

  const url = `${config.apiBaseUrl}${path}`;

  const requestHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    ...headers,
  };

  // Future: inject auth token here
  // const token = getAuthToken();
  // if (token) requestHeaders['Authorization'] = `Bearer ${token}`;

  const response = await fetch(url, {
    method,
    headers: requestHeaders,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });

  if (!response.ok) {
    let errorBody: Record<string, unknown> = {};
    try {
      errorBody = (await response.json()) as Record<string, unknown>;
    } catch {
      // Response body is not JSON
    }

    throw new ApiError(
      response.status,
      (errorBody['code'] as string) ?? `HTTP_${response.status}`,
      (errorBody['message'] as string) ?? response.statusText,
      errorBody['details'] as Record<string, unknown> | undefined,
    );
  }

  return (await response.json()) as T;
}
