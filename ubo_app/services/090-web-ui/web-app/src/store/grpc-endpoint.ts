/**
 * Base URL of the gRPC-web endpoint Envoy serves.
 *
 * When the page comes from the web-UI port, Envoy's gRPC listener is on a
 * different port and the URL has to name it explicitly. Behind a reverse proxy
 * the two share an origin, so a relative `/grpc` prefix is enough.
 */
export function getGrpcWebBaseUrl(): string {
  if (window.location.port === window.WEB_UI_CONFIG.webUiListenPort) {
    return `${window.location.protocol}//${window.location.hostname}:${window.WEB_UI_CONFIG.grpcEnvoyListenPort}/grpc`;
  }
  return `${window.location.origin}/grpc`;
}
