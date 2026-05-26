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

Your selections are saved to user settings and take effect on the next
right-click — no restart needed.

### Notes

- Actions appear only in views where they're valid. Binary Ninja builds context
  menus with inactive actions hidden, so each action's own `isValid` logic decides
  where it shows up (e.g. a function-only action won't clutter the hex view).
- Action names that contain `\` (such as `Patch\Convert to NOP`) render as
  submenus, exactly as they appear elsewhere in the menus.
- Actions that are already part of a view's native context menu are left
  untouched rather than duplicated.

## How it works

The plugin registers a `UIContextNotification` and implements
`OnContextMenuCreated`, injecting the configured actions (by their real
registered names, in your chosen order, under a dedicated menu group) every time
a context menu is built.

## Minimum Version

4000

## License

This plugin is released under an [MIT license](./LICENSE).

## Metadata Version

2
