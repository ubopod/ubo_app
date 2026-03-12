import { Home, NavigateNext } from "@mui/icons-material";
import { Box, Breadcrumbs, Link, Typography } from "@mui/material";
import { useCallback } from "react";

import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import type { StackItemType } from "../bindings/ubo/v1/ubo_pb";
import { goBack, goHome } from "../store/action-dispatcher";
import { splitIconFromText, stripColorMarkup } from "../utils/color-markup";

interface BreadcrumbProps {
  stack: StackItemType.AsObject[];
  currentTitle: string;
  store: StoreServiceClient;
}

function formatId(id: string): string {
  // "camera:viewfinder" → "Viewfinder", "wifi:connection-page" → "Connection Page"
  // Take the last non-empty segment after splitting on ":"
  const parts = id.split(":").filter(Boolean);
  const last = parts[parts.length - 1] || parts[0] || id;
  return last
    .split(/[-_]/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function getStackItemLabel(item: StackItemType.AsObject): string {
  if (item.menuStackItem) {
    const key = item.menuStackItem.menuKey;
    return key ? formatId(key) : "";
  }
  if (item.applicationStackItem) {
    return item.applicationStackItem.applicationId
      ? formatId(item.applicationStackItem.applicationId)
      : "Application";
  }
  if (item.notificationStackItem) {
    return "Notification";
  }
  return "Unknown";
}

export function Breadcrumb({ stack, currentTitle, store }: BreadcrumbProps) {
  const handleHomeClick = useCallback(() => {
    goHome(store);
  }, [store]);

  const handleCrumbClick = useCallback(
    (depth: number) => {
      const popCount = stack.length - depth - 1;
      if (popCount > 0) {
        goBack(store, popCount);
      }
    },
    [stack, store],
  );

  // Don't show breadcrumb if at root
  if (stack.length <= 1) return null;

  return (
    <Box sx={{ px: 2, py: 0.5 }}>
      <Breadcrumbs
        separator={<NavigateNext sx={{ fontSize: 14 }} />}
        sx={{ "& .MuiBreadcrumbs-li": { lineHeight: 1 } }}
      >
        <Link
          component="button"
          variant="caption"
          underline="hover"
          color="text.secondary"
          onClick={handleHomeClick}
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 0.5,
            cursor: "pointer",
          }}
        >
          <Home sx={{ fontSize: 14 }} />
          Home
        </Link>
        {stack.slice(1, -1).map((item, index) => (
          <Link
            key={index}
            component="button"
            variant="caption"
            underline="hover"
            color="text.secondary"
            onClick={() => handleCrumbClick(index + 1)}
            sx={{ cursor: "pointer" }}
          >
            {getStackItemLabel(item)}
          </Link>
        ))}
        {(() => {
          const raw = currentTitle || (stack.length > 0 ? getStackItemLabel(stack[stack.length - 1]) : "");
          const { icon, text } = splitIconFromText(raw);
          return (
            <Typography variant="caption" color="text.primary" fontWeight={600}>
              {icon && (
                <span style={{ fontFamily: "ArimoNerdFont" }}>{icon} </span>
              )}
              {text}
            </Typography>
          );
        })()}
      </Breadcrumbs>
    </Box>
  );
}
