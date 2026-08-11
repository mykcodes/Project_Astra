/**
 * ASTRA - Audio Playback Service
 * 
 * Handles playing synthesized speech audio (TTS).
 */

export class AudioPlaybackService {
  private audio: HTMLAudioElement | null = null;
  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private animationFrameId: number | null = null;
  private sourceNode: MediaElementAudioSourceNode | null = null;

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

      // Initialize audio context on first play to ensure user interaction has occurred
      if (!this.audioContext) {
        this.audioContext = new AudioContext();
      }

      // Resume context if it was suspended (e.g., due to autoplay policies)
      if (this.audioContext.state === 'suspended') {
        this.audioContext.resume();
      }

      this.sourceNode = this.audioContext.createMediaElementSource(this.audio);
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 256;

      this.sourceNode.connect(this.analyser);
      this.analyser.connect(this.audioContext.destination);

      this.setupAudioAnalysis();

      this.audio.onended = () => {
        URL.revokeObjectURL(url);
        this.cleanupAnalysis();
        resolve();
      };

      this.audio.onerror = (e) => {
        URL.revokeObjectURL(url);
        this.cleanupAnalysis();
        console.error('Audio playback error', e);
        reject(new Error('Audio playback failed'));
      };

      this.audio.play().catch((e) => {
        URL.revokeObjectURL(url);
        this.cleanupAnalysis();
        console.error('Audio play blocked or failed', e);
        reject(e);
      });
    });
  }

  private setupAudioAnalysis() {
    if (!this.analyser) return;

    const bufferLength = this.analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    
    let currentLevel = 0;

    const analyze = () => {
      if (!this.analyser) return;
      this.analyser.getByteFrequencyData(dataArray);
      
      let sum = 0;
      for (let i = 0; i < bufferLength; i++) {
        sum += dataArray[i]!;
      }
      const average = sum / bufferLength;
      
      // Normalize roughly between 0.0 and 1.0
      const targetLevel = Math.min(1.0, average / 100);
      
      // Smooth the movement
      currentLevel += (targetLevel - currentLevel) * 0.2;
      
      document.documentElement.style.setProperty('--audio-level', currentLevel.toFixed(3));
      
      this.animationFrameId = requestAnimationFrame(analyze);
    };

    analyze();
  }

  private cleanupAnalysis() {
    if (this.animationFrameId !== null) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = null;
    }
    
    if (this.sourceNode) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }
    
    if (this.analyser) {
      this.analyser.disconnect();
      this.analyser = null;
    }

    document.documentElement.style.setProperty('--audio-level', '0');
  }

  /**
   * Stop current playback.
   */
  stop() {
    this.cleanupAnalysis();
    if (this.audio) {
      this.audio.pause();
      this.audio.currentTime = 0;
      this.audio = null;
    }
  }
}

// Singleton instance
export const audioPlaybackService = new AudioPlaybackService();
