import contextlib
import threading
from datetime import datetime
from typing import Any, override

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QMouseEvent
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from client.core.client_state import (
    ACCESS_ASK,
    ACCESS_FULL,
    ACCESS_READ_ONLY,
    HYPER_OLLAMA_URL,
    MODEL_LOCAL,
    MODEL_OLLAMA,
    MODEL_OPENAI,
    MODEL_OPENROUTER,
)
from client.core.model_catalog import (
    fetch_ollama_models,
    fetch_openai_models,
    fetch_openrouter_models,
)
from client.ui.qt_blocks import CommandGroupBlock, PaperPlaneButton, StreamTextBlock


class PromptTextEdit(QPlainTextEdit):
    submitted = pyqtSignal()

    @override
    def keyPressEvent(self, event) -> None:
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            event.accept()
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class ClearableListWidget(QListWidget):
    @override
    def mousePressEvent(self, event) -> None:
        if self.itemAt(event.position().toPoint()) is None:
            self.clearSelection()
            self.setCurrentRow(-1)
            event.accept()
            return
        super().mousePressEvent(event)


class LoginPage(QWidget):
    login_requested = pyqtSignal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.login_input = QLineEdit()
        self.password_input = QLineEdit()
        self.login_button = QPushButton("Login")
        self.error_label = QLabel("")
        self._build()
        QTimer.singleShot(0, self.setFocus)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress:
            focus_widget = self.focusWidget()
            if focus_widget is not None:
                focus_widget.clearFocus()
            self.setFocus()
        return super().eventFilter(watched, event)

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        focus_widget = self.focusWidget()
        if focus_widget is not None:
            focus_widget.clearFocus()
        self.setFocus()
        super().mousePressEvent(event)

    def set_credentials(self, login: str, password: str) -> None:
        self.login_input.setText(login)
        self.password_input.setText(password)

    def clear_credentials(self) -> None:
        self.login_input.clear()
        self.password_input.clear()

    def set_busy(self, busy: bool) -> None:
        self.login_button.setDisabled(busy)
        self.login_input.setDisabled(busy)
        self.password_input.setDisabled(busy)
        self.login_button.setText("Connecting..." if busy else "Login")

    def show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()
        self.set_busy(False)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)

        panel = QFrame()
        panel.setObjectName("loginPanel")
        panel.setMaximumWidth(380)
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(30, 28, 30, 28)
        layout.setSpacing(14)

        title = QLabel("Кодобольный AI")
        title.setObjectName("loginTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("Hyperagent workspace")
        subtitle.setObjectName("loginSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        login_label = QLabel("Login")
        login_label.setObjectName("inputLabel")
        password_label = QLabel("Password")
        password_label.setObjectName("inputLabel")

        self.login_input.setPlaceholderText("Login")
        self.login_input.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.password_input.setPlaceholderText("Password")
        self.password_input.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.returnPressed.connect(self._submit)
        self.login_button.setObjectName("primaryButton")
        self.login_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_button.clicked.connect(self._submit)

        self.error_label.setObjectName("errorLabel")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(login_label)
        layout.addWidget(self.login_input)
        layout.addWidget(password_label)
        layout.addWidget(self.password_input)
        layout.addWidget(self.error_label)
        layout.addSpacing(2)
        layout.addWidget(self.login_button)
        root.addWidget(panel)

        for widget in (panel, title, subtitle, login_label, password_label):
            widget.installEventFilter(self)

    def _submit(self) -> None:
        login = self.login_input.text().strip()
        password = self.password_input.text()
        if not login or not password:
            self.show_error("Введите логин и пароль.")
            return
        self.error_label.hide()
        self.set_busy(True)
        self.login_requested.emit(login, password)


class ChatListPage(QWidget):
    chat_opened = pyqtSignal(int, str)
    create_chat_requested = pyqtSignal()
    rename_chat_requested = pyqtSignal(int, str)
    settings_requested = pyqtSignal()
    logout_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.chat_list = ClearableListWidget()
        self._chat_titles: dict[int, str] = {}
        self.new_chat_button = QPushButton("+ New Chat")
        self.menu_button = _account_menu_button(
            logout_callback=self.logout_requested.emit,
            rename_callback=self._rename_selected_chat,
            settings_callback=self.settings_requested.emit,
        )
        self._build()

    def set_chats(self, chats: list[dict[str, Any]], current_chat_id: int | None = None) -> None:
        self.chat_list.clear()
        self._chat_titles.clear()
        for chat in chats:
            chat_id = int(chat["id"])
            title = str(chat.get("title") or "NewChat")
            updated_at = _format_chat_timestamp(chat.get("updated_at"))
            item_text = f"{title}\n{updated_at}" if updated_at else title
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, chat_id)
            item.setToolTip(item_text)
            self.chat_list.addItem(item)
            self._chat_titles[chat_id] = title
            if current_chat_id == chat_id:
                self.chat_list.setCurrentItem(item)

    def set_new_chat_enabled(self, enabled: bool) -> None:
        self.new_chat_button.setEnabled(enabled)
        self.new_chat_button.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
        )

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("topBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 12, 14, 10)
        header_layout.setSpacing(8)

        title = QLabel("Кодобольный AI")
        title.setObjectName("screenTitle")
        self.new_chat_button.setObjectName("flatButton")
        self.new_chat_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_chat_button.clicked.connect(self.create_chat_requested.emit)

        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.new_chat_button)
        header_layout.addWidget(self.menu_button)

        self.chat_list.setObjectName("chatList")
        self.chat_list.itemDoubleClicked.connect(self._open_item)

        root.addWidget(header)
        root.addWidget(self.chat_list, 1)

    def _open_item(self, item: QListWidgetItem) -> None:
        chat_id = int(item.data(Qt.ItemDataRole.UserRole))
        self.chat_opened.emit(chat_id, self._chat_titles.get(chat_id, item.text()))

    def _rename_selected_chat(self) -> None:
        item = self.chat_list.currentItem()
        if item is None:
            return
        chat_id = int(item.data(Qt.ItemDataRole.UserRole))
        self.rename_chat_requested.emit(chat_id, self._chat_titles.get(chat_id, item.text()))


