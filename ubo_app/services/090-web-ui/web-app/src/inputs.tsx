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

    if (input?.fields) {
      for (const field of input.fields.itemsList) {
        if (field.pattern) {
          if (field.type !== InputFieldType.INPUT_FIELD_TYPE_FILE) {
            const value = formData.get(field.name) as string;
            if (value && !new RegExp(`^${field.pattern}$`).test(value)) {
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

    if (!store || !isGrpcConnected) {
      return;
    }
    event.preventDefault();
    const value = (formData.get("value") || "") as string;
    const action = (
      (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement
    )?.value;

    if (action === "provide") {
      const inputResult = new InputResult();
      inputResult.setMethod(InputMethod.INPUT_METHOD_WEB_DASHBOARD);

      const dataMap = inputResult.getDataMap();
      const fileMap = inputResult.getFilesMap();
      for (const [name, value] of formData.entries()) {
        if (!["id", "value", "action"].includes(name)) {
          if (value instanceof File) {
            fileMap.set(name, await value.bytes());
          } else {
            dataMap.set(name, value as string);
          }
        }
      }

      const inputProvideAction = new InputProvideAction();
      inputProvideAction.setId(id);
      inputProvideAction.setValue(value);
      inputProvideAction.setResult(inputResult);

      const action = new Action();
      action.setInputProvideAction(inputProvideAction);

      const dispatchActionRequest = new DispatchActionRequest();
      dispatchActionRequest.setAction(action);

      await store.dispatchAction(dispatchActionRequest);
    } else if (action === "cancel") {
      const inputCancelAction = new InputCancelAction();
      inputCancelAction.setId(id);

      const action = new Action();
      action.setInputCancelAction(inputCancelAction);

      const dispatchActionRequest = new DispatchActionRequest();
      dispatchActionRequest.setAction(action);

      await store.dispatchAction(dispatchActionRequest);
    }
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
