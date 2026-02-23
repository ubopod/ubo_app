import type { MenuItemData } from "../bindings/ubo/v1/ubo_pb";

/**
 * Proto generates wrapped item types: { items?: MenuItemData.AsObject }.
 * This helper unwraps them into a flat array of MenuItemData.AsObject.
 */
export function unwrapItems(
  itemsList: Array<{ items?: MenuItemData.AsObject }> | undefined,
): MenuItemData.AsObject[] {
  if (!itemsList) return [];
  return itemsList
    .map((wrapper) => wrapper.items)
    .filter((item): item is MenuItemData.AsObject => item != null);
}
