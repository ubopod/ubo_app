import type {
  ApplicationViewData,
  DockerAppStatus,
  DockerServiceState,
  HomeViewData,
  LocalizationState,
  MenuItemData,
  MenuViewData,
  NotificationViewData,
  SensorDeviceState,
  SensorEntityReading,
  SensorsState,
  StackItemType,
  StatusBarData,
  SystemState,
  ViewData,
  WeatherCondition,
} from "../bindings/ubo/v1/ubo_pb";

export interface AppState {
  currentView: ViewData.AsObject | null;
  statusBar: StatusBarData.AsObject | null;
  stack: StackItemType.AsObject[];
  connected: boolean;
  // Whole state slices, streamed by `SubscribeStore`. `null` until the first
  // frame for that selector arrives.
  system: SystemState.AsObject | null;
  localization: LocalizationState.AsObject | null;
  sensors: SensorsState.AsObject | null;
  docker: DockerServiceState.AsObject | null;
  volume: number;
}

export type {
  ApplicationViewData,
  DockerAppStatus,
  DockerServiceState,
  HomeViewData,
  LocalizationState,
  MenuItemData,
  MenuViewData,
  NotificationViewData,
  SensorDeviceState,
  SensorEntityReading,
  SensorsState,
  StackItemType,
  StatusBarData,
  SystemState,
  ViewData,
  WeatherCondition,
};
