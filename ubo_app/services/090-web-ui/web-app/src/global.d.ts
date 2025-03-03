export {};

declare global {
  interface Window {
    GRPC_ENVOY_LISTEN_PORT: string;
  }
}
