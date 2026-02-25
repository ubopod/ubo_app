import { ArrowBack } from "@mui/icons-material";
import { Box, IconButton, Paper, Typography } from "@mui/material";

import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import type {
  ApplicationViewData,
  BasicTypeOptional,
} from "../bindings/ubo/v1/ubo_pb";
import { goBack } from "../store/action-dispatcher";

/**
 * Extract the scalar value from a BasicTypeOptional oneof.
 */
function extractBasicValue(
  opt: BasicTypeOptional.AsObject | undefined,
): string {
  if (!opt) return "";
  if (opt.string) return opt.string;
  if (opt.int64) return String(opt.int64);
  if (opt.pb_float) return String(opt.pb_float);
  if (opt.bool !== undefined) return String(opt.bool);
  if (opt.bytes) return String(opt.bytes);
  return "";
}

/**
 * Extract a display string from an ExtraDataValue.
 */
function extractExtraDataValue(
  value: ApplicationViewData.ExtraDataValue.AsObject,
): string {
  if (value.basicType?.items) {
    return extractBasicValue(value.basicType.items);
  }
  if (value.list?.itemsList) {
    return value.list.itemsList
      .map((item) => extractBasicValue(item.items))
      .join(", ");
  }
  return "";
}

interface ApplicationViewProps {
  data: ApplicationViewData.AsObject;
  store: StoreServiceClient;
}

export function ApplicationView({ data, store }: ApplicationViewProps) {
  return (
    <Box sx={{ width: "100%", p: 2 }}>
      <Box sx={{ display: "flex", alignItems: "center", mb: 2, gap: 1 }}>
        <IconButton size="small" onClick={() => goBack(store)}>
          <ArrowBack />
        </IconButton>
        <Typography variant="h6">
          {data.applicationId || "Application"}
        </Typography>
      </Box>
      <Paper sx={{ p: 3, borderRadius: 2, textAlign: "center" }}>
        <Typography variant="body2" color="text.secondary">
          Application: {data.applicationId}
        </Typography>
        {data.extraData?.itemsMap && (
          <Box sx={{ mt: 2, textAlign: "left" }}>
            {data.extraData.itemsMap.map(([key, value]) => (
              <Typography
                key={key}
                variant="body2"
                sx={{ fontFamily: "monospace" }}
              >
                {key}: {extractExtraDataValue(value)}
              </Typography>
            ))}
          </Box>
        )}
      </Paper>
    </Box>
  );
}