class SettingsPage(QWidget):
    back_requested = pyqtSignal()
    save_requested = pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.model_group = QButtonGroup(self)
        self.theme_group = QButtonGroup(self)
        self.local_radio = QRadioButton("Hyper")
        self.openrouter_radio = QRadioButton("OpenRouter")
        self.ollama_radio = QRadioButton("Ollama")
        self.openai_radio = QRadioButton("OpenAI")
        self.openrouter_api_input = QLineEdit()
        self.ollama_url_input = QLineEdit()
        self.openai_api_input = QLineEdit()
        self.work_dir_input = QLineEdit()
        self.work_dir_browse_button = QPushButton("Browse…")
        self.dark_radio = QRadioButton("Dark")
        self.light_radio = QRadioButton("Light")
        self.back_button = QPushButton("Back")
        self.save_button = QPushButton("Save")
        self.openrouter_frame = QFrame()
        self.ollama_frame = QFrame()
        self.openai_frame = QFrame()
        self.work_dir_frame = QFrame()
        self._build()

    def set_settings(self, settings: dict[str, Any], focus_model: str | None = None) -> None:
        model = focus_model or str(settings.get("model") or MODEL_LOCAL)
        self.local_radio.setChecked(model == MODEL_LOCAL)
        self.openrouter_radio.setChecked(model == MODEL_OPENROUTER)
        self.ollama_radio.setChecked(model == MODEL_OLLAMA)
        self.openai_radio.setChecked(model == MODEL_OPENAI)
        self.openrouter_api_input.setText(str(settings.get("openrouter_api_key") or ""))
        self.ollama_url_input.setText(str(settings.get("ollama_url") or ""))
        self.openai_api_input.setText(str(settings.get("openai_api_key") or ""))
        self.work_dir_input.setText(str(settings.get("work_dir") or ""))
        self.dark_radio.setChecked(settings.get("theme") != "light")
        self.light_radio.setChecked(settings.get("theme") == "light")
        self._sync_model_fields()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("topBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 8)
        header_layout.setSpacing(8)
        self.back_button.setObjectName("ghostButton")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self.back_requested.emit)
        title = QLabel("Settings")
        title.setObjectName("screenTitle")
        header_layout.addWidget(self.back_button)
        header_layout.addWidget(title)
        header_layout.addStretch()

        body = QFrame()
        body.setObjectName("settingsBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        layout.addWidget(_settings_section_title("Agent type"))
        self.model_group.addButton(self.local_radio)
        self.model_group.addButton(self.openrouter_radio)
        self.model_group.addButton(self.ollama_radio)
        self.model_group.addButton(self.openai_radio)
        for radio in (
            self.local_radio,
            self.openrouter_radio,
            self.ollama_radio,
            self.openai_radio,
        ):
            radio.setObjectName("settingsRadio")
            radio.toggled.connect(self._sync_model_fields)
            layout.addWidget(radio)

        self._build_openrouter_frame()
        self._build_ollama_frame()
        self._build_openai_frame()
        layout.addWidget(self.openrouter_frame)
        layout.addWidget(self.ollama_frame)
        layout.addWidget(self.openai_frame)

        layout.addWidget(_settings_section_title("Working directory"))
        self._build_work_dir_frame()
        layout.addWidget(self.work_dir_frame)

        layout.addWidget(_settings_section_title("Theme"))
        self.theme_group.addButton(self.dark_radio)
        self.theme_group.addButton(self.light_radio)
        for radio in (self.dark_radio, self.light_radio):
            radio.setObjectName("settingsRadio")
            layout.addWidget(radio)

        layout.addStretch()
        self.save_button.setObjectName("primaryButton")
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.clicked.connect(lambda: self.save_requested.emit(self.settings()))
        layout.addWidget(self.save_button)

        root.addWidget(header)
        root.addWidget(body, 1)

    def _build_openrouter_frame(self) -> None:
        self.openrouter_frame.setObjectName("settingsPanel")
        layout = QVBoxLayout(self.openrouter_frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        api_label = QLabel("OpenRouter API key")
        api_label.setObjectName("inputLabel")
        self.openrouter_api_input.setPlaceholderText("sk-or-...")
        layout.addWidget(api_label)
        layout.addWidget(self.openrouter_api_input)

    def _build_ollama_frame(self) -> None:
        self.ollama_frame.setObjectName("settingsPanel")
        layout = QVBoxLayout(self.ollama_frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        url_label = QLabel("Ollama URL")
        url_label.setObjectName("inputLabel")
        self.ollama_url_input.setPlaceholderText("http://localhost:11434")
        layout.addWidget(url_label)
        layout.addWidget(self.ollama_url_input)

    def _build_openai_frame(self) -> None:
        self.openai_frame.setObjectName("settingsPanel")
        layout = QVBoxLayout(self.openai_frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        api_label = QLabel("OpenAI API key")
        api_label.setObjectName("inputLabel")
        self.openai_api_input.setPlaceholderText("sk-...")
        layout.addWidget(api_label)
        layout.addWidget(self.openai_api_input)

    def _build_work_dir_frame(self) -> None:
        self.work_dir_frame.setObjectName("settingsPanel")
        layout = QVBoxLayout(self.work_dir_frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        dir_label = QLabel("Agent's working directory on this machine")
        dir_label.setObjectName("inputLabel")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.work_dir_input.setPlaceholderText("workdir (default)")
        row.addWidget(self.work_dir_input, 1)
        self.work_dir_browse_button.setObjectName("ghostButton")
        self.work_dir_browse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.work_dir_browse_button.clicked.connect(self._browse_work_dir)
        row.addWidget(self.work_dir_browse_button)
        layout.addWidget(dir_label)
        layout.addLayout(row)

    def _browse_work_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Choose working directory", self.work_dir_input.text().strip()
        )
        if directory:
            self.work_dir_input.setText(directory)

    def _sync_model_fields(self, _checked: bool = False) -> None:
        self.openrouter_frame.setVisible(self.openrouter_radio.isChecked())
        self.ollama_frame.setVisible(self.ollama_radio.isChecked())
        self.openai_frame.setVisible(self.openai_radio.isChecked())

    def settings(self) -> dict[str, Any]:
        model = MODEL_LOCAL
        if self.openrouter_radio.isChecked():
            model = MODEL_OPENROUTER
        elif self.ollama_radio.isChecked():
            model = MODEL_OLLAMA
        elif self.openai_radio.isChecked():
            model = MODEL_OPENAI
        return {
            "model": model,
            "openrouter_api_key": self.openrouter_api_input.text().strip(),
            "ollama_url": self.ollama_url_input.text().strip(),
            "openai_api_key": self.openai_api_input.text().strip(),
            "work_dir": self.work_dir_input.text().strip(),
            "theme": "light" if self.light_radio.isChecked() else "dark",
        }


_PROVIDER_LABELS = {
    MODEL_LOCAL: "Hyper",
    MODEL_OPENROUTER: "OpenRouter",
    MODEL_OLLAMA: "Ollama",
    MODEL_OPENAI: "OpenAI",
}


def _short_label(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 3)] + "..."


class ChatPage(QWidget):
    send_requested = pyqtSignal(str, int)
    provider_selected = pyqtSignal(str)
    model_choice_selected = pyqtSignal(str, str)
    access_selected = pyqtSignal(str)
    back_requested = pyqtSignal()
    create_chat_requested = pyqtSignal()
    rename_chat_requested = pyqtSignal(int, str)
    settings_requested = pyqtSignal()
    logout_requested = pyqtSignal()
    _models_fetched = pyqtSignal(str, list)
    _models_fetch_failed = pyqtSignal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.chat_id = 0
        self._stream_kind: str | None = None
        self._active_think_block: StreamTextBlock | None = None
        self._active_command_group: CommandGroupBlock | None = None
        self._current_content_label: QLabel | None = None
        self._current_content_text = ""
        self._current_response_model: str | None = None
        self._command_groups: dict[str, CommandGroupBlock] = {}
        self._current_provider = MODEL_LOCAL
        self._provider_context: dict[str, str] = {
            "ollama_url": "",
            "openrouter_api_key": "",
            "openai_api_key": "",
        }
        self._model_by_provider: dict[str, str] = {
            MODEL_LOCAL: "",
            MODEL_OPENROUTER: "",
            MODEL_OLLAMA: "",
            MODEL_OPENAI: "",
        }
        self._available_models: dict[str, list[str]] = {
            MODEL_LOCAL: [],
            MODEL_OPENROUTER: [],
            MODEL_OLLAMA: [],
            MODEL_OPENAI: [],
        }
        self._fetched_providers: set[str] = set()
        self._models_fetched.connect(self._on_models_fetched)
        self._models_fetch_failed.connect(self._on_models_fetch_failed)
        self._waiting_visible = False

        self.title_label = QLabel("Кодобольный AI")
        self.output_scroll = QScrollArea()
        self.output_widget = QWidget()
        self.output_layout = QVBoxLayout(self.output_widget)
        self.input = PromptTextEdit()
        self.access_button = QToolButton()
        self.provider_button = QToolButton()
        self.model_button = QToolButton()
        self.send_button = PaperPlaneButton()
        self.back_button = QPushButton("Chats")
        self.new_chat_button = QPushButton("+ New Chat")
        self.menu_button = _account_menu_button(
            logout_callback=self.logout_requested.emit,
            rename_callback=self._rename_current_chat,
            settings_callback=self.settings_requested.emit,
        )
        self.waiting_label = QLabel("Waiting...")
        self.waiting_label.setObjectName("waitingMessage")
        self._build()

    def open_chat(self, chat_id: int, title: str) -> None:
        self.chat_id = chat_id
        self.set_chat_title(title)
        self._clear_output()
        self.set_busy(False)

    def load_history(self, messages: list[dict[str, Any]]) -> None:
        self._clear_output()
        for message in messages:
            self._append_history_message(message)
        self._reset_stream_state()
        self._sync_output_height_soon()

    def set_chat_title(self, title: str) -> None:
        self.title_label.setText(title)

    def _rename_current_chat(self) -> None:
        if self.chat_id:
            self.rename_chat_requested.emit(self.chat_id, self.title_label.text())

    def set_new_chat_enabled(self, enabled: bool) -> None:
        self.new_chat_button.setEnabled(enabled)
        self.new_chat_button.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
        )

    def set_model(self, model: str, settings: dict[str, Any] | None = None) -> None:
        context_changed = False
        if settings is not None:
            new_context = {
                "ollama_url": str(settings.get("ollama_url") or ""),
                "openrouter_api_key": str(settings.get("openrouter_api_key") or ""),
                "openai_api_key": str(settings.get("openai_api_key") or ""),
            }
            context_changed = new_context != self._provider_context
            self._provider_context = new_context
            self._model_by_provider = {
                MODEL_LOCAL: str(settings.get("local_model") or ""),
                MODEL_OPENROUTER: str(settings.get("openrouter_model") or ""),
                MODEL_OLLAMA: str(settings.get("ollama_model") or ""),
                MODEL_OPENAI: str(settings.get("openai_model") or ""),
            }
        provider_changed = model != self._current_provider
        self._current_provider = model
        self.provider_button.setText(_PROVIDER_LABELS.get(model, "Hyper"))
        self._update_model_button()
        # Refresh the model list on an actual provider switch, the first time
        # this provider is ever seen, or when its connection details (Ollama
        # URL / OpenRouter key) changed since the last fetch — a saved
        # Settings edit invalidates whatever was cached before it.
        if provider_changed or context_changed or model not in self._fetched_providers:
            self._refresh_available_models(model)

    def _update_model_button(self) -> None:
        provider = self._current_provider
        model_name = self._model_by_provider.get(provider, "")
        if model_name:
            self.model_button.setText(_short_label(model_name, 24))
            self.model_button.setToolTip(model_name)
        elif provider in self._fetched_providers:
            self.model_button.setText("No models")
            self.model_button.setToolTip("")
        else:
            self.model_button.setText("Loading...")
            self.model_button.setToolTip("")
        _bind_menu_above(self.model_button, self._build_model_menu())

    def _build_model_menu(self) -> QMenu:
        provider = self._current_provider
        menu = QMenu(self.model_button)
        models = self._available_models.get(provider, [])
        if models:
            model_list = QListWidget(menu)
            model_list.setObjectName("modelMenuList")
            model_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            model_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            model_list.setUniformItemSizes(True)
            current_model = self._model_by_provider.get(provider, "")
            for model in models:
                item = QListWidgetItem(model)
                item.setToolTip(model)
                model_list.addItem(item)
                if model == current_model:
                    item.setSelected(True)
                    model_list.setCurrentItem(item)
            visible_rows = min(14, max(1, len(models)))
            row_height = max(24, model_list.sizeHintForRow(0))
            model_list.setFixedSize(460, row_height * visible_rows + 8)
            if current_model:
                current_item = model_list.currentItem()
                if current_item is not None:
                    model_list.scrollToItem(current_item)
            model_list.itemClicked.connect(
                lambda item, p=provider, m=menu: self._select_model_from_menu(p, item, m)
            )
            model_action = QWidgetAction(menu)
            model_action.setDefaultWidget(model_list)
            menu.addAction(model_action)
            menu.addSeparator()
        else:
            empty_action = QAction("No models found", menu)
            empty_action.setEnabled(False)
            menu.addAction(empty_action)
            menu.addSeparator()

        refresh_action = QAction("Refresh models", menu)
        refresh_action.triggered.connect(
            lambda checked=False, p=provider: self._refresh_available_models(p)
        )
        menu.addAction(refresh_action)
        manual_action = QAction("Enter model name...", menu)
        manual_action.triggered.connect(
            lambda checked=False, p=provider: self._open_model_manual(p)
        )
        menu.addAction(manual_action)
        return menu

    def _select_model_from_menu(
        self,
        provider: str,
        item: QListWidgetItem,
        menu: QMenu,
    ) -> None:
        self.model_choice_selected.emit(provider, item.text())
        menu.close()

    def prompt_model_choice(self, provider: str) -> None:
        QMessageBox.information(self, "Choose a model", "Pick a model before sending a task.")
        self._refresh_available_models(provider)

    def set_access(self, access: str) -> None:
        labels = {
            ACCESS_READ_ONLY: "ReadOnly",
            ACCESS_ASK: "Ask",
            ACCESS_FULL: "Full",
        }
        self.access_button.setText(f"{labels.get(access, 'Ask')}")

    def _open_model_manual(self, provider: str) -> None:
        current = self._model_by_provider.get(provider, "")
        name, accepted = QInputDialog.getText(self, "Model name", "Model:", text=current)
        name = name.strip()
        if accepted and name:
            self.model_choice_selected.emit(provider, name)

    def _refresh_available_models(self, provider: str) -> None:
        if provider == MODEL_OLLAMA:
            # An unconfigured URL falls back to the standard local Ollama
            # default (the same address Hyper's fixed backend happens to
            # use) rather than showing "No models" for a server that's
            # actually reachable at the well-known default port.
            url = self._provider_context.get("ollama_url") or HYPER_OLLAMA_URL

            def fetch_fn() -> list[str]:
                return fetch_ollama_models(url)
        elif provider == MODEL_OPENROUTER:
            api_key = self._provider_context.get("openrouter_api_key") or ""

            def fetch_fn() -> list[str]:
                return fetch_openrouter_models(api_key)
        elif provider == MODEL_OPENAI:
            api_key = self._provider_context.get("openai_api_key") or ""
            if not api_key:
                # Unlike OpenRouter, OpenAI requires a key just to list
                # models -- an unconfigured key can only ever show "No
                # models", not a real (or borrowed) list.
                self._models_fetched.emit(provider, [])
                return

            def fetch_fn() -> list[str]:
                return fetch_openai_models(api_key)
        else:

            def fetch_fn() -> list[str]:
                return fetch_ollama_models(HYPER_OLLAMA_URL)

        def worker() -> None:
            try:
                models = fetch_fn()
            except Exception as exc:
                self._models_fetch_failed.emit(provider, str(exc))
            else:
                self._models_fetched.emit(provider, models)

        threading.Thread(target=worker, daemon=True).start()

    def _on_models_fetched(self, provider: str, models: list[str]) -> None:
        self._fetched_providers.add(provider)
        self._available_models[provider] = models
        previous_choice = self._model_by_provider.get(provider) or ""
        # A saved choice that this provider's server no longer offers (or
        # was auto-picked earlier against the wrong server, e.g. Local
        # Ollama borrowing Hyper's list before that was fixed) must not keep
        # displaying as if it were still selected.
        resolved_choice = previous_choice if previous_choice in models else ""
        if not resolved_choice and models:
            resolved_choice = models[0]
        self._model_by_provider[provider] = resolved_choice
        # Only announce the change if this fetch is still for the provider
        # actually active right now. A background fetch started before a
        # provider switch can resolve after the user has already moved on;
        # letting it emit unconditionally would push settings["model"] back
        # to the stale provider it was fetched for.
        if resolved_choice != previous_choice and provider == self._current_provider:
            self.model_choice_selected.emit(provider, resolved_choice)
        if provider == self._current_provider:
            self._update_model_button()

    def _on_models_fetch_failed(self, provider: str, error: str) -> None:
        self._fetched_providers.add(provider)
        self._available_models[provider] = []
        if provider == self._current_provider:
            self._update_model_button()
            self.model_button.setToolTip(error)

    def set_busy(self, busy: bool) -> None:
        self.input.setDisabled(busy)
        self.send_button.setDisabled(busy)
        self.send_button.setVisible(not busy)
        self._set_waiting_visible(busy)

    def append_user_message(self, text: str) -> None:
        self._close_active_think()
        self._close_active_command_group()
        self._reset_stream_state()
        self._append_text_block(text, "userMessage")

    def append_result(self, message: dict[str, Any]) -> None:
        self._close_active_think()
        self._close_active_command_group()
        self._reset_stream_state()
        answer = message.get("answer") or message.get("result") or message.get("summary") or message
        self._append_text_block(f"Result: {answer}", "resultMessage", markdown=True)

    def append_status(self, message: str) -> None:
        self._close_active_think()
        self._close_active_command_group()
        self._reset_stream_state()
        self._append_text_block(f"Status: {message}", "statusMessage")

    def append_client_command_start(self, command: dict[str, Any]) -> None:
        self._close_active_think()
        self._current_content_label = None
        self._current_content_text = ""
        command_id = str(command.get("id") or len(self._command_groups))
        group = self._active_command_group
        if group is None:
            group = CommandGroupBlock()
            self._active_command_group = group
            self._add_output_widget(group)
        block = group.add_command(
            command_id,
            str(command.get("command") or ""),
            str(command.get("cwd") or ""),
        )
        self._command_groups[command_id] = group
        self._stream_kind = "client_command"
        self._sync_output_height_soon()
        self._scroll_to_widget(block)

    def append_client_command_result(self, result: dict[str, Any]) -> None:
        self._close_active_think()
        command_id = str(result.get("id") or "")
        group = self._command_groups.get(command_id)
        if group is None:
            group = self._active_command_group
        if group is None:
            group = CommandGroupBlock()
            self._active_command_group = group
            self._add_output_widget(group)
        block = group.command(command_id)
        if block is None:
            command_id = command_id or str(len(self._command_groups))
            block = group.add_command(
                command_id,
                str(result.get("command") or ""),
                str(result.get("cwd") or ""),
            )
            self._command_groups[command_id] = group
        block.complete(result)
        self._stream_kind = "client_command"
        self._sync_output_height_soon()
        self._scroll_to_widget(block)

    def append_agent_message(self, kind: str, text: Any) -> None:
        value = "" if text is None else str(text)
        if kind != "think":
            self._close_active_think()
        self._close_active_command_group()

        if kind == "think":
            if self._stream_kind != "think" or self._active_think_block is None:
                self._active_think_block = StreamTextBlock("Думает", "thinkText", expanded=True)
                self._add_output_widget(self._active_think_block)
                self._stream_kind = "think"
            self._active_think_block.append_text(value)
            self._sync_output_height_soon()
            self._scroll_to_widget(self._active_think_block)
            return

        if kind == "title":
            return

        if kind == "start":
            model = value.strip()
            if model and model != self._current_response_model:
                self._append_text_block(model, "modelHeader")
                self._current_response_model = model
            self._stream_kind = "start"
            self._current_content_label = None
            self._current_content_text = ""
            return

        if kind == "content":
            if self._stream_kind != "content" or self._current_content_label is None:
                self._current_content_label = self._create_output_label(
                    "", "assistantText", markdown=True
                )
                self._current_content_text = ""
                self._add_output_widget(self._current_content_label)
            self._current_content_text += value
            self._current_content_label.setText(self._current_content_text)
            self._stream_kind = "content"
            self._sync_output_height_soon()
            self._scroll_to_widget(self._current_content_label)
            return

        self._reset_stream_state()
        labels = {"tool_call": "Tool", "status": "Status"}
        self._append_text_block(f"{labels.get(kind, kind or 'Message')}: {value}", "statusMessage")

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("topBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 8)
        header_layout.setSpacing(8)

        self.back_button.setObjectName("ghostButton")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self.back_requested.emit)

        self.title_label.setObjectName("screenTitle")
        self.new_chat_button.setObjectName("flatButton")
        self.new_chat_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_chat_button.clicked.connect(self.create_chat_requested.emit)

        header_layout.addWidget(self.back_button)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.new_chat_button)
        header_layout.addWidget(self.menu_button)

        body = QFrame()
        body.setObjectName("chatBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(22, 12, 22, 14)
        body_layout.setSpacing(10)

        self.output_scroll.setObjectName("agentScroll")
        self.output_scroll.setWidgetResizable(True)
        self.output_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.output_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.output_scroll.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.output_scroll.setWidget(self.output_widget)
        self.output_widget.setObjectName("agentOutput")
        self.output_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.output_widget.setMinimumWidth(0)
        self.output_layout.setContentsMargins(0, 0, 0, 0)
        self.output_layout.setSpacing(12)
        self.output_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        input_frame = QFrame()
        input_frame.setObjectName("inputFrame")
        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(12, 10, 10, 10)
        input_layout.setSpacing(8)
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)

        self.input.setObjectName("taskInput")
        self.input.setPlaceholderText("Ask the agent")
        self.input.setFixedHeight(92)
        self.input.setTabChangesFocus(True)
        self.input.setMinimumWidth(120)
        self.input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.input.submitted.connect(self._send)

        self.access_button.setObjectName("selectorButton")
        self.access_button.setCursor(Qt.CursorShape.PointingHandCursor)
        access_menu = QMenu(self.access_button)
        for label, value in (
            ("ReadOnly", ACCESS_READ_ONLY),
            ("Ask", ACCESS_ASK),
            ("Full access", ACCESS_FULL),
        ):
            action = QAction(label, self.access_button)
            action.triggered.connect(
                lambda checked=False, item=value: self.access_selected.emit(item)
            )
            access_menu.addAction(action)
        _bind_menu_above(self.access_button, access_menu)

        self.provider_button.setObjectName("selectorButton")
        self.provider_button.setCursor(Qt.CursorShape.PointingHandCursor)
        provider_menu = QMenu(self.provider_button)
        for label, value in (
            ("Hyper", MODEL_LOCAL),
            ("OpenRouter", MODEL_OPENROUTER),
            ("Ollama", MODEL_OLLAMA),
            ("OpenAI", MODEL_OPENAI),
        ):
            action = QAction(label, self.provider_button)
            action.triggered.connect(
                lambda checked=False, item=value: self.provider_selected.emit(item)
            )
            provider_menu.addAction(action)
        _bind_menu_above(self.provider_button, provider_menu)

        self.model_button.setObjectName("selectorButton")
        self.model_button.setCursor(Qt.CursorShape.PointingHandCursor)
        _bind_menu_above(self.model_button, self._build_model_menu())

        self.send_button.setFixedSize(38, 38)
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.clicked.connect(self._send)

        input_layout.addWidget(self.input)
        controls_layout.addStretch(1)
        controls_layout.addWidget(self.access_button)
        controls_layout.addWidget(self.provider_button)
        controls_layout.addWidget(self.model_button)
        controls_layout.addWidget(self.send_button)
        input_layout.addLayout(controls_layout)

        body_layout.addWidget(self.output_scroll, 1)
        body_layout.addWidget(input_frame)

        root.addWidget(header)
        root.addWidget(body, 1)

    def _send(self) -> None:
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self.append_user_message(text)
        self.set_busy(True)
        self.send_requested.emit(text, self.chat_id)

    def _append_text_block(self, text: str, object_name: str, markdown: bool = False) -> QLabel:
        label = self._create_output_label(text, object_name, markdown=markdown)
        self._add_output_widget(label)
        return label

    def _append_history_message(self, message: dict[str, Any]) -> None:
        message_type = str(message.get("message_type") or "")
        value = message.get("message")

        if message_type == "user":
            self.append_user_message(str(value))
            return

        if message_type == "client_command_start":
            self.append_client_command_start(value)
            return

        if message_type == "client_command_result":
            self.append_client_command_result(value)
            return

        if message_type == "title":
            return

        if message_type == "result":
            self.append_result(value)
            return

        self.append_agent_message(message_type, value)

    def _create_output_label(self, text: str, object_name: str, markdown: bool = False) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setTextFormat(Qt.TextFormat.MarkdownText if markdown else Qt.TextFormat.PlainText)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        label.setMinimumWidth(0)
        label.setMaximumHeight(16777215)
        if markdown:
            label.setOpenExternalLinks(True)
        return label

    def _add_output_widget(self, widget: QWidget) -> None:
        waiting_was_visible = self._waiting_visible
        if waiting_was_visible:
            self._remove_waiting_label()
        widget.setMinimumWidth(0)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.output_layout.addWidget(widget)
        if waiting_was_visible:
            self._add_waiting_label()
        self._sync_output_height_soon()
        self._scroll_to_widget(widget)

    def _clear_output(self) -> None:
        while self.output_layout.count():
            item = self.output_layout.takeAt(0)
            widget = item.widget()
            if widget is self.waiting_label:
                widget.hide()
                continue
            if widget is not None:
                widget.deleteLater()
        self._command_groups.clear()
        self._reset_stream_state()
        self._waiting_visible = False
        self.waiting_label.setParent(None)

    def _close_active_think(self) -> None:
        if self._active_think_block is not None:
            self._active_think_block.collapse()
            self._active_think_block = None
        if self._stream_kind == "think":
            self._stream_kind = None

    def _close_active_command_group(self) -> None:
        if self._active_command_group is not None:
            self._active_command_group.collapse()
            self._active_command_group = None
        if self._stream_kind == "client_command":
            self._stream_kind = None

    def _reset_stream_state(self) -> None:
        self._stream_kind = None
        self._active_think_block = None
        self._active_command_group = None
        self._current_content_label = None
        self._current_content_text = ""
        self._current_response_model = None

    def _scroll_to_widget(self, widget: QWidget) -> None:
        QTimer.singleShot(0, lambda: self._ensure_widget_visible(widget))

    def _ensure_widget_visible(self, widget: QWidget) -> None:
        with contextlib.suppress(RuntimeError):
            self._sync_output_height()
            self.output_scroll.ensureWidgetVisible(widget, 0, 24)

    def _sync_output_height_soon(self) -> None:
        QTimer.singleShot(0, self._sync_output_height)

    def _sync_output_height(self) -> None:
        height = max(self.output_layout.sizeHint().height(), self.output_scroll.viewport().height())
        self.output_widget.setMinimumHeight(height)
        self.output_widget.setMaximumHeight(16777215)

    def _set_waiting_visible(self, visible: bool) -> None:
        if visible == self._waiting_visible:
            return
        self._waiting_visible = visible
        if visible:
            self._add_waiting_label()
        else:
            self._remove_waiting_label()
        self._sync_output_height_soon()

    def _add_waiting_label(self) -> None:
        self.output_layout.addWidget(self.waiting_label)
        self.waiting_label.show()
        self._scroll_to_widget(self.waiting_label)

    def _remove_waiting_label(self) -> None:
        self.output_layout.removeWidget(self.waiting_label)
        self.waiting_label.hide()

    @override
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_output_height_soon()


def _account_menu_button(
    logout_callback, rename_callback=None, settings_callback=None
) -> QToolButton:
    button = QToolButton()
    button.setObjectName("menuButton")
    button.setText("⋮")
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    button.setCursor(Qt.CursorShape.PointingHandCursor)

    menu = QMenu(button)
    if rename_callback is not None:
        rename_action = QAction("Rename chat", button)
        rename_action.triggered.connect(rename_callback)
        menu.addAction(rename_action)
        menu.addSeparator()
    if settings_callback is not None:
        settings_action = QAction("Settings", button)
        settings_action.triggered.connect(settings_callback)
        menu.addAction(settings_action)
        menu.addSeparator()
    logout_action = QAction("Logout", button)
    logout_action.triggered.connect(logout_callback)
    menu.addAction(logout_action)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    button.setMenu(menu)
    return button


def _bind_menu_above(button: QToolButton, menu: QMenu) -> None:
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    button.setMenu(menu)
    menu.aboutToShow.connect(lambda: QTimer.singleShot(0, lambda: _move_menu_above(button, menu)))


def _move_menu_above(button: QToolButton, menu: QMenu) -> None:
    pos = button.mapToGlobal(button.rect().topLeft())
    pos.setY(pos.y() - menu.sizeHint().height())
    menu.move(pos)


def _settings_section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("settingsSectionTitle")
    return label


def _format_chat_timestamp(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return str(value)
    return dt.strftime("%d.%m.%Y %H:%M")
