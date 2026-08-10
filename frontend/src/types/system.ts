/**
 * ASTRA — System Types
 */

export enum ConnectionState {
  CONNECTED = 'connected',
  DISCONNECTED = 'disconnected',
  RECONNECTING = 'reconnecting',
}

export interface SystemStatus {
  connection: ConnectionState;
  backendVersion?: string;
  databaseConnected?: boolean;
  uptime?: number;
}

export interface HealthResponse {
  status: string;
  version: string;
  environment: string;
  uptime: number;
}
