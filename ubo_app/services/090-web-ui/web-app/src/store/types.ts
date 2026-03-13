import type {
  ApplicationViewData,
  HomeViewData,
  MenuItemData,
  MenuViewData,
  NotificationViewData,
  StackItemType,
  StatusBarData,
  ViewData,
} from "../bindings/ubo/v1/ubo_pb";

export interface AppState {
  currentView: ViewData.AsObject | null;
  statusBar: StatusBarData.AsObject | null;
  stack: StackItemType.AsObject[];
  connected: boolean;
  cpuPercent: number;
  ramPercent: number;
  volume: number;
}

export type {
  ApplicationViewData,
  HomeViewData,
  MenuItemData,
  MenuViewData,
  NotificationViewData,
  StackItemType,
  StatusBarData,
  ViewData,
};
