import { useEffect } from "react";

import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import { goBack, goHome, scroll } from "../store/action-dispatcher";

export function useKeyboardNavigation(store: StoreServiceClient): void {
  useEffect(() => {
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
        case "PageUp":
          e.preventDefault();
          scroll(store, "up");
          break;
        case "PageDown":
          e.preventDefault();
          scroll(store, "down");
          break;
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [store]);
}
