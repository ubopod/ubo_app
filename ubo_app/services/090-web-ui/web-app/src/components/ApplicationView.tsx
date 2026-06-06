import { Box, Paper, Typography } from "@mui/material";

import { pageRegistry } from "./pages/PageRegistry";
import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import type {
  ApplicationViewData,
  BasicType,
} from "../bindings/ubo/v1/ubo_pb";

/**
 * Extract the scalar value from a BasicType oneof.
 */
export function extractBasicValue(
  opt: BasicType.AsObject | undefined,
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
export function extractExtraDataValue(
  value: ApplicationViewData.ExtraDataValue.AsObject,
): string {
  if (value.basicType) {
    return extractBasicValue(value.basicType);
  }
  if (value.list?.itemsList) {
    return value.list.itemsList
      .map((item) => extractBasicValue(item))
      .join(", ");
  }
  return "";
}

interface ApplicationViewProps {
  data: ApplicationViewData.AsObject;
  store: StoreServiceClient;
}

export function ApplicationView({ data, store }: ApplicationViewProps) {
  const SpecializedPage = data.applicationId
    ? pageRegistry[data.applicationId]
    : undefined;

  if (SpecializedPage) {
    return <SpecializedPage data={data} store={store} />;
  }

  return (
    <Box sx={{ width: "100%", p: 2 }}>
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
