/**
 * The `StoreService` server-streaming calls, bound to the fetch transport.
 *
 * Unary calls still go through the generated `StoreServiceClient`: they
 * complete, so the buffer grpc-web keeps for the life of a request is released
 * with them. Only the endless streams need {@link openServerStream}.
 */
import {
  openServerStream,
  type Cancelable,
  type StreamSink,
} from "./fetch-stream";
import { getGrpcWebBaseUrl } from "./grpc-endpoint";
import {
  SubscribeEventRequest,
  SubscribeEventResponse,
  SubscribeStoreRequest,
  SubscribeStoreResponse,
} from "../bindings/store/v1/store_pb";

export function subscribeEvent(
  request: SubscribeEventRequest,
  sink: StreamSink<SubscribeEventResponse>,
): Cancelable {
  return openServerStream({
    url: `${getGrpcWebBaseUrl()}/store.v1.StoreService/SubscribeEvent`,
    request,
    deserialize: SubscribeEventResponse.deserializeBinary,
    sink,
  });
}

export function subscribeStore(
  request: SubscribeStoreRequest,
  sink: StreamSink<SubscribeStoreResponse>,
): Cancelable {
  return openServerStream({
    url: `${getGrpcWebBaseUrl()}/store.v1.StoreService/SubscribeStore`,
    request,
    deserialize: SubscribeStoreResponse.deserializeBinary,
    sink,
  });
}
