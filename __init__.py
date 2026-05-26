"""Custom Context

Adds arbitrary registered UI actions (anything that can be bound in the
keybindings list) to Binary Ninja's right-click context menu.

The list of actions and their order is configured from
Plugins > Custom Context > Configure Context Menu... and persists in the user
settings. Actions are injected through a UIContextNotification, so changes take
effect on the very next right-click without a restart. Because context menus are
built with inactive actions hidden, each action's own isValid callback decides
where it shows up -- an action you add only appears in views where it's valid.
"""

import json

from binaryninja.log import log_debug, log_error
from binaryninja.settings import Settings
from binaryninja.enums import SettingsScope

try:
    from binaryninjaui import (UIAction, UIActionHandler, Menu, UIContext,
                               UIContextNotification)
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                   QLineEdit, QListWidget, QListWidgetItem,
                                   QPushButton, QSpinBox, QWidget, QDialogButtonBox,
                                   QAbstractItemView)
    _UI_AVAILABLE = True
except ImportError:
    # Running headless: there is nothing for this plugin to do.
    _UI_AVAILABLE = False


SETTING_GROUP = "customContext"
SETTING_ACTIONS = "customContext.actions"
SETTING_ORDER = "customContext.menuOrder"

# Internal menu group key our items live under (keeps them clustered together
# and separated from native groups by separators).
MENU_GROUP = "CustomContextPlugin"

# Action that opens the configuration dialog (also our Plugins menu entry).
CONFIGURE_ACTION = "Custom Context\\Configure Context Menu..."

# Default group position: toward the bottom of the menu so we don't shove
# native items down. Tunable per-user via the dialog / settings.
DEFAULT_ORDER = 200


def current_actions_raw():
    """Ordered list of action names the user has chosen, straight from settings."""
    try:
        return list(Settings().get_string_list(SETTING_ACTIONS))
    except Exception:
        return []


def current_actions():
    """Chosen actions filtered down to ones currently registered."""
    return [a for a in current_actions_raw() if UIAction.isActionRegistered(a)]


def current_group_order():
    """Where our group of actions sits in the menu (0 = top, 255 = bottom)."""
    try:
        return max(0, min(255, int(Settings().get_double(SETTING_ORDER))))
    except Exception:
        return DEFAULT_ORDER


def _log_op_failure(operation, exc, action=None):
    """Low-noise diagnostic for a menu/view API call that we recover from.

    Logged at debug level so it's invisible during normal use, but available
    when chasing a UI-lifecycle or binding issue (e.g. a Python wrapper around
    a freed C++ object, an action name that's been unregistered, or a view
    type whose contextMenu() doesn't behave the way we expect).
    """
    if action is not None:
        log_debug("Custom Context: %s failed for %r: %s" % (operation, action, exc))
    else:
        log_debug("Custom Context: %s failed: %s" % (operation, exc))


def _group_of(menu, action):
    """Which menu group an action belongs to, or None if it can't be determined."""
    try:
        return menu.getGroupForAction(action)
    except Exception as e:
        _log_op_failure("menu.getGroupForAction", e, action=action)
        return None


def sync_menu(menu):
    """Reconcile our group of actions within a single context menu.

    Idempotent and stateless: we recover the items we own by asking the menu
    which actions are in our group (rather than tracking menu/view wrappers,
    which invites the "Internal C++ object already deleted" GC bug). Native
    items are never relocated, duplicated, or removed.
    """
    desired = current_actions()
    try:
        present = dict(menu.getActions())
    except Exception as e:
        _log_op_failure("menu.getActions", e)
        present = {}

    ours = {a for a in present if _group_of(menu, a) == MENU_GROUP}

    # Remove actions we previously added that are no longer wanted.
    for action in ours - set(desired):
        try:
            menu.removeAction(action)
        except Exception as e:
            _log_op_failure("menu.removeAction", e, action=action)

    # Add desired actions in order. addAction is an upsert keyed by name, so
    # re-adding our existing items simply refreshes their ordering. An action
    # already present in a native group is left untouched.
    try:
        menu.setGroupOrdering(MENU_GROUP, current_group_order())
    except Exception as e:
        _log_op_failure("menu.setGroupOrdering", e)
    for index, action in enumerate(desired):
        if action in present and action not in ours:
            continue  # native item with this name -- don't disturb it
        try:
            menu.addAction(action, MENU_GROUP, min(index, 255))
        except Exception as e:
            _log_op_failure("menu.addAction", e, action=action)


