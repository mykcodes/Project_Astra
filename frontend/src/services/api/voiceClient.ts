/**
 * ASTRA - Voice API Client
 * 
 * Handles API calls to the backend voice and conversation services.
 */

const API_BASE = '/api';

export interface TranscriptionOptions {
  clientTimestampMs?: number;
  durationMs?: number;
  utteranceId?: string;
  sessionId?: string;
}

export interface MessageOptions {
  utteranceId?: string;
  alignedObservationId?: string | null;
  sessionId?: string;
}

export class VoiceClient {
  public lastUtteranceId: string | null = null;
  public lastAlignedObservationId: string | null = null;

  /**
   * Upload audio blob for transcription.
   */
  async transcribeAudio(audioBlob: Blob, options?: TranscriptionOptions): Promise<string> {
    const formData = new FormData();
    formData.append('audio', audioBlob, 'audio.webm'); // Default to webm for MediaRecorder

    const uttId = options?.utteranceId || (typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID().slice(0, 8) : Math.random().toString(36).substring(2, 10));
    formData.append('utterance_id', uttId);

    const onsetMs = options?.clientTimestampMs || Date.now();
    formData.append('client_timestamp_ms', onsetMs.toString());

    if (options?.durationMs !== undefined) {
      formData.append('client_duration_ms', options.durationMs.toString());
    }
    if (options?.sessionId) {
      formData.append('session_id', options.sessionId);
    }
    formData.append('clock_domain', 'CLIENT_WALL_CLOCK_UTC_MS');

    const response = await fetch(`${API_BASE}/voice/transcribe`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Transcription failed: ${response.statusText}`);
    }

    const data = await response.json();
    this.lastUtteranceId = data.utterance_id || uttId;
    this.lastAlignedObservationId = data.aligned_observation_id || null;

    return data.text;
  }

  /**
   * Send a message to the AI conversation orchestrator (synchronous).
   */
  async sendMessage(text: string, options?: MessageOptions): Promise<string> {
    const alignedObsId = options?.alignedObservationId !== undefined 
      ? options.alignedObservationId 
      : this.lastAlignedObservationId;

    const payload: Record<string, any> = { text };
    if (alignedObsId) {
      payload.aligned_observation_id = alignedObsId;
    }
    const uttId = options?.utteranceId || this.lastUtteranceId;
    if (uttId) {
      payload.utterance_id = uttId;
    }

    const response = await fetch(`${API_BASE}/conversation/message`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`Message failed: ${response.statusText}`);
    }

    const data = await response.json();
    return data.text;
  }

  /**
   * Send a message to the AI conversation orchestrator (streaming).
   */
  async streamMessage(text: string, onEvent: (event: any) => void): Promise<void> {
    const response = await fetch(`${API_BASE}/conversation/message/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ text }),
    });

    if (!response.ok) {
      throw new Error(`Message stream failed: ${response.statusText}`);
    }

    if (!response.body) {
      throw new Error('Response body is null');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) {
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.trim()) {
            try {
              const event = JSON.parse(line);
              onEvent(event);
            } catch (e) {
              console.error('Failed to parse SSE JSON:', line, e);
            }
          }
        }
      }
    }
    
    if (buffer.trim()) {
      try {
        const event = JSON.parse(buffer);
        onEvent(event);
      } catch (e) {
        console.error('Failed to parse SSE JSON (end):', buffer, e);
      }
    }
  }

  /**
   * Synthesize text into speech audio.
   */
  async synthesizeSpeech(text: string): Promise<Blob> {
    const response = await fetch(`${API_BASE}/voice/synthesize`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ text }),
    });

    if (!response.ok) {
      throw new Error(`Synthesis failed: ${response.statusText}`);
    }

    return await response.blob();
  }

  /**
   * Cancel currently running goal or action execution.
   */
  async cancelExecution(): Promise<boolean> {
    try {
      const response = await fetch(`${API_BASE}/conversation/cancel`, {
        method: 'POST',
      });
      if (!response.ok) return false;
      const data = await response.json();
      return Boolean(data.cancelled);
    } catch {
      return false;
    }
  }

  /**
   * Fetch all resumable goals.
   */
  async listResumableGoals(): Promise<any[]> {
    try {
      const response = await fetch(`${API_BASE}/conversation/goals/resumable`);
      if (!response.ok) return [];
      const data = await response.json();
      return data.goals || [];
    } catch {
      return [];
    }
  }

  /**
   * Resume an interrupted or suspended goal from its checkpoint (streaming).
   */
  async resumeGoal(goalId: string, onEvent: (event: any) => void): Promise<void> {
    const response = await fetch(`${API_BASE}/conversation/goals/${encodeURIComponent(goalId)}/resume`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Resume failed: ${response.statusText}`);
    }

    if (!response.body) {
      throw new Error('Response body is null');
    }

    await this._readSSEStream(response.body, onEvent);
  }

  /**
   * Submit clarification response for ambiguous target or missing parameter (streaming).
   */
  async clarifyTarget(
    requestId: string,
    selectedOptionId?: string,
    customInput?: string,
    rememberAsPreference?: boolean,
    onEvent?: (event: any) => void
  ): Promise<void> {
    const response = await fetch(`${API_BASE}/conversation/clarify`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        request_id: requestId,
        selected_option_id: selectedOptionId,
        custom_input: customInput,
        remember_as_preference: Boolean(rememberAsPreference),
      }),
    });

    if (!response.ok) {
      throw new Error(`Clarification failed: ${response.statusText}`);
    }

    if (!response.body) {
      throw new Error('Response body is null');
    }

    await this._readSSEStream(response.body, onEvent);
  }

  /**
   * Submit authorization or rejection for consequential action (streaming).
   */
  async confirmAction(
    requestId: string,
    confirmed: boolean,
    onEvent?: (event: any) => void
  ): Promise<void> {
    const response = await fetch(`${API_BASE}/conversation/confirm`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        request_id: requestId,
        confirmed,
      }),
    });

    if (!response.ok) {
      throw new Error(`Confirmation failed: ${response.statusText}`);
    }

    if (!response.body) {
      throw new Error('Response body is null');
    }

    await this._readSSEStream(response.body, onEvent);
  }

  private async _readSSEStream(body: ReadableStream<Uint8Array>, onEvent?: (event: any) => void): Promise<void> {
    const reader = body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) {
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.trim()) {
            try {
              const event = JSON.parse(line);
              if (onEvent) onEvent(event);
            } catch (e) {
              console.error('Failed to parse SSE JSON:', line, e);
            }
          }
        }
      }
    }

    if (buffer.trim()) {
      try {
        const event = JSON.parse(buffer);
        if (onEvent) onEvent(event);
      } catch (e) {
        console.error('Failed to parse SSE JSON (end):', buffer, e);
      }
    }
  }
}

export const voiceClient = new VoiceClient();
