import { Box, CircularProgress, Typography } from "@mui/material";
import { useEffect, useMemo } from "react";

import { ApplicationView } from "./ApplicationView";
import { BackButton } from "./BackButton";
import { Breadcrumb } from "./Breadcrumb";
import { ChatView } from "./ChatView";
import { Dashboard } from "./dashboard/Dashboard";
import { InstructionView } from "./InstructionView";
import { NotificationOverlay } from "./NotificationOverlay";
import { PromptView } from "./PromptView";
import { RenderView } from "./RenderView";
import { StatusBar } from "./StatusBar";
import { TileGrid } from "./TileGrid";
import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import { useKeyboardNavigation } from "../hooks/useKeyboardNavigation";
import { subscribeToAudioEvents } from "../store/audio";
import { unwrapItems } from "../store/helpers";
import { StateManager, StateManagerContext } from "../store/state-manager";
import { useAppState } from "../store/useAppState";
import { splitIconFromText } from "../utils/color-markup";

function AppContent({ store }: { store: StoreServiceClient }) {
  const { currentView, statusBar, stack } = useAppState();
  useKeyboardNavigation(store);

  // Derive current title (icon + text) from view data
  const { currentTitle, currentTitleIcon, currentTitleText } = (() => {
    if (!currentView) return { currentTitle: "", currentTitleIcon: "", currentTitleText: "" };
    // The dashboard is self-describing; a redundant "Home" heading above it
    // would only eat vertical space.
    if (currentView.homeViewData) return { currentTitle: "Home", currentTitleIcon: "", currentTitleText: "" };
    if (currentView.menuViewData) {
      const { icon, text } = splitIconFromText(currentView.menuViewData.title ?? "");
      return { currentTitle: icon ? `${icon}${text}` : text, currentTitleIcon: icon, currentTitleText: text };
    }
    if (currentView.notificationViewData) {
      const { icon, text } = splitIconFromText(currentView.notificationViewData.title ?? "");
      return { currentTitle: icon ? `${icon}${text}` : text, currentTitleIcon: icon, currentTitleText: text };
    }
    if (currentView.applicationViewData) {
      const id = currentView.applicationViewData.applicationId ?? "";
      const parts = id.split(":").filter(Boolean);
      const last = parts[parts.length - 1] || id;
      const text = last
        .split(/[-_]/)
        .map((w: string) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ");
      return { currentTitle: text, currentTitleIcon: "", currentTitleText: text };
    }
    if (currentView.renderViewData) {
      const text = currentView.renderViewData.title || currentView.renderViewData.kind || "View";
      return { currentTitle: text, currentTitleIcon: "", currentTitleText: text };
    }
    if (currentView.instructionViewData) {
      const text = currentView.instructionViewData.title ?? "Instructions";
      return { currentTitle: text, currentTitleIcon: "", currentTitleText: text };
    }
    if (currentView.promptViewData) {
      const text = currentView.promptViewData.title ?? "Confirm";
      return { currentTitle: text, currentTitleIcon: "", currentTitleText: text };
    }
    if (currentView.chatViewData) {
      return { currentTitle: "Chat", currentTitleIcon: "", currentTitleText: "Chat" };
    }
    return { currentTitle: "", currentTitleIcon: "", currentTitleText: "" };
  })();

  const showBackButton = (stack?.length ?? 0) > 2;

  // Render content area based on view type
  const content = (() => {
    if (!currentView) {
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
            Connecting to store...
          </Typography>
        </Box>
      );
    }

    if (currentView.homeViewData) {
      return <Dashboard store={store} />;
    }

    if (currentView.menuViewData) {
      const menu = currentView.menuViewData;
      return (
        <TileGrid
          items={unwrapItems(menu.items?.itemsList)}
          store={store}
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

    if (currentView.renderViewData) {
      return (
        <RenderView
          data={currentView.renderViewData}
          store={store}
        />
      );
    }

    if (currentView.instructionViewData) {
      return <InstructionView data={currentView.instructionViewData} />;
    }

    if (currentView.promptViewData) {
      return <PromptView data={currentView.promptViewData} store={store} />;
    }

    if (currentView.chatViewData) {
      return <ChatView data={currentView.chatViewData} store={store} />;
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
        height: "100dvh",
        backgroundColor: "background.default",
      }}
    >
      <StatusBar data={statusBar} store={store} />
      <Breadcrumb stack={stack} currentTitle={currentTitle} store={store} />
      <Box sx={{ flex: 1, p: 2, overflow: "auto" }}>
        {(showBackButton || currentTitleText) && (
          <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 2 }}>
            {showBackButton && <BackButton store={store} />}
            {currentTitleText && (
              <Typography variant="h6" fontWeight={600}>
                {currentTitleIcon && (
                  <span style={{ fontFamily: "ArimoNerdFont", marginRight: 8 }}>
                    {currentTitleIcon}
                  </span>
                )}
                {currentTitleText}
              </Typography>
            )}
          </Box>
        )}
        {content}
      </Box>
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
