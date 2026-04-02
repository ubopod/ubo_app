import { Clear } from "@mui/icons-material";
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
  Stack,
  FormControlLabel,
  Switch,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
} from "@mui/material";
import { useState } from "react";

import { DispatchActionRequest } from "./bindings/store/v1/store_pb";
import { StoreServiceClient } from "./bindings/store/v1/StoreServiceClientPb";
import {
  Action,
  InputCancelAction,
  InputFieldType,
  InputMethod,
  InputProvideAction,
  InputResult,
  WebUIInputDescription,
} from "./bindings/ubo/v1/ubo_pb";
import { triggerPostDispatch } from "./store/action-dispatcher";
import { inputFieldTypes } from "./types";

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

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
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
      event.preventDefault();
      return;
    }

    // Only validate fields when providing (not cancelling)
    if (action === "provide" && input?.fields) {
      for (const field of input.fields.itemsList) {
        const fieldValue = formData.get(field.name) as string;

        // Check required fields
        if (field.required && (!fieldValue || fieldValue.trim() === "")) {
          alert(`"${field.label}" is required!`);
          event.preventDefault();
          return;
        }

        // Check pattern validation
        if (field.pattern) {
          if (field.type !== InputFieldType.INPUT_FIELD_TYPE_FILE) {
            if (fieldValue && !new RegExp(`^${field.pattern}$`).test(fieldValue)) {
              alert(
                `The value for "${field.label}" does not match the required pattern!`,
              );
              event.preventDefault();
              return;
            }
          }
        }
      }
    }

    if (!store) {
      alert("Store not available. Please refresh the page.");
      return;
    }
    if (!isGrpcConnected) {
      alert("gRPC not connected. Please wait for connection.");
      return;
    }
    event.preventDefault();
    // Extract value: if fields are defined, use the first field's value;
    // otherwise use the "value" field
    let value = "";
    if (input?.fields && input.fields.itemsList.length > 0) {
      const firstField = input.fields.itemsList[0];
      value = (formData.get(firstField.name) as string) || "";
      if (!value || value.trim() === "") {
        const inputElement = form.querySelector(
          `[name="${firstField.name}"]`,
        ) as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null;
        if (inputElement) {
          value = inputElement.value || "";
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

    if (action === "provide") {
      try {
        const inputResult = new InputResult();
        inputResult.setMethod(InputMethod.INPUT_METHOD_WEB_DASHBOARD);

        const dataMap = inputResult.getDataMap();
        const fileMap = inputResult.getFilesMap();
        for (const [name, value] of formData.entries()) {
          if (!["id", "value", "action"].includes(name)) {
            if (value instanceof File) {
              fileMap.set(name, await value.arrayBuffer());
            } else {
              dataMap.set(name, value as string);
            }
          }
        }

        const inputProvideAction = new InputProvideAction();
        inputProvideAction.setId(id);
        inputProvideAction.setValue(value);
        inputProvideAction.setResult(inputResult);

        const provideAction = new Action();
        provideAction.setInputProvideAction(inputProvideAction);

        const dispatchActionRequest = new DispatchActionRequest();
        dispatchActionRequest.setAction(provideAction);

        await store.dispatchAction(dispatchActionRequest);
      } catch (error) {
        console.error("Error dispatching InputProvideAction:", error);
        alert(`Error submitting form: ${error instanceof Error ? error.message : String(error)}`);
      }
    } else if (action === "cancel") {
      try {
        const inputCancelAction = new InputCancelAction();
        inputCancelAction.setId(id);

        const cancelAction = new Action();
        cancelAction.setInputCancelAction(inputCancelAction);

        const dispatchActionRequest = new DispatchActionRequest();
        dispatchActionRequest.setAction(cancelAction);

        await store.dispatchAction(dispatchActionRequest);
      } catch (error) {
        console.error("Error dispatching InputCancelAction:", error);
        alert(`Error cancelling form: ${error instanceof Error ? error.message : String(error)}`);
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
        <DialogContent sx={{ "&&.MuiDialogContent-root": { pt: 1 } }}>
          <Stack
            component="form"
            autoComplete="off"
            method="POST"
            encType="multipart/form-data"
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
                      <FormHelperText>{field.description}</FormHelperText>
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
                    <FormHelperText>{field.description}</FormHelperText>
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
                        variant={files[field.name] ? "contained" : "outlined"}
                        sx={{ flexGrow: 1, textTransform: "none" }}
                      >
                        <input
                          type="file"
                          id={field.name}
                          name={field.name}
                          required={field.required}
                          accept={field.fileMimetype || "*"}
                          onChange={async (event) => {
                            if (event.target.files?.length) {
                              const file = event.target.files[0];
                              const content = await file.text();
                              setFiles((files) => {
                                if (
                                  !field.pattern ||
                                  new RegExp(field.pattern).test(content)
                                ) {
                                  return {
                                    ...files,
                                    [id]: {
                                      ...files[id],
                                      [field.name]: file,
                                    },
                                  };
                                } else {
                                  alert(
                                    `The file "${file.name}" does not match the required pattern!`,
                                  );
                                  event.target.value = "";
                                  const newFiles = files[id] || {};
                                  delete newFiles[field.name];
                                  return { ...files, [id]: newFiles };
                                }
                              });
                            } else {
                              const newFiles = files[id] || {};
                              delete newFiles[field.name];
                              return { ...files, [id]: newFiles };
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
                      {files[field.name] && (
                        <IconButton
                          sx={{ flexGrow: 0, flexShrink: 0 }}
                          onClick={(event) => {
                            const input =
                              event.currentTarget.previousElementSibling?.querySelector(
                                "input",
                              ) as HTMLInputElement;
                            input.value = "";
                            setFiles((files) => {
                              const newFiles = { ...files };
                              delete newFiles[field.name];
                              return newFiles;
                            });
                          }}
                        >
                          <Clear />
                        </IconButton>
                      )}
                    </Stack>
                    <FormHelperText>{field.description}</FormHelperText>
                  </FormControl>
                ) : (
                  <TextField
                    key={field.name}
                    type={inputFieldTypes[field.type]}
                    name={field.name}
                    label={field.label}
                    helperText={field.description}
                    defaultValue={field.defaultValue || undefined}
                    title={field.title || undefined}
                    required={field.required}
                    fullWidth
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
