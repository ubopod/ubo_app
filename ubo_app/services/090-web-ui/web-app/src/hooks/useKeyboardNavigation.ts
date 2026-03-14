import { useEffect } from "react";

import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import { goBack, goHome, scroll, toggleMicMute } from "../store/action-dispatcher";
import { startBrowserMic, stopBrowserMic } from "../store/audio-input";

export function useKeyboardNavigation(store: StoreServiceClient): void {
  useEffect(() => {
    let vKeyHeld = false;

    function handleKeyDown(e: KeyboardEvent) {
      // Don't capture events from input elements
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT"
      ) {
        return;
      }

      switch (e.key) {
        case "Backspace":
          e.preventDefault();
          goBack(store);
          break;
        case "Escape": {
          // Don't navigate if a MUI overlay is open — let the overlay handle Escape
          const hasOverlay = document.querySelector(
            '[role="tooltip"], [role="menu"], [role="dialog"], .MuiModal-root',
          );
          if (hasOverlay) break;
          e.preventDefault();
          goHome(store);
          break;
        }
        case "ArrowUp":
        case "PageUp": {
          const hasPopover = document.querySelector(".MuiPopover-root");
          if (hasPopover) break;
          // TileGrid handles its own arrow keys — don't also scroll
          if (document.querySelector("[data-tile-grid]")) break;
          // On non-TileGrid pages, focus the back button if available
          const backBtn = document.querySelector<HTMLElement>("[data-back-button]");
          if (backBtn) {
            e.preventDefault();
            backBtn.focus();
          } else {
            e.preventDefault();
            scroll(store, "up");
          }
          break;
        }
        case "ArrowDown":
        case "PageDown": {
          const hasPopover = document.querySelector(".MuiPopover-root");
          if (hasPopover) break;
          if (document.querySelector("[data-tile-grid]")) break;
          e.preventDefault();
          scroll(store, "down");
          break;
        }
        case "m":
        case "M":
          e.preventDefault();
          toggleMicMute(store);
          break;
        case "v":
        case "V":
          if (!vKeyHeld) {
            vKeyHeld = true;
            e.preventDefault();
            startBrowserMic(store);
          }
          break;
      }
    }

    function handleKeyUp(e: KeyboardEvent) {
      if ((e.key === "v" || e.key === "V") && vKeyHeld) {
        vKeyHeld = false;
        e.preventDefault();
        stopBrowserMic(store);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, [store]);
}
