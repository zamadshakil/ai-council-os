'use client';

import { MotionConfig } from 'framer-motion';

export function InterfaceMotionProvider({ children }: { children: React.ReactNode }) {
  return (
    <MotionConfig
      reducedMotion="user"
      transition={{ type: 'spring', stiffness: 420, damping: 34, mass: 0.72 }}
    >
      {children}
    </MotionConfig>
  );
}
