import { useEffect, useRef } from 'react';
import { useSystemStore } from '@/state/systemStore.ts';
import { OrbState, OrbEvent } from '@/features/orb/types.ts';
import { microphoneService } from '@/services/voice/MicrophoneService.ts';
import { audioPlaybackService } from '@/services/voice/AudioPlaybackService.ts';
import { voiceClient } from '@/services/api/voiceClient.ts';

/**
 * Headless component that orchestrates the voice pipeline
 * based on the Orb state machine.
 */
export function VoiceInteractionManager() {
  const { orbState, sendOrbEvent } = useSystemStore();
  const processingRef = useRef(false);

  useEffect(() => {
    // Prevent re-triggering if already processing a state transition
    if (processingRef.current) return;

    const handleState = async () => {
      try {
        switch (orbState) {
          case OrbState.LISTENING:
            processingRef.current = true;
            await microphoneService.startRecording();
            processingRef.current = false;
            break;

          case OrbState.TRANSCRIBING:
            processingRef.current = true;
            const audioBlob = await microphoneService.stopRecording();
            
            // 1. Transcribe
            const transcript = await voiceClient.transcribeAudio(audioBlob);
            if (!transcript) throw new Error("Empty transcript");
            
            sendOrbEvent(OrbEvent.PROCESSING_START);
            
            // 2. We are now heading to THINKING, the logic continues there.
            // But we can just continue the async chain here if we want, 
            // OR let the THINKING state handler catch it. 
            // Better to let state handler catch it.
            processingRef.current = false;
            
            // Wait, we need to pass the transcript to THINKING.
            // Using a simple module-level variable or ref for the prototype.
            window.__lastTranscript = transcript;
            break;

          case OrbState.THINKING:
            processingRef.current = true;
            const textToSend = window.__lastTranscript || "Hello ASTRA";
            
            // 2. Get AI Response
            const aiResponse = await voiceClient.sendMessage(textToSend);
            
            // 3. Synthesize Speech
            const ttsAudioBlob = await voiceClient.synthesizeSpeech(aiResponse);
            window.__lastAudioBlob = ttsAudioBlob;
            
            sendOrbEvent(OrbEvent.RESPONSE_READY);
            processingRef.current = false;
            break;

          case OrbState.SPEAKING:
            processingRef.current = true;
            const blobToPlay = window.__lastAudioBlob;
            if (blobToPlay) {
              await audioPlaybackService.playAudioBlob(blobToPlay);
            }
            sendOrbEvent(OrbEvent.SPEECH_COMPLETE);
            processingRef.current = false;
            break;
            
          case OrbState.IDLE:
            // Stop any ongoing playback if we transition back to IDLE unexpectedly (interruption)
            audioPlaybackService.stop();
            document.documentElement.style.setProperty('--audio-level', '0');
            break;
            
          case OrbState.ERROR:
            // Cleanup
            microphoneService.stopRecording().catch(() => {});
            audioPlaybackService.stop();
            document.documentElement.style.setProperty('--audio-level', '0');
            
            // Auto-clear error after 3 seconds for prototype
            setTimeout(() => {
              sendOrbEvent(OrbEvent.ERROR_CLEARED);
            }, 3000);
            break;
        }
      } catch (error) {
        console.error('Voice pipeline error:', error);
        sendOrbEvent(OrbEvent.ERROR_OCCURRED, { errorMessage: String(error) });
        processingRef.current = false;
      }
    };

    handleState();
  }, [orbState, sendOrbEvent]);

  return null;
}

// Add global types for our temporary state passing
declare global {
  interface Window {
    __lastTranscript?: string;
    __lastAudioBlob?: Blob;
  }
}
