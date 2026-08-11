import { useEffect, useRef } from 'react';
import { OrbState } from './types.ts';
import './Particles.css';

interface ParticlesProps {
  orbState: OrbState;
}

interface Particle {
  x: number;
  y: number;
  z: number;
  baseRadius: number;
  angle1: number;
  angle2: number;
  speed: number;
  color: string;
}

// Helper to interpolate values
const lerp = (start: number, end: number, amt: number) => (1 - amt) * start + amt * end;

export function Particles({ orbState }: ParticlesProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef(orbState);
  
  useEffect(() => {
    stateRef.current = orbState;
  }, [orbState]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) return;

    let width = window.innerWidth;
    let height = window.innerHeight;
    canvas.width = width;
    canvas.height = height;

    const handleResize = () => {
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = width;
      canvas.height = height;
    };
    window.addEventListener('resize', handleResize);

    const particles: Particle[] = [];
    const MAX_PARTICLES = 300; // Increased for a denser orb
    let animationFrameId: number;
    let time = 0;

    // Smoothed transition values
    let currentRadius = 100;
    let currentSpeedMult = 1;
    let currentAudioLevel = 0;

    // Initialize particles
    for (let i = 0; i < MAX_PARTICLES; i++) {
      particles.push({
        x: 0, y: 0, z: 0,
        baseRadius: 1 + Math.random() * 2,
        angle1: Math.random() * Math.PI * 2,
        angle2: Math.random() * Math.PI * 2,
        speed: 0.005 + Math.random() * 0.015,
        color: `hsla(${200 + Math.random() * 40}, 80%, 70%, 0.8)`
      });
    }

    const renderLoop = () => {
      ctx.clearRect(0, 0, width, height);
      const state = stateRef.current;
      time += 0.01;

      // Read audio level from CSS variable set by services
      const rawAudioLevel = parseFloat(document.documentElement.style.getPropertyValue('--audio-level')) || 0;
      currentAudioLevel = lerp(currentAudioLevel, rawAudioLevel, 0.2);

      // Define target parameters based on state
      let targetRadius = 100;
      let targetSpeedMult = 1;
      let targetHue = 220;
      let baseGlow = 0.5;

      switch (state) {
        case OrbState.IDLE:
          targetRadius = 110;
          targetSpeedMult = 0.5;
          targetHue = 220;
          baseGlow = 0.3;
          break;
        case OrbState.LISTENING:
          targetRadius = 130 + currentAudioLevel * 50; // Audio reacts here
          targetSpeedMult = 1.5 + currentAudioLevel * 2;
          targetHue = 152; // Greenish
          baseGlow = 0.8;
          break;
        case OrbState.TRANSCRIBING:
          targetRadius = 100;
          targetSpeedMult = 3.0; // Fast tight spin
          targetHue = 190;
          baseGlow = 0.6;
          break;
        case OrbState.THINKING:
          targetRadius = 110 + Math.sin(time * 5) * 10; // Gentle pulse
          targetSpeedMult = 2.0;
          targetHue = 262; // Purple
          baseGlow = 0.7;
          break;
        case OrbState.SPEAKING:
          targetRadius = 120 + currentAudioLevel * 80;
          targetSpeedMult = 1.0 + currentAudioLevel * 3;
          targetHue = 200;
          baseGlow = 0.5 + currentAudioLevel;
          break;
        case OrbState.ERROR:
          targetRadius = 90;
          targetSpeedMult = 0.2;
          targetHue = 0; // Red
          baseGlow = 0.4;
          break;
        case OrbState.DISCONNECTED:
          targetRadius = 80;
          targetSpeedMult = 0.1;
          targetHue = 220;
          baseGlow = 0.1;
          break;
      }

      // Smooth interpolation for global physics parameters
      currentRadius = lerp(currentRadius, targetRadius, 0.1);
      currentSpeedMult = lerp(currentSpeedMult, targetSpeedMult, 0.1);

      const centerX = width / 2;
      const centerY = height / 2;

      // Draw central atmospheric core (behind particles)
      const coreGradient = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, currentRadius * 1.5);
      coreGradient.addColorStop(0, `hsla(${targetHue}, 80%, 70%, ${baseGlow * 0.4})`);
      coreGradient.addColorStop(1, 'transparent');
      ctx.fillStyle = coreGradient;
      ctx.fillRect(0, 0, width, height);

      // Sort particles by Z-axis for depth rendering (painters algorithm)
      // Since we calculate Z dynamically, we just sort the array directly on render
      // But doing it every frame is expensive, so we just calculate 3D coords and sort an index array
      
      const renderList = particles.map(p => {
        // Update angles
        p.angle1 += p.speed * currentSpeedMult;
        p.angle2 += (p.speed * 0.5) * currentSpeedMult;

        // Spherical distribution with noise
        const r = currentRadius + Math.sin(p.angle1 * 3 + time) * 10;
        
        // 3D coordinates
        const x3d = r * Math.sin(p.angle1) * Math.cos(p.angle2);
        const y3d = r * Math.sin(p.angle1) * Math.sin(p.angle2);
        const z3d = r * Math.cos(p.angle1);
        
        return { p, x3d, y3d, z3d };
      });

      renderList.sort((a, b) => a.z3d - b.z3d); // sort by depth

      for (const item of renderList) {
        const { p, x3d, y3d, z3d } = item;
        
        // 3D to 2D projection
        const fov = 400;
        const scale = fov / (fov + z3d + 200); // offset Z to push it into the screen
        
        const projX = centerX + x3d * scale;
        const projY = centerY + y3d * scale;
        
        // Dynamic radius and opacity based on depth (Z)
        const size = Math.max(0.1, p.baseRadius * scale * 2);
        
        // Near particles are brighter, far particles are dimmer
        const depthAlpha = Math.max(0.1, Math.min(1.0, (z3d + currentRadius) / (currentRadius * 2)));
        const finalAlpha = depthAlpha * baseGlow;

        // Apply dynamic hue while keeping some variation
        const h = targetHue + (Math.sin(p.angle1) * 20); // slight hue variance
        
        ctx.beginPath();
        ctx.arc(projX, projY, size, 0, Math.PI * 2);
        ctx.fillStyle = `hsla(${h}, 80%, 70%, ${finalAlpha})`;
        ctx.fill();

        if (finalAlpha > 0.4) {
          ctx.shadowBlur = size * 2;
          ctx.shadowColor = `hsla(${h}, 80%, 70%, ${finalAlpha})`;
        } else {
          ctx.shadowBlur = 0;
        }
      }

      animationFrameId = requestAnimationFrame(renderLoop);
    };

    renderLoop();

    return () => {
      window.removeEventListener('resize', handleResize);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return <canvas ref={canvasRef} className="particles-canvas" aria-hidden="true" />;
}
