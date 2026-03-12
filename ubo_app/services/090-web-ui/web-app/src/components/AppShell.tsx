import { Box, CircularProgress, Typography } from "@mui/material";
import { useEffect, useMemo } from "react";

import { ApplicationView } from "./ApplicationView";
import { Breadcrumb } from "./Breadcrumb";
import { NotificationOverlay } from "./NotificationOverlay";
import { StatusBar } from "./StatusBar";
import { TileGrid } from "./TileGrid";
import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import { useKeyboardNavigation } from "../hooks/useKeyboardNavigation";
import { navigateTo } from "../store/action-dispatcher";
import { splitIconFromText } from "../utils/color-markup";
import { subscribeToAudioEvents } from "../store/audio";
import { unwrapItems } from "../store/helpers";
import {
  StateManager,
  StateManagerContext,
} from "../store/state-manager";
import { useAppState } from "../store/useAppState";

function AppContent({ store }: { store: StoreServiceClient }) {
  const { currentView, statusBar, stack } = useAppState();
  useKeyboardNavigation(store);

  // Auto-navigate past home view to main menu (debounced to avoid rapid-fire)
  useEffect(() => {
    if (currentView?.homeViewData) {
      const timer = setTimeout(() => {
        navigateTo(store, "main");
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [currentView, store]);

  // Derive current title from view data
  const currentTitle = (() => {
    if (!currentView) return "";
    if (currentView.homeViewData) return "Home";
    if (currentView.menuViewData) {
      const { icon, text } = splitIconFromText(currentView.menuViewData.title ?? "");
      return icon ? `${icon}${text}` : text;
    }
    if (currentView.notificationViewData) {
      const { text } = splitIconFromText(currentView.notificationViewData.title ?? "");
      return text;
    }
    if (currentView.applicationViewData) {
      const id = currentView.applicationViewData.applicationId ?? "";
      // Format "camera:viewfinder" → "Viewfinder"
      const parts = id.split(":").filter(Boolean);
      const last = parts[parts.length - 1] || id;
      return last
        .split(/[-_]/)
        .map((w: string) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ");
    }
    return "";
  })();

  // Render content area based on view type
  const content = (() => {
    if (!currentView || currentView.homeViewData) {
      return (
        <Box
          sx={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            py: 8,
            gap: 2,
          }}
        >
          <CircularProgress size={32} />
          <Typography variant="body2" color="text.secondary">
            {currentView?.homeViewData
              ? "Navigating to main menu..."
              : "Connecting to store..."}
          </Typography>
        </Box>
      );
    }

    if (currentView.menuViewData) {
      const menu = currentView.menuViewData;
      return (
        <TileGrid
          items={unwrapItems(menu.items?.itemsList)}
          store={store}
          title={menu.title}
          heading={menu.heading}
          subHeading={menu.subHeading}
        />
      );
    }

    if (currentView.notificationViewData) {
      return (
        <NotificationOverlay
          data={currentView.notificationViewData}
          store={store}
        />
      );
    }

    if (currentView.applicationViewData) {
      return (
        <ApplicationView
          data={currentView.applicationViewData}
          store={store}
        />
      );
    }

    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: "center" }}>
        Unknown view type
      </Typography>
    );
  })();

  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        minHeight: "100vh",
        backgroundColor: "background.default",
      }}
    >
      <StatusBar data={statusBar} store={store} />
      <Breadcrumb stack={stack} currentTitle={currentTitle} store={store} />
      <Box sx={{ flex: 1, p: 2, overflow: "auto" }}>{content}</Box>
    </Box>
  );
}

interface AppShellProps {
  store: StoreServiceClient;
}

export function AppShell({ store }: AppShellProps) {
  const stateManager = useMemo(() => new StateManager(store), [store]);

  // Subscribe to audio events
  useEffect(() => {
    const unsubscribe = subscribeToAudioEvents(store);
    return unsubscribe;
  }, [store]);

  return (
    <StateManagerContext.Provider value={stateManager}>
      <AppContent store={store} />
    </StateManagerContext.Provider>
  );
}
