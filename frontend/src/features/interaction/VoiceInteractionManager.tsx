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
            // Stop any ongoing playback on barge-in
            audioPlaybackService.stop();
            document.documentElement.style.setProperty('--audio-level', '0');
            console.log('VOICE_CAPTURE_STARTED');
            processingRef.current = true;
            await microphoneService.startRecording();
            processingRef.current = false;
            break;

          case OrbState.TRANSCRIBING:
            processingRef.current = true;
            console.log('VOICE_CAPTURE_ENDED');
            const audioBlob = await microphoneService.stopRecording();
            
            console.log('TRANSCRIPTION_STARTED');
            const transcript = await voiceClient.transcribeAudio(audioBlob);
            console.log('TRANSCRIPTION_COMPLETED');
            
            if (!transcript) throw new Error("Empty transcript");
            
            // Guard: don't transition if user cancelled/interrupted during transcription
            if (useSystemStore.getState().orbState === OrbState.TRANSCRIBING) {
              window.__lastTranscript = transcript;
              sendOrbEvent(OrbEvent.PROCESSING_START);
            }
            processingRef.current = false;
            break;

          case OrbState.THINKING:
            processingRef.current = true;
            const textToSend = window.__lastTranscript || "Hello ASTRA";
            
            console.log('AI_REQUEST_STARTED');
            const aiResponse = await voiceClient.sendMessage(textToSend);
            console.log('AI_RESPONSE_RECEIVED');
            
            console.log('TTS_STARTED');
            const ttsAudioBlob = await voiceClient.synthesizeSpeech(aiResponse);
            console.log('TTS_COMPLETED');
            
            // Guard: don't transition if user cancelled/interrupted during processing
            if (useSystemStore.getState().orbState === OrbState.THINKING) {
              window.__lastAudioBlob = ttsAudioBlob;
              sendOrbEvent(OrbEvent.RESPONSE_READY);
            }
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
            console.log('VOICE_SESSION_COMPLETED');
            audioPlaybackService.stop();
            document.documentElement.style.setProperty('--audio-level', '0');
            break;
            
          case OrbState.ERROR:
            console.log('VOICE_ERROR');
            // Cleanup
            microphoneService.stopRecording().catch(() => {});
            audioPlaybackService.stop();
            document.documentElement.style.setProperty('--audio-level', '0');
            
            // Auto-clear error after 3 seconds for prototype
            setTimeout(() => {
              if (useSystemStore.getState().orbState === OrbState.ERROR) {
                sendOrbEvent(OrbEvent.ERROR_CLEARED);
              }
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
