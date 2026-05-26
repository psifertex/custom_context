# Custom Context
Author: **Jordan Wiens**

_Add arbitrary actions to the right-click context menu._

## Description

Binary Ninja registers a large number of UI actions — everything you can see and
bind in the keybindings list. Most are reachable only via a hotkey or a top-level
menu. **Custom Context** lets you surface any of them directly in the right-click
context menu so they're a click away wherever you're working.

Open **Plugins ▸ Custom Context ▸ Configure Context Menu…** to pick actions:

- **Search** the full list of registered actions and **Add →** the ones you want.
- **Reorder** your selections (Move Up / Move Down, or drag-and-drop) and
  **Remove** any you no longer need.
- Choose where the block of custom actions sits in the menu with the
  **section position** control (0 = top, 255 = bottom).

Your selections are saved to user settings and applied immediately — no restart
needed. Clicking **OK** refreshes the menus of all open views, and any view
opened afterward picks up the configuration as well.

### Notes

- Works in the linear, graph, hex, types, and stack views (the views Binary Ninja
  exposes a context-menu hook for).
- Actions appear only where they're valid. Binary Ninja builds context menus with
  inactive actions hidden, so each action's own `isValid` logic decides where it
  shows up (e.g. a function-only action won't clutter the hex view).
- Action names that contain `\` (such as `Patch\Convert to NOP`) render as
  submenus, exactly as they appear elsewhere in the menus.
- Actions that are already part of a view's native context menu are left
  untouched rather than duplicated.

## How it works

The plugin registers a `UIContextNotification` and reconciles each view's
context menu via three event-driven hooks (no polling / no `isValid` abuse):

- `OnContextMenuCreated` — fires once when a view first builds its (persistent)
  context menu; adds the configured actions for that view.
- `OnViewChange` — fires when you switch view type within a frame (e.g.
  linear ↔ graph), refreshing the now-current view in case it was previously
  cached with stale items.
- On dialog save — walks the open tabs/frames and re-applies the change
  directly, so updates are immediate without a restart.

The sync is stateless and idempotent: the plugin recovers its own items from a
menu by querying the menu group, rather than tracking object identity (which
avoids the "Internal C++ object already deleted" GC trap when wrappers churn).

## Minimum Version

4000

## License

This plugin is released under an [MIT license](./LICENSE).

## Metadata Version

2
