import { ButtonBase, Paper, Typography } from "@mui/material";
import { useEffect, useRef } from "react";

import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import { executeAction, navigateTo } from "../store/action-dispatcher";
import { MENU_SELECT_PREFIX } from "../store/constants";
import { useAppState } from "../store/useAppState";
import { parseColoredIcon, stripColorMarkup } from "../utils/color-markup";

// The device's home menu offers Main, Notifications and Power. The web UI shows
// only Main: its status bar already carries a notification bell and a power
// menu, so the other two would be duplicate controls. The device's own home
// screen is unaffected — this is a client-side choice, not a change to
// `HOME_MENU_ID`.
const MAIN_ITEM_KEY = "main";

/**
 * The single navigation affordance on the dashboard.
 *
 * Takes keyboard focus on mount so the arrow keys and Enter have somewhere to
 * land — on the kiosk display nothing else on the page is focusable.
 */
export function MainMenuTile({ store }: { store: StoreServiceClient }) {
  const { currentView } = useAppState();
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    buttonRef.current?.focus({ preventScroll: true });
  }, []);

  const items = currentView?.homeViewData?.menuItems?.itemsList ?? [];
  const item = items.find((candidate) => candidate.key === MAIN_ITEM_KEY);

  if (!item) return null;

  const label = stripColorMarkup(item.label || "Main Menu");
  const parsedIcon = item.icon ? parseColoredIcon(item.icon) : null;

  const activate = () => {
    if (!item.actionId) return;
    if (item.actionId.startsWith(MENU_SELECT_PREFIX)) {
      navigateTo(store, item.actionId.slice(MENU_SELECT_PREFIX.length));
      return;
    }
    executeAction(store, item.actionId, item.key || undefined);
  };

  return (
    <ButtonBase
      ref={buttonRef}
      onClick={activate}
      focusRipple
      sx={{ display: "block", width: "100%", borderRadius: 2, textAlign: "left" }}
    >
      {/* Same fill and ink as the menu tiles in `Tile.tsx`, so the one
          navigation control on the dashboard reads as the same kind of thing
          it turns into. */}
      <Paper
        elevation={2}
        sx={{
          px: 2.5,
          py: 1.75,
          borderRadius: 2,
          border: 1,
          borderColor: "divider",
          borderStyle: "solid",
          backgroundColor: item.backgroundColor || "#1976d2",
          display: "flex",
          alignItems: "center",
          gap: 1.5,
          transition: "all 0.15s ease",
          "&:hover": { borderColor: "primary.light" },
        }}
      >
        {parsedIcon && (
          <Typography
            component="span"
            sx={{
              fontFamily: "ArimoNerdFont",
              fontSize: 26,
              color: parsedIcon.color || item.color || "#ffffff",
              lineHeight: 1,
            }}
          >
            {parsedIcon.icon}
          </Typography>
        )}
        <Typography
          variant="subtitle1"
          fontWeight={600}
          sx={{ color: item.color || "#ffffff" }}
        >
          {label}
        </Typography>
      </Paper>
    </ButtonBase>
  );
}
