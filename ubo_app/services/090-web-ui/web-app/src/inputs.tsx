import {
  Clear,
  InfoOutlined,
  Visibility,
  VisibilityOff,
} from "@mui/icons-material";
import {
  Typography,
  TextField,
  Select,
  MenuItem,
  Button,
  FormControl,
  Divider,
  InputLabel,
  FormHelperText,
  Link,
  Stack,
  FormControlLabel,
  Switch,
  Slider,
  IconButton,
  InputAdornment,
  Popover,
  Dialog,
  DialogTitle,
  DialogContent,
} from "@mui/material";
import { useState } from "react";

import { DispatchActionRequest } from "./bindings/store/v1/store_pb";
import { StoreServiceClient } from "./bindings/store/v1/StoreServiceClientPb";
import {
  Action,
  FileUploadChunkAction,
  FileUploadCompleteAction,
  FileUploadStartAction,
  InputFieldType,
  InputMethod,
  InputProvideAction,
  InputResult,
  WebUIInputDescription,
} from "./bindings/ubo/v1/ubo_pb";
import { triggerPostDispatch } from "./store/action-dispatcher";
import { inputFieldTypes } from "./types";

const CHUNK_SIZE = 512 * 1024; // 512 KB (gRPC-web base64 inflates ~33%)
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

function HelpButton({ text }: { text: string }) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  return (
    <>
      <IconButton
        size="small"
        edge="end"
        aria-label="syntax help"
        onClick={(event) => setAnchorEl(event.currentTarget)}
      >
        <InfoOutlined fontSize="small" />
      </IconButton>
      <Popover
        open={Boolean(anchorEl)}
        anchorEl={anchorEl}
        onClose={() => setAnchorEl(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}
      >
        <Typography
          component="pre"
          variant="body2"
          sx={{
            p: 2,
            m: 0,
            whiteSpace: "pre-wrap",
            maxWidth: 380,
            fontFamily: "monospace",
          }}
        >
          {text}
        </Typography>
      </Popover>
    </>
  );
}

function dispatchActionAsync(
  store: StoreServiceClient,
  action: Action,
): Promise<void> {
  const request = new DispatchActionRequest();
  request.setAction(action);
  return new Promise((resolve, reject) => {
    store.dispatchAction(request, null, (err) => {
      if (err) reject(err);
      else resolve();
    });
  });
}

async function chunkedUpload(
  store: StoreServiceClient,
  uploadId: string,
  file: File,
): Promise<void> {
  const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

  // 1. Send start
  const startAction = new FileUploadStartAction();
  startAction.setUploadId(uploadId);
  startAction.setFilename(file.name);
  startAction.setTotalSize(file.size);
  startAction.setTotalChunks(totalChunks);
  startAction.setChunkSize(CHUNK_SIZE);

  const startAct = new Action();
  startAct.setFileUploadStartAction(startAction);
  await dispatchActionAsync(store, startAct);

  // 2. Fire all chunks concurrently with retry
  const sendChunk = async (index: number): Promise<void> => {
    const blob = file.slice(index * CHUNK_SIZE, (index + 1) * CHUNK_SIZE);
    const buffer = new Uint8Array(await blob.arrayBuffer());

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      try {
        const chunkAction = new FileUploadChunkAction();
        chunkAction.setUploadId(uploadId);
        chunkAction.setChunkIndex(index);
        chunkAction.setData(buffer);

        const act = new Action();
        act.setFileUploadChunkAction(chunkAction);
        await dispatchActionAsync(store, act);
        return;
      } catch {
        if (attempt === MAX_RETRIES) {
          throw new Error(`Chunk ${index} failed after ${MAX_RETRIES} retries`);
        }
        await new Promise((r) => setTimeout(r, RETRY_DELAY_MS * (attempt + 1)));
      }
    }
  };

  await Promise.all(
    Array.from({ length: totalChunks }, (_, i) => sendChunk(i)),
  );

  // 3. Send complete
  const completeAction = new FileUploadCompleteAction();
  completeAction.setUploadId(uploadId);

  const completeAct = new Action();
  completeAct.setFileUploadCompleteAction(completeAction);
  await dispatchActionAsync(store, completeAct);
}

