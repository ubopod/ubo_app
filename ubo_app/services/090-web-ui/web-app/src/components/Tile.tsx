import { ButtonBase, Paper, Typography } from "@mui/material";
import { forwardRef } from "react";

import type { MenuItemData } from "../bindings/ubo/v1/ubo_pb";
import { parseKivyIcon } from "../utils/kivy-markup";

interface TileProps {
  item: MenuItemData.AsObject;
  focused: boolean;
  onActivate: () => void;
}

function deriveLabel(key: string): string {
  return key
    .split(/[_-]/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export const Tile = forwardRef<HTMLButtonElement, TileProps>(
  function Tile({ item, focused, onActivate }, ref) {
    const displayLabel = item.label || deriveLabel(item.key);
    const parsedIcon = item.icon ? parseKivyIcon(item.icon) : null;

    return (
      <ButtonBase
        ref={ref}
        onClick={onActivate}
        focusRipple
        sx={{
          display: "block",
          textAlign: "center",
          borderRadius: 2,
          width: "100%",
        }}
      >
        <Paper
          elevation={focused ? 8 : 2}
          sx={{
            p: 2,
            borderRadius: 2,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            minHeight: 120,
            backgroundColor: item.backgroundColor || "background.paper",
            border: focused ? 2 : 1,
            borderColor: focused ? "primary.main" : "divider",
            borderStyle: "solid",
            transition: "all 0.15s ease",
            "&:hover": {
              borderColor: "primary.light",
              elevation: 6,
            },
          }}
        >
          {parsedIcon && (
            <Typography
              variant="h4"
              sx={{
                mb: 1,
                color: parsedIcon.color || item.color || "text.primary",
                fontFamily: "ArimoNerdFont",
                fontSize: 40,
              }}
            >
              {parsedIcon.icon}
            </Typography>
          )}
          <Typography
            variant="body2"
            sx={{
              color: item.color || "text.primary",
              fontWeight: 500,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              maxWidth: "100%",
            }}
          >
            {displayLabel}
          </Typography>
        </Paper>
      </ButtonBase>
    );
  },
);
