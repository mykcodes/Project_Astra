/**
 * ASTRA - Audio Playback Service
 * 
 * Handles playing synthesized speech audio (TTS).
 */

export class AudioPlaybackService {
  private audio: HTMLAudioElement | null = null;

  /**
   * Play an audio blob.
   * @param audioBlob The audio blob to play (e.g. MP3)
   * @returns A promise that resolves when playback is complete.
   */
  playAudioBlob(audioBlob: Blob): Promise<void> {
    return new Promise((resolve, reject) => {
      this.stop();

      const url = URL.createObjectURL(audioBlob);
      this.audio = new Audio(url);

      this.audio.onended = () => {
        URL.revokeObjectURL(url);
        resolve();
      };

      this.audio.onerror = (e) => {
        URL.revokeObjectURL(url);
        console.error('Audio playback error', e);
        reject(new Error('Audio playback failed'));
      };

      this.audio.play().catch((e) => {
        URL.revokeObjectURL(url);
        console.error('Audio play blocked or failed', e);
        reject(e);
      });
    });
  }

  /**
   * Stop current playback.
   */
  stop() {
    if (this.audio) {
      this.audio.pause();
      this.audio.currentTime = 0;
      this.audio = null;
    }
  }
}

// Singleton instance
export const audioPlaybackService = new AudioPlaybackService();
