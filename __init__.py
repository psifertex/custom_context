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

from binaryninja.log import log_error
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


if _UI_AVAILABLE:

    class ContextMenuNotification(UIContextNotification):
        """Injects the configured actions into every context menu as it's built."""

        def __init__(self):
            super().__init__()
            # Per-menu bookkeeping of the actions *we* added, keyed by id(menu).
            # The view's context menu object is reused, so this lets us update
            # ordering and remove deselected actions without ever touching the
            # native items the view added itself.
            self._added = {}

        def OnContextMenuCreated(self, context, view, menu):
            try:
                desired = current_actions()
                try:
                    existing = set(dict(menu.getActions()))
                except Exception:
                    existing = set()

                record = self._added.setdefault(id(menu), set())
                # Anything already in the menu that we didn't add is native --
                # leave it strictly alone (don't relocate it, don't remove it).
                native = existing - record

                # Drop actions we previously added that are no longer wanted.
                for action in list(record):
                    if action not in desired:
                        try:
                            menu.removeAction(action)
                        except Exception:
                            pass
                        record.discard(action)

                # Add / refresh the desired actions in the user's order. addAction
                # is an upsert keyed by action name, so re-adding simply updates
                # the ordering when the user has reordered them.
                menu.setGroupOrdering(MENU_GROUP, current_group_order())
                for index, action in enumerate(desired):
                    if action in native:
                        continue  # already present as a native item; don't duplicate
                    menu.addAction(action, MENU_GROUP, min(index, 255))
                    record.add(action)
            except Exception as e:
                log_error("Custom Context: failed to populate context menu: %s" % e)

    class ConfigureDialog(QDialog):
        """Two-pane picker: search/add on the left, ordered selection on the right."""

        def __init__(self, context, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Custom Context")
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

            intro = QLabel(
                "Add registered actions to the right-click context menu. An action "
                "only appears in views where it's valid; elsewhere Binary Ninja hides "
                "it automatically. Names containing '\\' render as submenus.")
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

        def addSelected(self):
            present = self._selectedNames()
            for item in self.available.selectedItems():
                name = item.text()
                if name not in present:
                    self.selected.addItem(QListWidgetItem(name))
                    present.add(name)

        def removeSelected(self):
            for item in self.selected.selectedItems():
                self.selected.takeItem(self.selected.row(item))

        def move(self, delta):
            row = self.selected.currentRow()
            if row < 0:
                return
            new_row = row + delta
            if new_row < 0 or new_row >= self.selected.count():
                return
            item = self.selected.takeItem(row)
            self.selected.insertItem(new_row, item)
            self.selected.setCurrentRow(new_row)

        def saveAndAccept(self):
            chosen = [self.selected.item(i).text() for i in range(self.selected.count())]
            try:
                Settings().set_string_list(SETTING_ACTIONS, chosen,
                                           scope=SettingsScope.SettingsUserScope)
                Settings().set_double(SETTING_ORDER, float(self.orderSpin.value()),
                                      scope=SettingsScope.SettingsUserScope)
            except Exception as e:
                log_error("Custom Context: failed to save settings: %s" % e)
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
            "default": DEFAULT_ORDER,
            "minValue": 0,
            "maxValue": 255,
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
