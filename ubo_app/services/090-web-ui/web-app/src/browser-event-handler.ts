import { DispatchActionRequest } from "./generated/store/v1/store_pb";
import { StoreServiceClient } from "./generated/store/v1/StoreServiceClientPb";
import {
  Action,
  Key,
  KeypadAction,
  KeypadKeyPressAction,
  KeypadKeyReleaseAction,
} from "./generated/ubo/v1/ubo_pb";

export function subscribeToBrowserEvents(store: StoreServiceClient) {
  const KEYS = {
    "1": Key.KEY_L1,
    "2": Key.KEY_L2,
    "3": Key.KEY_L3,
    Backspace: Key.KEY_HOME,
    ArrowLeft: Key.KEY_BACK,
    h: Key.KEY_BACK,
    ArrowUp: Key.KEY_UP,
    k: Key.KEY_UP,
    ArrowDown: Key.KEY_DOWN,
    j: Key.KEY_DOWN,
  };
  type KeyType = keyof typeof KEYS;

  function isValidKey(key: string): key is KeyType {
    return key in KEYS;
  }

  const pressedKeys = new KeypadAction.PressedKeysSetType();

  function keyUpHandler({ key }: KeyboardEvent) {
    if (isValidKey(key)) {
      pressedKeys.setItemsList(
        pressedKeys.getItemsList().filter((item) => item !== KEYS[key]),
      );

      const keypadKeyReleaseAction = new KeypadKeyReleaseAction();
      keypadKeyReleaseAction.setKey(KEYS[key]);
      keypadKeyReleaseAction.setPressedKeys(pressedKeys);

      const action = new Action();
      action.setKeypadKeyReleaseAction(keypadKeyReleaseAction);

      const dispatchActionRequest = new DispatchActionRequest();
      dispatchActionRequest.setAction(action);

      store.dispatchAction(dispatchActionRequest);
    }
  }

  function keyDownHandler({ key }: KeyboardEvent) {
    if (isValidKey(key)) {
      pressedKeys.addItems(KEYS[key]);

      const keypadKeyPressAction = new KeypadKeyPressAction();
      keypadKeyPressAction.setKey(KEYS[key]);
      keypadKeyPressAction.setPressedKeys(pressedKeys);

      const action = new Action();
      action.setKeypadKeyPressAction(keypadKeyPressAction);

      const dispatchActionRequest = new DispatchActionRequest();
      dispatchActionRequest.setAction(action);

      store.dispatchAction(dispatchActionRequest);
    }
  }

  document.addEventListener("keyup", keyUpHandler);
  document.addEventListener("keydown", keyDownHandler);

  return () => {
    document.removeEventListener("keyup", keyUpHandler);
    document.removeEventListener("keydown", keyDownHandler);
  };
}
