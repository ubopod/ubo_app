import { ArrowBack } from "@mui/icons-material";
import { IconButton } from "@mui/material";
import { useCallback } from "react";

import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import { goBack } from "../store/action-dispatcher";

interface BackButtonProps {
  store: StoreServiceClient;
}

export function BackButton({ store }: BackButtonProps) {
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      switch (e.key) {
        case "Enter":
        case " ":
          goBack(store);
          e.preventDefault();
          break;
        case "ArrowDown": {
          const grid = document.querySelector<HTMLElement>("[data-tile-grid]");
          if (grid) {
            const firstButton = grid.querySelector<HTMLElement>("button");
            (firstButton ?? grid).focus();
            e.preventDefault();
            break;
          }
          const notifActions = document.querySelector<HTMLElement>("[data-notification-actions]");
          if (notifActions) {
            const firstButton = notifActions.querySelector<HTMLElement>("button");
            (firstButton ?? notifActions).focus();
            e.preventDefault();
            break;
          }
          e.preventDefault();
          break;
        }
      }
    },
    [store],
  );

  return (
    <IconButton
      data-back-button
      onClick={() => goBack(store)}
      onKeyDown={handleKeyDown}
      size="large"
      sx={{
        minWidth: 48,
        minHeight: 48,
        borderRadius: 2,
        border: "2px solid transparent",
        "&:focus-visible": {
          borderColor: "primary.main",
          boxShadow: 2,
        },
      }}
    >
      <ArrowBack />
    </IconButton>
  );
}
