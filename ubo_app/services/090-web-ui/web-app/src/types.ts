import { InputFieldType } from "./bindings/ubo/v1/ubo_pb";

export type Action =
  | "install docker"
  | "run docker"
  | "stop docker"
  | "download envoy"
  | "run envoy"
  | "remove envoy";

export const inputFieldTypes: Record<InputFieldType, string> = {
  [InputFieldType.INPUT_FIELD_TYPE_LONG]: "long",
  [InputFieldType.INPUT_FIELD_TYPE_TEXT]: "text",
  [InputFieldType.INPUT_FIELD_TYPE_PASSWORD]: "password",
  [InputFieldType.INPUT_FIELD_TYPE_NUMBER]: "number",
  [InputFieldType.INPUT_FIELD_TYPE_CHECKBOX]: "checkbox",
  [InputFieldType.INPUT_FIELD_TYPE_COLOR]: "color",
  [InputFieldType.INPUT_FIELD_TYPE_SELECT]: "select",
  [InputFieldType.INPUT_FIELD_TYPE_FILE]: "file",
  [InputFieldType.INPUT_FIELD_TYPE_DATE]: "date",
  [InputFieldType.INPUT_FIELD_TYPE_TIME]: "time",
  [InputFieldType.INPUT_FIELD_TYPE_UBO_APP_DOT_STORE_DOT_INPUT_DOT_TYPES_UNSPECIFIED]:
    "unspecified",
};

export interface StatusType {
  status: "ok" | "error";
  docker:
  | "running"
  | "not ready"
  | "not installed"
  | "not running"
  | "unknown"
  | "failed";
  envoy: "running" | "not downloaded" | "not running" | "unknown" | "failed";
  state: string;
}
