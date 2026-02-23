import { DispatchActionRequest } from "../bindings/store/v1/store_pb";
import { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import {
  Action,
  ExecuteMenuActionAction,
  MenuChooseByIndexAction,
  MenuScrollAction,
  MenuScrollDirection,
  NotificationsClearByIdAction,
  PowerOffAction,
  RebootAction,
  StackPopAction,
  StackPopToRootAction,
  StackPushMenuAction,
} from "../bindings/ubo/v1/ubo_pb";

function dispatch(store: StoreServiceClient, action: Action): void {
  const request = new DispatchActionRequest();
  request.setAction(action);
  store.dispatchAction(request);
}

export function chooseByIndex(
  store: StoreServiceClient,
  index: number,
): void {
  const choose = new MenuChooseByIndexAction();
  choose.setIndex(index);
  const action = new Action();
  action.setMenuChooseByIndexAction(choose);
  dispatch(store, action);
}

export function executeAction(
  store: StoreServiceClient,
  actionId: string,
): void {
  const executeAction = new ExecuteMenuActionAction();
  executeAction.setActionId(actionId);
  const action = new Action();
  action.setExecuteMenuActionAction(executeAction);
  dispatch(store, action);
}

export function dismissNotification(
  store: StoreServiceClient,
  notificationId: string,
): void {
  goBack(store);
  const clearById = new NotificationsClearByIdAction();
  clearById.setId(notificationId);
  const action = new Action();
  action.setNotificationsClearByIdAction(clearById);
  dispatch(store, action);
}

export function goBack(store: StoreServiceClient, count = 1): void {
  const stackPop = new StackPopAction();
  stackPop.setCount(count);
  const action = new Action();
  action.setStackPopAction(stackPop);
  dispatch(store, action);
}

export function goHome(store: StoreServiceClient): void {
  const stackPopToRoot = new StackPopToRootAction();
  const action = new Action();
  action.setStackPopToRootAction(stackPopToRoot);
  dispatch(store, action);
}

export function navigateTo(
  store: StoreServiceClient,
  menuKey: string,
): void {
  const stackPush = new StackPushMenuAction();
  stackPush.setMenuKey(menuKey);
  const action = new Action();
  action.setStackPushMenuAction(stackPush);
  dispatch(store, action);
}

export function scroll(
  store: StoreServiceClient,
  direction: "up" | "down",
): void {
  const menuScroll = new MenuScrollAction();
  menuScroll.setDirection(
    direction === "up"
      ? MenuScrollDirection.MENU_SCROLL_DIRECTION_UP
      : MenuScrollDirection.MENU_SCROLL_DIRECTION_DOWN,
  );
  const action = new Action();
  action.setMenuScrollAction(menuScroll);
  dispatch(store, action);
}

export function powerOff(store: StoreServiceClient): void {
  const powerOffAction = new PowerOffAction();
  const action = new Action();
  action.setPowerOffAction(powerOffAction);
  dispatch(store, action);
}

export function reboot(store: StoreServiceClient): void {
  const rebootAction = new RebootAction();
  const action = new Action();
  action.setRebootAction(rebootAction);
  dispatch(store, action);
}
