import { Box } from "@mui/material";
import { useEffect, useMemo, useRef, useState } from "react";

import { subscribeToBrowserEvents } from "./browser-event-handler";
import { Layout } from "./layout";
import { subscribeToStoreEvents } from "./store-event-handler";
import { DispatchActionRequest } from "../generated/store/v1/store_pb";
import { StoreServiceClient } from "../generated/store/v1/StoreServiceClientPb";
import {
  Action,
  Key,
  KeypadAction,
  KeypadKeyPressAction,
  KeypadKeyReleaseAction,
} from "../generated/ubo/v1/ubo_pb";

export function Display({ store }: { store: StoreServiceClient }) {
  const [canvas, setCanvas] = useState<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (!canvas) return;

    subscribeToStoreEvents(store, canvas);
    return subscribeToBrowserEvents({
      onKeyDown: keyDownHandler,
      onKeyUp: keyUpHandler,
    });
  }, [canvas]);

  const pressedKeys = useMemo(() => new KeypadAction.PressedKeysSetType(), []);

  function keyUpHandler(key: Key) {
    pressedKeys.setItemsList(
      pressedKeys.getItemsList().filter((item) => item !== key),
    );

    const keypadKeyReleaseAction = new KeypadKeyReleaseAction();
    keypadKeyReleaseAction.setKey(key);
    keypadKeyReleaseAction.setPressedKeys(pressedKeys);

    const action = new Action();
    action.setKeypadKeyReleaseAction(keypadKeyReleaseAction);

    const dispatchActionRequest = new DispatchActionRequest();
    dispatchActionRequest.setAction(action);

    store.dispatchAction(dispatchActionRequest);
  }

  function keyDownHandler(key: Key) {
    pressedKeys.addItems(key);

    const keypadKeyPressAction = new KeypadKeyPressAction();
    keypadKeyPressAction.setKey(key);
    keypadKeyPressAction.setPressedKeys(pressedKeys);

    const action = new Action();
    action.setKeypadKeyPressAction(keypadKeyPressAction);

    const dispatchActionRequest = new DispatchActionRequest();
    dispatchActionRequest.setAction(action);

    store.dispatchAction(dispatchActionRequest);
  }

  const touchStartX = useRef(0);
  const touchStartY = useRef(0);
  const touchEndX = useRef(0);
  const touchEndY = useRef(0);

  const handleTouchStart = (event: React.TouchEvent) => {
    touchStartX.current = event.changedTouches[0].screenX;
    touchStartY.current = event.changedTouches[0].screenY;
  };

  const handleTouchEnd = (event: React.TouchEvent) => {
    touchEndX.current = event.changedTouches[0].screenX;
    touchEndY.current = event.changedTouches[0].screenY;
    handleGesture();
  };

  const handleGesture = () => {
    const deltaX = touchEndX.current - touchStartX.current;
    const deltaY = touchEndY.current - touchStartY.current;

    if (Math.abs(deltaX) > Math.abs(deltaY)) {
      if (deltaX < -5) {
        keyDownHandler(Key.KEY_BACK);
        keyUpHandler(Key.KEY_BACK);
      }
    } else {
      if (deltaY > 5) {
        keyDownHandler(Key.KEY_UP);
        keyUpHandler(Key.KEY_UP);
      } else if (deltaY < -5) {
        keyDownHandler(Key.KEY_DOWN);
        keyUpHandler(Key.KEY_DOWN);
      }
    }
  };

  const [ref, setRef] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    const preventDefault = (e: TouchEvent) => e.preventDefault();

    const disableBodyScroll = () => {
      document.addEventListener("touchmove", preventDefault, {
        passive: false,
      });
    };

    const enableBodyScroll = () => {
      document.removeEventListener("touchmove", preventDefault);
    };

    const element = ref;
    if (element) {
      element.addEventListener("touchstart", disableBodyScroll);
      element.addEventListener("touchend", enableBodyScroll);
    }

    return () => {
      if (element) {
        element.removeEventListener("touchstart", disableBodyScroll);
        element.removeEventListener("touchend", enableBodyScroll);
      }
      enableBodyScroll(); // Ensure scrolling is re-enabled on unmount
    };
  }, [ref]);

  return (
    <Box
      ref={setRef}
      sx={{
        position: "relative",
        my: 1,
        mx: "auto",
        py: 2,
        width: "max-content",
      }}
    >
      <Layout
        sx={{ height: 290, mt: 2 }}
        onKeyDown={keyDownHandler}
        onKeyUp={keyUpHandler}
      />
      <canvas
        style={{
          backgroundColor: "black",
          imageRendering: "crisp-edges",
          width: "240px",
          height: "240px",
          position: "absolute",
          top: "16px",
          left: "50%",
          transform: "translateX(-50%)",
        }}
        ref={setCanvas}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      />
    </Box>
  );
}