type WebUIField = NonNullable<
  WebUIInputDescription.AsObject["fields"]
>["itemsList"][number];

const URL_PATTERN = /(https?:\/\/[^\s]+)/g;
// Beyond this, a URL stops being readable and starts wrecking the layout.
const MAX_LINK_TEXT = 48;

// OAuth authorization URLs run to several hundred characters of PKCE
// challenge and state, so the visible text is shortened to host + path while
// the href keeps the whole thing.
function linkText(url: string): string {
  if (url.length <= MAX_LINK_TEXT) {
    return url;
  }
  try {
    const parsed = new URL(url);
    const short = `${parsed.host}${parsed.pathname}`;
    return short.length <= MAX_LINK_TEXT ? `${short}…` : `${parsed.host}…`;
  } catch {
    return `${url.slice(0, MAX_LINK_TEXT)}…`;
  }
}

// Renders text with any URLs in it as real links. Prompts routinely carry a
// page the user has to visit — an unclickable URL they cannot select on a
// pod screen is useless to them.
export function LinkifiedText({ text }: { text?: string }) {
  if (!text) {
    return null;
  }
  return (
    <>
      {text.split(URL_PATTERN).map((part, index) =>
        index % 2 === 1 ? (
          <Link
            key={index}
            href={part}
            target="_blank"
            rel="noopener noreferrer"
          >
            {linkText(part)}
          </Link>
        ) : (
          part
        ),
      )}
    </>
  );
}

// Props shared by every plain-text-style TextField (text/number/password/…),
// so the password branch and the default branch stay in sync.
function fieldTextProps(field: WebUIField) {
  return {
    name: field.name,
    label: field.label,
    helperText: field.description ? (
      <LinkifiedText text={field.description} />
    ) : undefined,
    defaultValue: field.defaultValue || undefined,
    title: field.title || undefined,
    required: field.required,
    fullWidth: true as const,
  };
}

