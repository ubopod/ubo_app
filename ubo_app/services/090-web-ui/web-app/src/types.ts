export type Action =
  | "install docker"
  | "run docker"
  | "stop docker"
  | "download envoy"
  | "run envoy"
  | "remove envoy";

export interface ReadableInformation {
  text: string;
}

export enum InputFieldType {
  LONG = "long",
  TEXT = "text",
  PASSWORD = "password",
  NUMBER = "number",
  CHECKBOX = "checkbox",
  COLOR = "color",
  SELECT = "select",
  FILE = "file",
  DATE = "date",
  TIME = "time",
}

export interface InputFieldDescription {
  name: string;
  label: string;
  type: InputFieldType;
  description: string | null;
  title: string | null;
  pattern: string | null;
  default: string | null;
  options: string[] | null;
  required: boolean;
}

export interface InputDescription {
  title: string;
  prompt: string | null;
  extra_information: ReadableInformation | null;
  id: string;
  fields: InputFieldDescription[];
  pattern: string | null;
}

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
  inputs: InputDescription[];
}
