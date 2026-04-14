/// <reference types="vite/client" />

declare global {
  interface Window {
    scenePilot?: {
      environment: string;
    };
  }
}

export {};
