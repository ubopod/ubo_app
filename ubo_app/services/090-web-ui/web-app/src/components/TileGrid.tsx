import { Box, Typography } from "@mui/material";
import { useCallback, useEffect, useRef, useState } from "react";

import { Tile } from "./Tile";
import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import type { MenuItemData } from "../bindings/ubo/v1/ubo_pb";
import { chooseByIndex, executeAction, navigateTo } from "../store/action-dispatcher";
import { splitIconFromText, stripKivyMarkup } from "../utils/kivy-markup";


interface TileGridProps {
  items: MenuItemData.AsObject[];
  store: StoreServiceClient;
  title?: string;
  heading?: string;
  subHeading?: string;
}

export function TileGrid({
  items,
  store,
  title,
  heading,
  subHeading,
}: TileGridProps) {
  const [focusIndex, setFocusIndex] = useState(0);
  const tileRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const columns = items.length <= 2 ? items.length : items.length <= 4 ? 2 : 3;

  useEffect(() => {
    setFocusIndex(0);
  }, [items]);

  useEffect(() => {
    tileRefs.current[focusIndex]?.focus();
  }, [focusIndex]);

  const handleActivate = useCallback(
    (item: MenuItemData.AsObject, index: number) => {
      if (item.actionId?.startsWith("menu:select:")) {
        navigateTo(store, item.actionId.slice("menu:select:".length));
      } else if (item.actionId) {
        executeAction(store, item.actionId);
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
      {(title || heading) && (
        <Box sx={{ mb: 2 }}>
          {heading && (
            <Typography variant="overline" color="text.secondary">
              {stripKivyMarkup(heading)}
            </Typography>
          )}
          {title && (() => {
            const { icon, text } = splitIconFromText(title);
            return (
              <Typography variant="h6" fontWeight={600}>
                {icon && (
                  <span style={{ fontFamily: "ArimoNerdFont", marginRight: 8 }}>
                    {icon}
                  </span>
                )}
                {text}
              </Typography>
            );
          })()}
          {subHeading && (
            <Typography variant="body2" color="text.secondary">
              {stripKivyMarkup(subHeading)}
            </Typography>
          )}
        </Box>
      )}
      <Box
        onKeyDown={handleKeyDown}
        sx={{
          display: "grid",
          gridTemplateColumns: `repeat(${columns}, 1fr)`,
          gap: 2,
        }}
      >
        {items.map((item, index) => (
          <Tile
            key={item.key || index}
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
