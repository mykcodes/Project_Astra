import { useEffect, useRef } from 'react';
import { useSystemStore } from '@/state/systemStore.ts';
import { OrbState } from './types.ts';
import './Particles.css';

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  alpha: number;
  targetAlpha: number;
  life: number;
  maxLife: number;
  angle: number;
  speed: number;
  color: string;
}

export function Particles() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const orbState = useSystemStore((s) => s.orbState);
  
  // Ref to keep track of the current state without triggering re-renders in the animation loop
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
    const MAX_PARTICLES = 150;
    let animationFrameId: number;

    const createParticle = (state: OrbState): Particle => {
      const centerX = width / 2;
      const centerY = height / 2;
      
      // Spawn particles in a ring around the orb
      const minRadius = 80;
      const maxRadius = 350;
      const distance = minRadius + Math.pow(Math.random(), 2) * (maxRadius - minRadius);
      const angle = Math.random() * Math.PI * 2;
      
      let speed = 0.2;
      let color = 'hsla(220, 90%, 70%, 0.8)'; // default primary light
      let maxLife = 100 + Math.random() * 200;
      
      switch (state) {
        case OrbState.IDLE:
          speed = 0.05 + Math.random() * 0.1;
          color = 'hsla(220, 90%, 75%, 0.4)';
          break;
        case OrbState.LISTENING:
          speed = 1.0 + Math.random() * 1.5;
          color = 'hsla(152, 70%, 65%, 0.7)';
          break;
        case OrbState.TRANSCRIBING:
          speed = 1.2 + Math.random() * 1.8;
          color = 'hsla(190, 80%, 65%, 0.7)';
          break;
        case OrbState.THINKING:
          speed = 1.5 + Math.random() * 2.0;
          color = 'hsla(262, 80%, 75%, 0.8)';
          break;
        case OrbState.SPEAKING:
          speed = 2.0 + Math.random() * 3.0;
          color = 'hsla(200, 85%, 65%, 0.8)';
          break;
        case OrbState.ERROR:
          speed = 0.1 + Math.random() * 0.2;
          color = 'hsla(0, 72%, 65%, 0.5)';
          break;
        case OrbState.DISCONNECTED:
          speed = 0.02 + Math.random() * 0.05;
          color = 'hsla(220, 10%, 55%, 0.2)';
          break;
      }

      return {
        x: centerX + Math.cos(angle) * distance,
        y: centerY + Math.sin(angle) * distance,
        vx: 0,
        vy: 0,
        radius: 0.5 + Math.random() * 2,
        alpha: 0,
        targetAlpha: Math.random(),
        life: 0,
        maxLife,
        angle,
        speed,
        color
      };
    };

    const updateParticles = () => {
      const currentState = stateRef.current;
      
      // Maintain particle count
      if (particles.length < MAX_PARTICLES && Math.random() < 0.2) {
        particles.push(createParticle(currentState));
      }

      const centerX = width / 2;
      const centerY = height / 2;

      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        if (!p) continue;
        p.life++;

        if (p.life >= p.maxLife) {
          particles.splice(i, 1);
          continue;
        }

        // Fade in/out
        if (p.life < p.maxLife * 0.2) {
          p.alpha += 0.01;
        } else if (p.life > p.maxLife * 0.8) {
          p.alpha -= 0.01;
        }

        p.alpha = Math.max(0, Math.min(p.alpha, p.targetAlpha));

        // Movement behavior based on state
        switch (currentState) {
          case OrbState.IDLE:
          case OrbState.DISCONNECTED:
          case OrbState.ERROR:
            // Slow orbital movement
            p.angle += p.speed * 0.005;
            const dxIdle = p.x - centerX;
            const dyIdle = p.y - centerY;
            const distIdle = Math.sqrt(dxIdle * dxIdle + dyIdle * dyIdle);
            p.x = centerX + Math.cos(p.angle) * distIdle;
            p.y = centerY + Math.sin(p.angle) * distIdle;
            break;
            
          case OrbState.LISTENING:
            // Move smoothly towards center (attraction)
            const dxList = centerX - p.x;
            const dyList = centerY - p.y;
            const distList = Math.sqrt(dxList * dxList + dyList * dyList);
            if (distList > 80) {
              p.x += (dxList / distList) * p.speed;
              p.y += (dyList / distList) * p.speed;
            }
            p.angle += 0.02; // slight rotation as they get pulled in
            break;
            
          case OrbState.TRANSCRIBING:
            // Particles orbit inward in a tight spiral
            p.angle += p.speed * 0.02;
            const dxTrans = p.x - centerX;
            const dyTrans = p.y - centerY;
            let distTrans = Math.sqrt(dxTrans * dxTrans + dyTrans * dyTrans);
            if (distTrans > 90) {
              distTrans -= p.speed * 0.5;
            } else if (distTrans < 85) {
              distTrans += p.speed * 0.5;
            }
            p.x = centerX + Math.cos(p.angle) * distTrans;
            p.y = centerY + Math.sin(p.angle) * distTrans;
            break;
            
          case OrbState.THINKING:
            // Faster orbital movement with slight wobble
            p.angle += p.speed * 0.015;
            const wobble = Math.sin(p.life * 0.1) * 2;
            const dxThink = p.x - centerX;
            const dyThink = p.y - centerY;
            let distThink = Math.sqrt(dxThink * dxThink + dyThink * dyThink);
            distThink += wobble * 0.2;
            p.x = centerX + Math.cos(p.angle) * distThink;
            p.y = centerY + Math.sin(p.angle) * distThink;
            break;
            
          case OrbState.SPEAKING:
            // Burst outwards dynamically
            const dirX = p.x - centerX;
            const dirY = p.y - centerY;
            const mag = Math.sqrt(dirX * dirX + dirY * dirY);
            if (mag > 0) {
              // Accelerate as they move outward
              const dynamicSpeed = p.speed * (1 + mag * 0.005);
              p.x += (dirX / mag) * dynamicSpeed;
              p.y += (dirY / mag) * dynamicSpeed;
            }
            // Add a slight sine wave to outward burst
            p.x += Math.sin(p.life * 0.2) * 1;
            p.y += Math.cos(p.life * 0.2) * 1;
            break;
        }
      }
    };

    const drawParticles = () => {
      ctx.clearRect(0, 0, width, height);
      
      particles.forEach(p => {
        if (p.alpha <= 0) return;
        
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        
        // Convert the hsla string to include alpha
        const colorWithAlpha = p.color.replace(/[\d.]+\)$/g, `${p.alpha})`);
        
        ctx.fillStyle = colorWithAlpha;
        ctx.fill();
        
        // Add subtle glow to each particle
        ctx.shadowBlur = p.radius * 2;
        ctx.shadowColor = p.color;
      });
    };

    const renderLoop = () => {
      updateParticles();
      drawParticles();
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
