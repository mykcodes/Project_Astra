/**
 * ASTRA — Common Types
 */

/** Standard API response wrapper */
export interface ApiResponse<T> {
  data: T;
  success: boolean;
  message?: string;
  timestamp: string;
}

/** Paginated API response */
export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
}

/** Normalized application error */
export interface AppError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  timestamp: string;
}

/** Unique identifier type */
export type ID = string;

/** ISO 8601 timestamp string */
export type Timestamp = string;