export function Inputs({
  inputs,
  isGrpcConnected,
  store,
}: {
  inputs: WebUIInputDescription.AsObject[];
  isGrpcConnected: boolean;
  store: StoreServiceClient | null;
}) {
  const [files, setFiles] = useState<Record<string, Record<string, File>>>({});
  const [visiblePasswords, setVisiblePasswords] = useState<
    Record<string, boolean>
  >({});

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const form = event.currentTarget;
    const formData = new FormData(form);
    const id = formData.get("id") as string;
    const input = inputs.find((input) => input.id === id);

    // Determine action early so we can skip validation for cancel
    const action =
      (formData.get("action") as string) ||
      ((event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement)
        ?.value ||
      "";

    if (!action) {
      alert("Error: Could not determine form action. Please try again.");
      return;
    }

    // Only validate fields when providing (not cancelling)
    if (action === "provide" && input?.fields) {
      for (const field of input.fields.itemsList) {
        // Skip validation for file fields (handled by onChange)
        if (field.type === InputFieldType.INPUT_FIELD_TYPE_FILE) {
          const fileValue = formData.get(field.name);
          if (
            field.required &&
            (!(fileValue instanceof File) || fileValue.size === 0)
          ) {
            alert(`"${field.label}" is required!`);
            return;
          }
          continue;
        }

        const fieldValue = formData.get(field.name) as string;

        // Check required fields
        if (field.required && (!fieldValue || fieldValue.trim() === "")) {
          alert(`"${field.label}" is required!`);
          return;
        }

        // Check pattern validation
        if (field.pattern) {
          if (fieldValue && !new RegExp(`^${field.pattern}$`).test(fieldValue)) {
            alert(
              `The value for "${field.label}" does not match the required pattern!`,
            );
            return;
          }
        }
      }
    }

    // Only file uploads still go over gRPC (chunked, in the background).
    // Text "provide" and all "cancel" submissions are sent to the Flask
    // backend instead, so they don't depend on gRPC/Envoy/Docker.
    let hasFiles = false;
    for (const entryValue of formData.values()) {
      if (entryValue instanceof File && entryValue.size > 0) {
        hasFiles = true;
        break;
      }
    }

    if (action === "provide" && hasFiles) {
      if (!store) {
        alert("Store not available. Please refresh the page.");
        return;
      }
      if (!isGrpcConnected) {
        alert("gRPC not connected. Please wait for connection.");
        return;
      }
      // Extract value: if fields are defined, use the first non-file field's
      // value; otherwise use the "value" field
      let value = "";
      if (input?.fields && input.fields.itemsList.length > 0) {
        const firstField = input.fields.itemsList.find(
          (f) => f.type !== InputFieldType.INPUT_FIELD_TYPE_FILE,
        );
        if (firstField) {
          value = (formData.get(firstField.name) as string) || "";
          if (!value || value.trim() === "") {
            const inputElement = form.querySelector(
              `[name="${firstField.name}"]`,
            ) as
              | HTMLInputElement
              | HTMLTextAreaElement
              | HTMLSelectElement
              | null;
            if (inputElement) {
              value = inputElement.value || "";
            }
          }
        }
      } else {
        value = (formData.get("value") as string) || "";
        if (!value || value.trim() === "") {
          const inputElement = form.querySelector(
            '[name="value"]',
          ) as HTMLInputElement | null;
          if (inputElement) {
            value = inputElement.value || "";
          }
        }
      }

      try {
        const inputResult = new InputResult();
        inputResult.setMethod(InputMethod.INPUT_METHOD_WEB_DASHBOARD);

        const dataMap = inputResult.getDataMap();
        // Collect file uploads to start in background after dialog closes
        const pendingUploads: Array<{ uploadId: string; file: File }> = [];

        for (const [name, value] of formData.entries()) {
          if (!["id", "value", "action"].includes(name)) {
            if (value instanceof File) {
              const uploadId =
                typeof crypto.randomUUID === "function"
                  ? crypto.randomUUID()
                  : Array.from(crypto.getRandomValues(new Uint8Array(16)))
                      .map((b) => b.toString(16).padStart(2, "0"))
                      .join("")
                      .replace(
                        /(.{8})(.{4})(.{4})(.{4})(.{12})/,
                        "$1-$2-$3-$4-$5",
                      );
              dataMap.set(`${name}_upload_id`, uploadId);
              dataMap.set(`${name}_name`, value.name);
              pendingUploads.push({ uploadId, file: value });
            } else {
              dataMap.set(name, value as string);
            }
          }
        }

        // Dispatch InputProvideAction first to close the dialog
        const inputProvideAction = new InputProvideAction();
        inputProvideAction.setId(id);
        inputProvideAction.setValue(value);
        inputProvideAction.setResult(inputResult);

        const provideAction = new Action();
        provideAction.setInputProvideAction(inputProvideAction);

        const dispatchActionRequest = new DispatchActionRequest();
        dispatchActionRequest.setAction(provideAction);

        await store.dispatchAction(dispatchActionRequest);

        // Start chunked uploads in background (dialog already closed)
        for (const { uploadId, file } of pendingUploads) {
          chunkedUpload(store, uploadId, file).catch((err) =>
            console.error("Chunked upload failed:", err),
          );
        }
      } catch (error) {
        console.error("Error dispatching InputProvideAction:", error);
        alert(
          `Error submitting form: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    } else {
      // Submit to the Flask backend, which dispatches the action directly to
      // the in-process store — no gRPC required.
      formData.set("action", action);
      try {
        await fetch("/", { method: "POST", body: formData });
      } catch (error) {
        console.error("Error submitting form to backend:", error);
        alert(
          `Error submitting form: ${error instanceof Error ? error.message : String(error)}`,
        );
        return;
      }
    }

    // Refresh status after a brief delay to allow the core to process the
    // action and update the input list. This is done once here instead of
    // after each individual dispatch branch to keep the logic centralized.
    setTimeout(() => triggerPostDispatch(), 200);
  }

  return inputs.map((input, index) => {
    const id = input.id;
    if (!id) {
      console.warn("Input description without ID:", input);
      return null;
    }
    return (
      <Dialog key={id} open>
        <DialogTitle>{input.prompt}</DialogTitle>
        {input.title && (
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ px: 3, mt: -1, mb: 1 }}
          >
            <LinkifiedText text={input.title} />
          </Typography>
        )}
        <DialogContent sx={{ "&&.MuiDialogContent-root": { pt: 1 } }}>
          <Stack
            component="form"
            autoComplete="off"
            gap={2}
            onSubmit={handleSubmit}
          >
            <input name="id" type="hidden" value={id} />

            {input.fields?.itemsList.length ? (
              input.fields.itemsList.map((field) =>
                field.type === InputFieldType.INPUT_FIELD_TYPE_SELECT ? (
                  <FormControl
                    key={field.name}
                    fullWidth
                    required={field.required}
                  >
                    <InputLabel htmlFor={field.name}>{field.label}</InputLabel>
                    <Select
                      id={field.name}
                      name={field.name}
                      label={field.label}
                      defaultValue={field.defaultValue || ""}
                      displayEmpty
                    >
                      {field.options?.itemsList?.map((option) => (
                        <MenuItem key={option} value={option}>
                          {option}
                        </MenuItem>
                      ))}
                    </Select>
                    {field.description && (
                      <FormHelperText><LinkifiedText text={field.description} /></FormHelperText>
                    )}
                  </FormControl>
                ) : field.type === InputFieldType.INPUT_FIELD_TYPE_LONG ? (
                  <TextField
                    key={field.name}
                    name={field.name}
                    label={field.label}
                    helperText={field.description}
                    defaultValue={field.defaultValue || undefined}
                    title={field.title || undefined}
                    multiline
                    minRows={4}
                    slotProps={{
                      htmlInput: {
                        pattern: field.pattern || undefined,
                      },
                      input: field.help
                        ? {
                            endAdornment: <HelpButton text={field.help} />,
                            sx: { alignItems: "flex-start" },
                          }
                        : undefined,
                    }}
                    required={field.required}
                    fullWidth
                  />
                ) : field.type === InputFieldType.INPUT_FIELD_TYPE_CHECKBOX ? (
                  <FormControl
                    key={field.name}
                    fullWidth
                    required={field.required}
                    title={field.title || undefined}
                  >
                    <FormControlLabel
                      label={field.label}
                      control={
                        <Switch
                          name={field.name}
                          required={field.required}
                          defaultValue={field.defaultValue || undefined}
                        />
                      }
                    />
                    <FormHelperText><LinkifiedText text={field.description} /></FormHelperText>
                  </FormControl>
                ) : field.type === InputFieldType.INPUT_FIELD_TYPE_FILE ? (
                  <FormControl
                    key={field.name}
                    fullWidth
                    required={field.required}
                    title={field.title || undefined}
                  >
                    <InputLabel htmlFor={field.name}>{field.label}</InputLabel>
                    <Stack direction="row" spacing={1} width="100%" mt={5}>
                      <Button
                        component="label"
                        variant={
                          files[id]?.[field.name] ? "contained" : "outlined"
                        }
                        sx={{ flexGrow: 1, textTransform: "none" }}
                      >
                        <input
                          type="file"
                          id={field.name}
                          name={field.name}
                          required={field.required}
                          accept={field.fileMimetype || "*"}
                          onChange={async (event) => {
                            const clearField = () =>
                              setFiles((files) => {
                                const fieldFiles = { ...files[id] };
                                delete fieldFiles[field.name];
                                return { ...files, [id]: fieldFiles };
                              });
                            if (event.target.files?.length) {
                              const file = event.target.files[0];
                              // Only decode the file as text when a pattern needs
                              // to validate it; binary uploads (e.g. .onnx models)
                              // have no pattern and must not be read as text.
                              const matches =
                                !field.pattern ||
                                new RegExp(field.pattern).test(await file.text());
                              if (matches) {
                                setFiles((files) => ({
                                  ...files,
                                  [id]: {
                                    ...files[id],
                                    [field.name]: file,
                                  },
                                }));
                              } else {
                                alert(
                                  `The file "${file.name}" does not match the required pattern!`,
                                );
                                event.target.value = "";
                                clearField();
                              }
                            } else {
                              clearField();
                            }
                          }}
                          hidden
                        />
                        <Typography variant="body2">
                          {files[id]?.[field.name]
                            ? files[id][field.name].name
                            : "Select a file"}
                        </Typography>
                      </Button>
                      {files[id]?.[field.name] && (
                        <IconButton
                          sx={{ flexGrow: 0, flexShrink: 0 }}
                          onClick={(event) => {
                            const input =
                              event.currentTarget.previousElementSibling?.querySelector(
                                "input",
                              ) as HTMLInputElement;
                            input.value = "";
                            setFiles((files) => {
                              const fieldFiles = { ...files[id] };
                              delete fieldFiles[field.name];
                              return { ...files, [id]: fieldFiles };
                            });
                          }}
                        >
                          <Clear />
                        </IconButton>
                      )}
                    </Stack>
                    <FormHelperText><LinkifiedText text={field.description} /></FormHelperText>
                  </FormControl>
                ) : field.type === InputFieldType.INPUT_FIELD_TYPE_PASSWORD ? (
                  <TextField
                    key={field.name}
                    type={
                      visiblePasswords[`${id}:${field.name}`]
                        ? "text"
                        : "password"
                    }
                    {...fieldTextProps(field)}
                    slotProps={{
                      input: {
                        endAdornment: (
                          <InputAdornment position="end">
                            <IconButton
                              aria-label={
                                visiblePasswords[`${id}:${field.name}`]
                                  ? "Hide password"
                                  : "Show password"
                              }
                              edge="end"
                              onClick={() =>
                                setVisiblePasswords((state) => ({
                                  ...state,
                                  [`${id}:${field.name}`]:
                                    !state[`${id}:${field.name}`],
                                }))
                              }
                            >
                              {visiblePasswords[`${id}:${field.name}`] ? (
                                <VisibilityOff />
                              ) : (
                                <Visibility />
                              )}
                            </IconButton>
                          </InputAdornment>
                        ),
                      },
                    }}
                  />
                ) : field.type === InputFieldType.INPUT_FIELD_TYPE_RANGE ? (
                  <FormControl
                    key={field.name}
                    fullWidth
                    required={field.required}
                    title={field.title || undefined}
                  >
                    <Typography gutterBottom>{field.label}</Typography>
                    <Slider
                      name={field.name}
                      min={0}
                      max={100}
                      step={1}
                      defaultValue={
                        field.defaultValue !== "" &&
                        Number.isFinite(Number(field.defaultValue))
                          ? Number(field.defaultValue)
                          : 50
                      }
                      valueLabelDisplay="auto"
                      valueLabelFormat={(value) => `${value}%`}
                      sx={{ mx: 1, width: "calc(100% - 16px)" }}
                    />
                    <FormHelperText><LinkifiedText text={field.description} /></FormHelperText>
                  </FormControl>
                ) : (
                  <TextField
                    key={field.name}
                    type={inputFieldTypes[field.type]}
                    {...fieldTextProps(field)}
                  />
                ),
              )
            ) : (
              <FormControl fullWidth>
                <TextField type="text" name="value" fullWidth />
              </FormControl>
            )}

            <Stack direction="row" spacing={2}>
              <Button
                type="submit"
                name="action"
                value="provide"
                variant="contained"
                color="primary"
              >
                Provide
              </Button>
              <Button
                type="submit"
                name="action"
                value="cancel"
                variant="outlined"
                formNoValidate
              >
                Cancel
              </Button>
            </Stack>

            {index < inputs.length - 1 && <Divider />}
          </Stack>
        </DialogContent>
      </Dialog>
    );
  });
}
