import type { ComponentType } from "react";

import { CameraViewfinder } from "./CameraViewfinder";
import { DockerQRCodePage } from "./DockerQRCodePage";
import { RawImageViewer } from "./RawImageViewer";
import { RawTextViewer } from "./RawTextViewer";
import { RPiConnectQRCodePage } from "./RPiConnectQRCodePage";
import { RPiConnectSignInPage } from "./RPiConnectSignInPage";
import type { ApplicationPageProps } from "./types";
import { VideoViewer } from "./VideoViewer";
import { VSCodeQRCodePage } from "./VSCodeQRCodePage";

export const pageRegistry: Record<string, ComponentType<ApplicationPageProps>> =
  {
    "camera:viewfinder": CameraViewfinder,
    "docker:qrcode-page": DockerQRCodePage,
    "vscode:qrcode-page": VSCodeQRCodePage,
    "rpi-connect:qrcode-page": RPiConnectQRCodePage,
    "rpi-connect:signin-page": RPiConnectSignInPage,
    "ubo:raw-image-viewer": RawImageViewer,
    "ubo:raw-text-viewer": RawTextViewer,
    "ubo:video-viewer": VideoViewer,
  };
