import { useState, useEffect } from 'react';
import type { ReactNode } from 'react';
import './InitializationWrapper.css';

interface InitializationWrapperProps {
  children: ReactNode;
}

export function InitializationWrapper({ children }: InitializationWrapperProps) {
  const [bootState, setBootState] = useState<'hidden' | 'emerging' | 'glowing' | 'particles' | 'settled'>('hidden');

  useEffect(() => {
    // Sequence timing
    const sequence = async () => {
      // 1. Dark environment (initial state)
      await new Promise((r) => setTimeout(r, 200));
      
      // 2. Orb emerges
      setBootState('emerging');
      await new Promise((r) => setTimeout(r, 400));
      
      // 3. Glow develops
      setBootState('glowing');
      await new Promise((r) => setTimeout(r, 400));
      
      // 4. Particles appear
      setBootState('particles');
      await new Promise((r) => setTimeout(r, 400));
      
      // 5. System settles -> IDLE
      setBootState('settled');
    };

    sequence();
  }, []);

  return (
    <div className={`initialization-wrapper boot-${bootState}`}>
      {children}
    </div>
  );
}
