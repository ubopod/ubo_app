import type { ComponentType } from "react";

import type { ApplicationPageProps } from "./types";
import { CameraViewfinder } from "./CameraViewfinder";

export const pageRegistry: Record<string, ComponentType<ApplicationPageProps>> =
  {
    "camera:viewfinder": CameraViewfinder,
  };
