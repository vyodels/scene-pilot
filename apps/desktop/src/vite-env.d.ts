/// <reference types="vite/client" />

declare global {
  interface Window {
    recruitAgent?: {
      environment: string;
    };
  }
}

export {};
