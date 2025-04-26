import { Clear } from "@mui/icons-material";
import {
  Box,
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

import { DispatchActionRequest } from "./generated/store/v1/store_pb";
import { StoreServiceClient } from "./generated/store/v1/StoreServiceClientPb";
import {
  Action,
  InputCancelAction,
  InputMethod,
  InputProvideAction,
  InputResult,
} from "./generated/ubo/v1/ubo_pb";
import { InputDescription, InputFieldType } from "./types";

export function Inputs({
  inputs,
  isGrpcConnected,
  store,
}: {
  inputs: InputDescription[];
  isGrpcConnected: boolean;
  store: StoreServiceClient | null;
}) {
  const [files, setFiles] = useState<Record<string, File>>({});

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    if (!store || !isGrpcConnected) {
      return;
    }
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const id = formData.get("id") as string;
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
            const filesValue = new InputResult.FilesValue();
            const bytes = await new Promise<Uint8Array>((resolve, reject) => {
              const reader = new FileReader();
              reader.onload = () => {
                if (reader.result instanceof ArrayBuffer) {
                  resolve(new Uint8Array(reader.result));
                } else if (typeof reader.result === "string") {
                  resolve(new TextEncoder().encode(reader.result));
                } else {
                  reject(new Error("Invalid file type"));
                }
              };
              reader.onerror = (error) => {
                console.error("FileReader error", error);
                reject(new Error("Failed to read file"));
              };
              reader.readAsArrayBuffer(value);
            });
            filesValue.setBytes(bytes);
            fileMap.set(name, filesValue);
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

  return inputs.map((input, index) => (
    <Dialog key={input.id} open>
      <DialogTitle>{input.prompt}</DialogTitle>
      <DialogContent>
        <Stack
          component="form"
          autoComplete="off"
          method="POST"
          encType="multipart/form-data"
          gap={2}
          onSubmit={handleSubmit}
        >
          <input name="id" type="hidden" value={input.id} />

          {input.fields?.length ? (
            input.fields.map((field) =>
              field.type === InputFieldType.SELECT ? (
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
                    defaultValue={field.default || ""}
                    displayEmpty
                  >
                    {field.options?.map((option) => (
                      <MenuItem key={option} value={option}>
                        {option}
                      </MenuItem>
                    ))}
                  </Select>
                  {field.description && (
                    <FormHelperText>{field.description}</FormHelperText>
                  )}
                </FormControl>
              ) : field.type === InputFieldType.LONG ? (
                <TextField
                  key={field.name}
                  name={field.name}
                  label={field.label}
                  helperText={field.description}
                  defaultValue={field.default || undefined}
                  title={field.title || undefined}
                  multiline
                  rows={4}
                  slotProps={{
                    htmlInput: {
                      pattern: field.pattern || undefined,
                    },
                  }}
                  required={field.required}
                  fullWidth
                />
              ) : field.type === InputFieldType.CHECKBOX ? (
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
                        defaultValue={field.default || undefined}
                      />
                    }
                  />
                  <FormHelperText>{field.description}</FormHelperText>
                </FormControl>
              ) : field.type === InputFieldType.FILE ? (
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
                        accept={field.pattern || "*"}
                        onChange={(event) => {
                          if (event.target.files?.length) {
                            const file = event.target.files[0];
                            setFiles((files) => ({
                              ...files,
                              [field.name]: file,
                            }));
                          } else {
                            setFiles((files) => {
                              const newFiles = { ...files };
                              delete newFiles[field.name];
                              return newFiles;
                            });
                          }
                        }}
                        hidden
                      />
                      <Typography variant="body2">
                        {files[field.name]
                          ? files[field.name].name
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
                  type={field.type}
                  name={field.name}
                  label={field.label}
                  helperText={field.description}
                  defaultValue={field.default || undefined}
                  title={field.title || undefined}
                  slotProps={{
                    htmlInput: {
                      pattern: field.pattern || undefined,
                    },
                  }}
                  required={field.required}
                  fullWidth
                />
              ),
            )
          ) : input.pattern ? (
            Object.keys(new RegExp(input.pattern).exec("")?.groups || {}).map(
              (groupName) => (
                <FormControl key={groupName} fullWidth>
                  <Box sx={{ display: "flex", alignItems: "center", mb: 1 }}>
                    <Typography variant="subtitle1">{groupName}</Typography>
                  </Box>
                  <TextField type="text" name={groupName} fullWidth />
                </FormControl>
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
  ));
}
