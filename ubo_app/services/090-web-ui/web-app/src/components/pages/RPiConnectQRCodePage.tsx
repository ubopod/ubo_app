import { extractBasicValue } from "../ApplicationView";
import { QRCodePage } from "./QRCodePage";
import type { ApplicationPageProps } from "./types";

export function RPiConnectQRCodePage({ data, store }: ApplicationPageProps) {
  const extraMap = data.extraData?.itemsMap ?? [];
  const urlEntry = extraMap.find(([key]) => key === "url");
  const url = urlEntry ? extractBasicValue(urlEntry[1]?.basicType) : "";

  return <QRCodePage title="RPi Connect" url={url} store={store} />;
}
