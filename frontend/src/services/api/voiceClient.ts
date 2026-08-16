/**
 * ASTRA - Voice API Client
 * 
 * Handles API calls to the backend voice and conversation services.
 */

const API_BASE = '/api';

export class VoiceClient {
  /**
   * Upload audio blob for transcription.
   */
  async transcribeAudio(audioBlob: Blob): Promise<string> {
    const formData = new FormData();
    formData.append('audio', audioBlob, 'audio.webm'); // Default to webm for MediaRecorder

    const response = await fetch(`${API_BASE}/voice/transcribe`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Transcription failed: ${response.statusText}`);
    }

    const data = await response.json();
    return data.text;
  }

  /**
   * Send a message to the AI conversation orchestrator (synchronous).
   */
  async sendMessage(text: string): Promise<string> {
    const response = await fetch(`${API_BASE}/conversation/message`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ text }),
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
}

export const voiceClient = new VoiceClient();
