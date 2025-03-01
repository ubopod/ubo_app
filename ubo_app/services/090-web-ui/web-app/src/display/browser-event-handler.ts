import { Key } from "../generated/ubo/v1/ubo_pb";

export function subscribeToBrowserEvents({
  onKeyUp,
  onKeyDown,
}: {
  onKeyUp: (key: Key) => void;
  onKeyDown: (key: Key) => void;
}) {
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

  function keyUpHandler({ key }: KeyboardEvent) {
    if (isValidKey(key)) {
      onKeyUp(KEYS[key]);
    }
  }

  function keyDownHandler({ key }: KeyboardEvent) {
    if (isValidKey(key)) {
      onKeyDown(KEYS[key]);
    }
  }

  document.addEventListener("keyup", keyUpHandler);
  document.addEventListener("keydown", keyDownHandler);

  return () => {
    document.removeEventListener("keyup", keyUpHandler);
    document.removeEventListener("keydown", keyDownHandler);
  };
}
