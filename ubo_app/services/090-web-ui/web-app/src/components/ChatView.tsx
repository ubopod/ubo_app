import { Send } from "@mui/icons-material";
import { Box, IconButton, Stack, TextField } from "@mui/material";
import { useEffect, useRef, useState } from "react";

import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import type { ChatBubbleData, ChatViewData } from "../bindings/ubo/v1/ubo_pb";
import { sendChatMessage, toggleChatAudio } from "../store/action-dispatcher";

interface ChatViewProps {
  data: ChatViewData.AsObject;
  store: StoreServiceClient;
}

// Typed chat is not wired yet — hide the composer; chat is voice-only for now.
// Flip to true to re-enable the text input field.
const SHOW_CHAT_INPUT: boolean = false;

function Waveform({
  bars,
  color,
  isPlaying,
}: {
  bars: number[];
  color: string;
  isPlaying: boolean;
}) {
  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "center",
        gap: "2px",
        height: 28,
        minWidth: 140,
      }}
    >
      {bars.map((value, index) => (
        <Box
          key={index}
          sx={{
            flex: 1,
            borderRadius: "2px",
            height: `${Math.max(8, Math.min(1, value) * 100)}%`,
            backgroundColor: color,
            // is_playing only changes opacity — no animation, so the view
            // stays deterministic.
            opacity: isPlaying ? 1 : 0.4,
          }}
        />
      ))}
    </Box>
  );
}

function ChatBubble({
  bubble,
  store,
}: {
  bubble: ChatBubbleData.AsObject;
  store: StoreServiceClient;
}) {
  const isUser = bubble.alignment === "right";
  const isAudio = bubble.kind === "audio";
  const background = bubble.backgroundColor || "#2b2f38";
  const foreground = bubble.color || "#ffffff";
  const waveform = bubble.waveform?.itemsList ?? [];

  return (
    <Box
      sx={{
        display: "flex",
        justifyContent: isUser ? "flex-end" : "flex-start",
      }}
    >
      <Box
        // On the device an audio bubble is played via its L1/L2/L3 button;
        // the web client has no hardware buttons, so the bubble is clicked
        // directly to toggle playback.
        onClick={
          isAudio
            ? () => toggleChatAudio(store, bubble.messageId ?? "")
            : undefined
        }
        sx={{
          maxWidth: "78%",
          px: 1.5,
          py: 1,
          borderRadius: 2,
          backgroundColor: background,
          color: foreground,
          cursor: isAudio ? "pointer" : "default",
        }}
      >
        {isAudio ? (
          <Waveform
            bars={waveform}
            color={foreground}
            isPlaying={Boolean(bubble.isPlaying)}
          />
        ) : (
          <Box
            component="span"
            sx={{ whiteSpace: "pre-wrap", fontSize: 14, lineHeight: 1.35 }}
          >
            {bubble.text}
          </Box>
        )}
      </Box>
    </Box>
  );
}

export function ChatView({ data, store }: ChatViewProps) {
  const bubbles = data.bubbles?.itemsList ?? [];
  const endRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState("");

  // Keep the newest message in view as the conversation grows.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [bubbles.length]);

  const send = () => {
    const text = draft.trim();
    if (!text) return;
    sendChatMessage(store, text);
    setDraft("");
  };

  return (
    // Natural-height column: a capped, scrollable bubble list above a
    // fixed input row. Not height:100% — the content area also holds the
    // "← Chat" title block, so a full-height column would push the input
    // off the bottom of the viewport.
    <Box sx={{ display: "flex", flexDirection: "column", width: "100%" }}>
      <Stack
        spacing={1}
        sx={{ maxHeight: "60vh", overflowY: "auto", mb: 1.5 }}
      >
        {bubbles.map((bubble, index) => (
          <ChatBubble
            key={bubble.messageId || `bubble-${index}`}
            bubble={bubble}
            store={store}
          />
        ))}
        <div ref={endRef} />
      </Stack>
      {SHOW_CHAT_INPUT && (
        <Box sx={{ display: "flex", gap: 1 }}>
          <TextField
            fullWidth
            size="small"
            placeholder="Type a message…"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                send();
              }
            }}
          />
          <IconButton
            color="primary"
            onClick={send}
            disabled={draft.trim().length === 0}
            aria-label="Send message"
          >
            <Send />
          </IconButton>
        </Box>
      )}
    </Box>
  );
}
