import { extractBasicValue } from "../ApplicationView";
import { QRCodePage } from "./QRCodePage";
import type { ApplicationPageProps } from "./types";

export function VSCodeQRCodePage({ data, store }: ApplicationPageProps) {
  const extraMap = data.extraData?.itemsMap ?? [];
  const urlEntry = extraMap.find(([key]) => key === "url");
  const url = urlEntry ? extractBasicValue(urlEntry[1]?.basicType) : "";

  return <QRCodePage title="VSCode Remote" url={url} store={store} />;
}
