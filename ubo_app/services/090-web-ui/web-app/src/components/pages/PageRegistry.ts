import type { ComponentType } from "react";

import type { ApplicationPageProps } from "./types";

// Custom application-specific pages remain supported as an escape hatch.
// Common views should use RenderViewData and the generic RenderView dispatcher.
export const pageRegistry: Record<string, ComponentType<ApplicationPageProps>> =
  {};
