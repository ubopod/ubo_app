import { useEffect, useState } from "react";
import { DispatchActionRequest } from "./generated/store/v1/store_pb";
import { StoreServiceClient } from "./generated/store/v1/StoreServiceClientPb";
import {
  Action,
  Notification,
  NotificationsAddAction,
  ReadableInformation,
} from "./generated/ubo/v1/ubo_pb";
import { subscribeToBrowserEvents } from "./browser-event-handler";
import { subscribeToStoreEvents } from "./store-event-handler";

async function dispatchNotification(store: StoreServiceClient) {
  const extraInformation = new ReadableInformation();
  extraInformation.setText(
    "Web UI is ready and connected, to use it open this url in your browser: http://{{hostname}}:4321",
  );
  extraInformation.setPiperText(
    "Web UI is ready and connected, to use it open this url in your browser.",
  );
  extraInformation.setPicovoiceText(
    "Web UI is ready and connected, to use it open this url in your browser.",
  );

  const notification = new Notification();
  notification.setTitle("Web UI");
  notification.setContent(
    "Web UI connected - you can use it on http://{{hostname}}:4321",
  );
  notification.setExtraInformation(extraInformation);

  const notificationsAddAction = new NotificationsAddAction();
  notificationsAddAction.setNotification(notification);

  const action = new Action();
  action.setNotificationsAddAction(notificationsAddAction);

  const dispatchActionRequest = new DispatchActionRequest();
  dispatchActionRequest.setAction(action);

  await store.dispatchAction(dispatchActionRequest);
}

export function Display({ store }: { store: StoreServiceClient }) {
  const [canvas, setCanvas] = useState<HTMLCanvasElement | null>(null);
  useEffect(() => {
    if (!canvas) return;

    dispatchNotification(store);
    subscribeToStoreEvents(store, canvas);
    return subscribeToBrowserEvents(store);
  }, [canvas]);

  return (
    <canvas
      style={{
        backgroundColor: "black",
        display: "block",
        margin: "auto",
        imageRendering: "crisp-edges",
      }}
      ref={setCanvas}
    />
  );
}