if _UI_AVAILABLE:

    class ContextMenuNotification(UIContextNotification):
        """Keeps each view's context menu in sync with the user's configuration.

        Three event-driven hooks cover the lifecycle of a view's menu without ever
        polling (no isValid abuse):

        - OnContextMenuCreated fires once when a view first builds its (persistent)
          context menu, for the linear/graph/hex/types/stack views.
        - OnViewChange fires when the user switches view type inside a frame, so a
          view that was previously cached with stale items gets refreshed the
          moment it becomes current.
        - apply_to_open_views() (called from the config dialog on save) pushes
          changes to the current view of every open frame immediately.
        """

        def OnContextMenuCreated(self, context, view, menu):
            try:
                sync_menu(menu)
            except Exception as e:
                log_error("Custom Context: failed to populate context menu: %s" % e)

        def OnViewChange(self, context, frame, view_type):
            # The view the user just switched to may have been built before the
            # last config change, so refresh its menu on the way in.
            try:
                if frame is None:
                    return
                view = frame.getCurrentViewInterface()
                if view is not None:
                    sync_menu(view.contextMenu())
            except Exception as e:
                log_error("Custom Context: failed to refresh on view change: %s" % e)

    def apply_to_open_views():
        """Re-sync the context menu of every currently open view.

        OnContextMenuCreated only touches views built after a change, so when the
        user edits their selection we walk the already-open tabs/frames and apply
        the change immediately -- no restart or reopen required.
        """
        for ctx in UIContext.allContexts():
            try:
                tabs = ctx.getTabs()
            except Exception as e:
                _log_op_failure("UIContext.getTabs", e)
                continue
            for tab in tabs:
                try:
                    frames = ctx.getAllViewFramesForTab(tab)
                except Exception as e:
                    _log_op_failure("UIContext.getAllViewFramesForTab", e)
                    continue
                for frame in frames:
                    try:
                        view = frame.getCurrentViewInterface()
                    except Exception as e:
                        _log_op_failure("ViewFrame.getCurrentViewInterface", e)
                        view = None
                    if view is None:
                        continue
                    try:
                        sync_menu(view.contextMenu())
                    except Exception as e:
                        _log_op_failure("sync_menu(view.contextMenu()) for open view", e)

    class ConfigureDialog(QDialog):
        """Two-pane picker: search/add on the left, ordered selection on the right."""

        def __init__(self, context, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Custom Context")
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

            intro = QLabel(
                "Add registered actions to the right-click context menu. An action "
                "only appears in views where it's valid; elsewhere Binary Ninja hides "
                "it automatically. Names containing '\\' render as submenus. "
                "Greyed-out actions are already in the right-click menu — hover for "
                "the reason.")
            intro.setWordWrap(True)

            # --- Available actions (left) ---
            self.filterEdit = QLineEdit()
            self.filterEdit.setPlaceholderText("Search actions...")
            self.filterEdit.setClearButtonEnabled(True)
            self.filterEdit.textChanged.connect(self.applyFilter)

            self.available = QListWidget()
            self.available.setSelectionMode(QAbstractItemView.ExtendedSelection)
            self.available.itemDoubleClicked.connect(lambda _item: self.addSelected())
            for name in sorted(UIAction.getAllRegisteredActions()):
                self.available.addItem(QListWidgetItem(name))

            availLayout = QVBoxLayout()
            availLayout.addWidget(QLabel("Available actions"))
            availLayout.addWidget(self.filterEdit)
            availLayout.addWidget(self.available)
            availWidget = QWidget()
            availWidget.setLayout(availLayout)

            # --- Add / remove (middle) ---
            self.addButton = QPushButton("Add →")
            self.addButton.clicked.connect(self.addSelected)
            self.removeButton = QPushButton("← Remove")
            self.removeButton.clicked.connect(self.removeSelected)
            midLayout = QVBoxLayout()
            midLayout.addStretch()
            midLayout.addWidget(self.addButton)
            midLayout.addWidget(self.removeButton)
            midLayout.addStretch()
            midWidget = QWidget()
            midWidget.setLayout(midLayout)

            # --- Selected actions (right) ---
            self.selected = QListWidget()
            self.selected.setSelectionMode(QAbstractItemView.ExtendedSelection)
            self.selected.setDragDropMode(QAbstractItemView.InternalMove)
            self.selected.setDefaultDropAction(Qt.MoveAction)
            self.selected.itemDoubleClicked.connect(lambda _item: self.removeSelected())
            for name in current_actions_raw():
                self.selected.addItem(QListWidgetItem(name))

            # Cache which actions are already present natively in any open view's
            # right-click menu so we can disable them in the available list with
            # an explanation. The set is fixed for the dialog's modal lifetime.
            self._native_actions = self._collect_native_actions()
            self._refresh_available_states()

            self.upButton = QPushButton("Move Up")
            self.upButton.clicked.connect(lambda: self.move(-1))
            self.downButton = QPushButton("Move Down")
            self.downButton.clicked.connect(lambda: self.move(1))
            selButtons = QHBoxLayout()
            selButtons.addWidget(self.upButton)
            selButtons.addWidget(self.downButton)
            selButtons.addStretch()

            selLayout = QVBoxLayout()
            selLayout.addWidget(QLabel("In context menu (top → bottom)"))
            selLayout.addWidget(self.selected)
            selLayout.addLayout(selButtons)
            selWidget = QWidget()
            selWidget.setLayout(selLayout)

            columns = QHBoxLayout()
            columns.addWidget(availWidget, 1)
            columns.addWidget(midWidget)
            columns.addWidget(selWidget, 1)

            # --- Group position ---
            self.orderSpin = QSpinBox()
            self.orderSpin.setRange(0, 255)
            self.orderSpin.setValue(current_group_order())
            orderRow = QHBoxLayout()
            orderRow.addWidget(QLabel("Menu section position (0 = top, 255 = bottom):"))
            orderRow.addWidget(self.orderSpin)
            orderRow.addStretch()

            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(self.saveAndAccept)
            buttons.rejected.connect(self.reject)

            layout = QVBoxLayout()
            layout.addWidget(intro)
            layout.addLayout(columns)
            layout.addLayout(orderRow)
            layout.addWidget(buttons)
            self.setLayout(layout)
            self.resize(780, 560)

        def applyFilter(self, text):
            text = text.strip().lower()
            for i in range(self.available.count()):
                item = self.available.item(i)
                item.setHidden(text not in item.text().lower())

        def _selectedNames(self):
            return {self.selected.item(i).text() for i in range(self.selected.count())}

        def _collect_native_actions(self):
            """Action names already in some open view's right-click menu (not ours)."""
            native = set()
            try:
                contexts = UIContext.allContexts()
            except Exception as e:
                _log_op_failure("UIContext.allContexts (native probe)", e)
                return native
            for ctx in contexts:
                try:
                    tabs = ctx.getTabs()
                except Exception as e:
                    _log_op_failure("UIContext.getTabs (native probe)", e)
                    continue
                for tab in tabs:
                    try:
                        frames = ctx.getAllViewFramesForTab(tab)
                    except Exception as e:
                        _log_op_failure("UIContext.getAllViewFramesForTab (native probe)", e)
                        continue
                    for frame in frames:
                        try:
                            view = frame.getCurrentViewInterface()
                        except Exception as e:
                            _log_op_failure("ViewFrame.getCurrentViewInterface (native probe)", e)
                            continue
                        if view is None:
                            continue
                        try:
                            menu = view.contextMenu()
                            actions = dict(menu.getActions())
                        except Exception as e:
                            _log_op_failure("view.contextMenu().getActions (native probe)", e)
                            continue
                        for a in actions:
                            # Exclude items we ourselves contributed -- those are
                            # captured by the selection check, not the native one.
                            if _group_of(menu, a) != MENU_GROUP:
                                native.add(a)
            return native

        def _refresh_available_states(self):
            """Disable items already in the right-click menu (selected or native)."""
            selected = self._selectedNames()
            for i in range(self.available.count()):
                item = self.available.item(i)
                name = item.text()
                if name in selected:
                    item.setFlags(item.flags() & ~(Qt.ItemIsEnabled | Qt.ItemIsSelectable))
                    item.setToolTip("Already added below — remove it on the right to re-enable.")
                elif name in self._native_actions:
                    item.setFlags(item.flags() & ~(Qt.ItemIsEnabled | Qt.ItemIsSelectable))
                    item.setToolTip("Binary Ninja already shows this in the right-click "
                                    "menu of an open view, so the plugin would skip it "
                                    "to avoid a duplicate.")
                else:
                    item.setFlags(item.flags() | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    item.setToolTip("")

        def addSelected(self):
            present = self._selectedNames()
            for item in self.available.selectedItems():
                name = item.text()
                if name not in present:
                    self.selected.addItem(QListWidgetItem(name))
                    present.add(name)
            self._refresh_available_states()

        def removeSelected(self):
            for item in self.selected.selectedItems():
                self.selected.takeItem(self.selected.row(item))
            self._refresh_available_states()

        def move(self, delta):
            # Move every selected row by `delta` as a block: take each row in the
            # right iteration order (ascending for up, descending for down) and
            # reinsert one position over. Each take/insert is a localised swap
            # with the neighbour that wasn't selected, so the original indices we
            # captured up front stay valid for the remaining iterations. If any
            # selected item is already at the boundary, we bail so the relative
            # ordering of the block is preserved.
            if delta not in (-1, 1):
                return
            rows = sorted(self.selected.row(i) for i in self.selected.selectedItems())
            if not rows:
                return
            if delta < 0 and rows[0] == 0:
                return
            if delta > 0 and rows[-1] == self.selected.count() - 1:
                return

            current_item = self.selected.currentItem()
            iter_rows = rows if delta < 0 else list(reversed(rows))
            moved = []
            for r in iter_rows:
                item = self.selected.takeItem(r)
                self.selected.insertItem(r + delta, item)
                moved.append(item)

            self.selected.clearSelection()
            for item in moved:
                item.setSelected(True)
            if current_item is not None:
                self.selected.setCurrentItem(current_item)

        def saveAndAccept(self):
            chosen = [self.selected.item(i).text() for i in range(self.selected.count())]
            try:
                Settings().set_string_list(SETTING_ACTIONS, chosen,
                                           scope=SettingsScope.SettingsUserScope)
                Settings().set_double(SETTING_ORDER, float(self.orderSpin.value()),
                                      scope=SettingsScope.SettingsUserScope)
            except Exception as e:
                log_error("Custom Context: failed to save settings: %s" % e)
            # Push the change to views that are already open so it takes effect
            # immediately rather than only on newly created views.
            apply_to_open_views()
            self.accept()

    _config_dialog = None

    def launch_configure(context):
        global _config_dialog
        parent = getattr(context, "widget", None) if context is not None else None
        _config_dialog = ConfigureDialog(context, parent=parent)
        _config_dialog.exec()

    _notification = None
    _registered = False

    def register():
        global _notification, _registered
        if _registered:
            return

        Settings().register_group(SETTING_GROUP, "Custom Context")
        Settings().register_setting(SETTING_ACTIONS, json.dumps({
            "title": "Context Menu Actions",
            "type": "array",
            "elementType": "string",
            "default": [],
            "description": "Registered UI actions added to the right-click context "
                           "menu, in order. Edit from Plugins > Custom Context.",
            "ignore": ["SettingsProjectScope", "SettingsResourceScope"],
        }))
        Settings().register_setting(SETTING_ORDER, json.dumps({
            "title": "Context Menu Section Position",
            "type": "number",
            # Declared as a double (note the float literals): the value is read and
            # written with get_double/set_double, and the registered type must agree
            # or the core throws "data_.f.flags & kInt64Flag" on every read.
            "default": float(DEFAULT_ORDER),
            "minValue": 0.0,
            "maxValue": 255.0,
            "description": "Ordering value (0-255) for where the custom action group "
                           "appears in the right-click menu; lower is higher up.",
            "ignore": ["SettingsProjectScope", "SettingsResourceScope"],
        }))

        UIAction.registerAction(CONFIGURE_ACTION)
        UIActionHandler.globalActions().bindAction(CONFIGURE_ACTION,
                                                   UIAction(launch_configure))
        Menu.mainMenu("Plugins").addAction(CONFIGURE_ACTION, "Custom Context")

        _notification = ContextMenuNotification()
        UIContext.registerNotification(_notification)

        _registered = True

    register()
