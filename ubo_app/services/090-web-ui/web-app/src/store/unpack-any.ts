// Decodes the `google.protobuf.Any` values that `SubscribeStore` returns, one
// per selector. This is the TypeScript counterpart of `_unpack_from_any` in
// `ubo_app/rpc/ubo_bindings/client.py`, and mirrors the packing rules in
// `ubo_app/rpc/store_service.py:_pack_to_any`: scalars arrive inside the
// `google.protobuf.*Value` wrappers, `None` arrives as `Empty`, and anything
// else is a `ubo.v1` message.
//
// The wrapper types are decoded by hand rather than via `wrappers_pb` — they
// are single-field messages, `google-protobuf` ships no type declarations, and
// this keeps them out of the bundle.

import * as uboPb from "../bindings/ubo/v1/ubo_pb";

const TYPE_URL_PREFIX = "type.googleapis.com/";
const UBO_PACKAGE = "ubo_bindings.ubo.v1.";

interface Deserializable {
  deserializeBinary(bytes: Uint8Array): { toObject(): unknown };
}

// jspb generates one class per message; the module exports them by short name.
const uboMessages = uboPb as unknown as Record<string, Deserializable | undefined>;

/** Read a base-128 varint. Returns the value and the offset just past it. */
function readVarint(bytes: Uint8Array, start: number): [bigint, number] {
  let result = 0n;
  let shift = 0n;
  let offset = start;
  while (offset < bytes.length) {
    const byte = bytes[offset];
    offset += 1;
    result |= BigInt(byte & 0x7f) << shift;
    if ((byte & 0x80) === 0) break;
    shift += 7n;
  }
  return [result, offset];
}

// proto3 omits a field set to its zero value, so an empty payload is not an
// error — it is `0` / `false` / `""`. Every decoder below returns the zero
// value when field 1 is absent.
function decodeDouble(bytes: Uint8Array): number {
  if (bytes.length < 9 || bytes[0] !== 0x09) return 0;
  return new DataView(bytes.buffer, bytes.byteOffset + 1, 8).getFloat64(0, true);
}

function decodeInt64(bytes: Uint8Array): number {
  if (bytes.length < 2 || bytes[0] !== 0x08) return 0;
  const [value] = readVarint(bytes, 1);
  // int64 is two's complement, not zigzag: negatives are sent as 10 bytes.
  const signed = BigInt.asIntN(64, value);
  return Number(signed);
}

function decodeBool(bytes: Uint8Array): boolean {
  if (bytes.length < 2 || bytes[0] !== 0x08) return false;
  const [value] = readVarint(bytes, 1);
  return value !== 0n;
}

function decodeLengthDelimited(bytes: Uint8Array): Uint8Array {
  if (bytes.length < 2 || bytes[0] !== 0x0a) return new Uint8Array(0);
  const [length, offset] = readVarint(bytes, 1);
  return bytes.subarray(offset, offset + Number(length));
}

function decodeString(bytes: Uint8Array): string {
  return new TextDecoder().decode(decodeLengthDelimited(bytes));
}

/**
 * Decode one `Any` into a plain JS value.
 *
 * Messages come back as the jspb `toObject()` shape — the same
 * `SomeState.AsObject` types the rest of the app already consumes. Unknown
 * type URLs yield `null` rather than throwing, so one unrecognised selector
 * cannot take down the whole subscription.
 */
export function unpackAny(typeUrl: string, bytes: Uint8Array): unknown {
  const name = typeUrl.startsWith(TYPE_URL_PREFIX)
    ? typeUrl.slice(TYPE_URL_PREFIX.length)
    : typeUrl;

  switch (name) {
    case "google.protobuf.Empty":
      return null;
    case "google.protobuf.DoubleValue":
      return decodeDouble(bytes);
    case "google.protobuf.Int64Value":
      return decodeInt64(bytes);
    case "google.protobuf.BoolValue":
      return decodeBool(bytes);
    case "google.protobuf.StringValue":
      return decodeString(bytes);
    case "google.protobuf.BytesValue":
      return decodeLengthDelimited(bytes);
    default:
      break;
  }

  if (name.startsWith(UBO_PACKAGE)) {
    const messageClass = uboMessages[name.slice(UBO_PACKAGE.length)];
    if (messageClass) {
      return messageClass.deserializeBinary(bytes).toObject();
    }
  }

  return null;
}
