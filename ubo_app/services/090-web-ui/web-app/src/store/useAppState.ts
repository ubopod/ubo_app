import { useEffect, useState } from "react";

import { useStateManager } from "./state-manager";
import type { AppState } from "./types";

export function useAppState(): AppState {
  const manager = useStateManager();
  const [state, setState] = useState<AppState>(manager.getState());

  useEffect(() => {
    return manager.subscribe(setState);
  }, [manager]);

  return state;
}
