import { Box, Typography , useMediaQuery, useTheme } from "@mui/material";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Tile } from "./Tile";
import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import type { MenuItemData } from "../bindings/ubo/v1/ubo_pb";
import { chooseByIndex, executeAction, navigateTo } from "../store/action-dispatcher";
import { MENU_SELECT_PREFIX } from "../store/constants";
import { parseColorMarkup, stripColorMarkup } from "../utils/color-markup";


interface TileGridProps {
  items: MenuItemData.AsObject[];
  store: StoreServiceClient;
  heading?: string;
  subHeading?: string;
}

export function TileGrid({
  items,
  store,
  heading,
  subHeading,
}: TileGridProps) {
  const [focusIndex, setFocusIndex] = useState(0);
  const tileRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const gridRef = useRef<HTMLDivElement>(null);
  const theme = useTheme();
  const isSmall = useMediaQuery(theme.breakpoints.down("sm"));
  const maxColumns = items.length <= 2 ? items.length : items.length <= 4 ? 2 : 3;
  const columns = isSmall ? Math.min(maxColumns, 2) : maxColumns;

  // Stable identity key derived from item keys — only changes when
  // the actual menu items change, not on every status-bar poll.
  const itemsKey = useMemo(
    () => items.map((i) => i.key).join("\0"),
    [items],
  );

  useEffect(() => {
    setFocusIndex(0);
    // Auto-focus the grid when items change so keyboard events are captured
    gridRef.current?.focus({ preventScroll: true });
  }, [itemsKey]);

  useEffect(() => {
    tileRefs.current[focusIndex]?.focus({ preventScroll: true });
  }, [focusIndex]);

  useEffect(() => {
    // In the two-display kiosk a load-time .focus() no-ops (the compositor's
    // single keyboard focus starts on the other surface), and a click on empty
    // page area lands DOM focus on <body>. Both leave arrow navigation dead
    // until the user presses Tab. So reclaim focus into the grid when the
    // window regains keyboard focus or a click leaves focus on the body —
    // guarded on <body> so clicks on real controls (tiles, back button,
    // dialogs) keep their own focus. requestAnimationFrame lets the click's
    // own focus handling settle first, so we don't fight it.
    const reclaimFocus = () => {
      if (document.visibilityState !== "visible") return;
      requestAnimationFrame(() => {
        const active = document.activeElement;
        if (active && active !== document.body && active !== document.documentElement) {
          return;
        }
        (tileRefs.current[focusIndex] ?? gridRef.current)?.focus({
          preventScroll: true,
        });
      });
    };
    window.addEventListener("focus", reclaimFocus);
    document.addEventListener("visibilitychange", reclaimFocus);
    document.addEventListener("click", reclaimFocus);
    return () => {
      window.removeEventListener("focus", reclaimFocus);
      document.removeEventListener("visibilitychange", reclaimFocus);
      document.removeEventListener("click", reclaimFocus);
    };
  }, [focusIndex]);

  const lastActivateRef = useRef(0);

  const handleActivate = useCallback(
    (item: MenuItemData.AsObject, index: number) => {
      const now = Date.now();
      if (now - lastActivateRef.current < 300) return;
      lastActivateRef.current = now;

      if (item.actionId?.startsWith(MENU_SELECT_PREFIX)) {
        navigateTo(store, item.actionId.slice(MENU_SELECT_PREFIX.length));
      } else if (item.actionId) {
        executeAction(store, item.actionId, item.key || undefined);
      } else {
        chooseByIndex(store, index);
      }
    },
    [store],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const count = items.length;
      if (count === 0) return;

      let next = focusIndex;

      switch (e.key) {
        case "ArrowRight":
          next = (focusIndex + 1) % count;
          e.preventDefault();
          break;
        case "ArrowLeft":
          next = (focusIndex - 1 + count) % count;
          e.preventDefault();
          break;
        case "ArrowDown":
          next = Math.min(focusIndex + columns, count - 1);
          e.preventDefault();
          break;
        case "ArrowUp":
          if (focusIndex < columns) {
            const backBtn = document.querySelector<HTMLElement>("[data-back-button]");
            if (backBtn) {
              backBtn.focus();
              e.preventDefault();
              return;
            }
          }
          next = Math.max(focusIndex - columns, 0);
          e.preventDefault();
          break;
        case "Enter":
          handleActivate(items[focusIndex], focusIndex);
          e.preventDefault();
          return;
        default:
          return;
      }
      setFocusIndex(next);
    },
    [focusIndex, items, columns, handleActivate],
  );

  return (
    <Box sx={{ width: "100%" }}>
      {(heading || subHeading) && (
        <Box sx={{ mb: 2 }}>
          {heading && (
            <Typography variant="overline" color="text.secondary">
              {stripColorMarkup(heading)}
            </Typography>
          )}
          {subHeading && (
            <Typography variant="body2" color="text.secondary" component="div">
              {parseColorMarkup(subHeading).map((seg, i) => (
                <span
                  key={i}
                  style={{
                    color: seg.color || undefined,
                    fontFamily: seg.isIcon ? "ArimoNerdFont" : undefined,
                  }}
                >
                  {seg.text}
                </span>
              ))}
            </Typography>
          )}
        </Box>
      )}
      <Box
        data-tile-grid
        ref={gridRef}
        tabIndex={0}
        onKeyDown={handleKeyDown}
        sx={{
          display: "grid",
          gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
          gap: 2,
          outline: "none",
        }}
      >
        {items.map((item, index) => (
          <Tile
            key={`${item.key || "item"}-${index}`}
            ref={(el) => {
              tileRefs.current[index] = el;
            }}
            item={item}
            focused={focusIndex === index}
            onActivate={() => handleActivate(item, index)}
          />
        ))}
      </Box>
    </Box>
  );
}
