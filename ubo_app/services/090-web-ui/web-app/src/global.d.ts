export {};

declare global {
  interface Window {
    WEB_UI_CONFIG: {
      grpcEnvoyListenPort: string;
      webUiListenPort: string;
    };
  }
}
