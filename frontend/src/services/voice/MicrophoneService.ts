/**
 * ASTRA - Microphone Service
 * 
 * Handles capturing audio from the user's microphone using the MediaRecorder API.
 */

export class MicrophoneService {
  private mediaRecorder: MediaRecorder | null = null;
  private audioChunks: Blob[] = [];
  private stream: MediaStream | null = null;

  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private animationFrameId: number | null = null;

  /**
   * Request microphone permissions and start recording.
   */
  async startRecording(): Promise<void> {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.mediaRecorder = new MediaRecorder(this.stream);
      this.audioChunks = [];

      this.mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          this.audioChunks.push(event.data);
        }
      };

      this.setupAudioAnalysis(this.stream);
      this.mediaRecorder.start();
    } catch (error) {
      console.error('Failed to access microphone:', error);
      throw error;
    }
  }

  private setupAudioAnalysis(stream: MediaStream) {
    this.audioContext = new AudioContext();
    const source = this.audioContext.createMediaStreamSource(stream);
    this.analyser = this.audioContext.createAnalyser();
    
    this.analyser.fftSize = 256;
    source.connect(this.analyser);

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
      
      // Normalize roughly between 0.0 and 1.0 (max is 255, but average speech is much lower)
      const targetLevel = Math.min(1.0, average / 100);
      
      // Smooth the movement
      currentLevel += (targetLevel - currentLevel) * 0.2;
      
      document.documentElement.style.setProperty('--audio-level', currentLevel.toFixed(3));
      
      this.animationFrameId = requestAnimationFrame(analyze);
    };

    analyze();
  }

  /**
   * Stop recording and return the audio Blob.
   */
  stopRecording(): Promise<Blob> {
    return new Promise((resolve, reject) => {
      if (!this.mediaRecorder || this.mediaRecorder.state === 'inactive') {
        reject(new Error('Recorder is not active'));
        return;
      }

      this.mediaRecorder.onstop = () => {
        const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
        this.audioChunks = [];
        this.cleanup();
        resolve(audioBlob);
      };

      this.mediaRecorder.stop();
    });
  }

  private cleanup() {
    if (this.animationFrameId !== null) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = null;
    }
    
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
      this.analyser = null;
    }
    document.documentElement.style.setProperty('--audio-level', '0');

    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop());
      this.stream = null;
    }
    this.mediaRecorder = null;
  }
}

// Singleton instance
export const microphoneService = new MicrophoneService();
