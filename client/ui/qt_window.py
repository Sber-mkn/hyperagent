import contextlib
import threading
from typing import Any, override

from PyQt6.QtCore import QByteArray, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QInputDialog, QMainWindow, QMessageBox, QStackedWidget

from client.core.chat_controller import ChatController
from client.core.client_state import (
    ACCESS_ASK,
    MODEL_LOCAL,
    ClientState,
)
from client.core.rabbitmq_client import RabbitMQClient
from client.ui.qt_pages import ChatListPage, ChatPage, LoginPage, SettingsPage
from client.ui.qt_style import stylesheet


class CommandPermissionRequest:
    def __init__(self, command: dict[str, Any]) -> None:
        self.command = command
        self.decision = "deny"
        self.done = threading.Event()


class ClientEventBridge(QObject):
    ready = pyqtSignal()
    result = pyqtSignal(object)
    agent_message = pyqtSignal(str, object)
    waiting_result = pyqtSignal()
    unknown_message = pyqtSignal(str)
    login_error = pyqtSignal(str)
    service_unavailable = pyqtSignal(str)
    client_command_start = pyqtSignal(object)
    client_command_result = pyqtSignal(object)
    command_permission_requested = pyqtSignal(object)

    def on_ready(self) -> None:
        self.ready.emit()

    def on_result(self, message: dict[str, Any]) -> None:
        self.result.emit(message)

    def on_agent_message(self, message_type: str, message: Any) -> None:
        self.agent_message.emit(message_type or "", message)

    def on_waiting_result(self) -> None:
        self.waiting_result.emit()

    def on_unknown_message(self, message_type: str) -> None:
        self.unknown_message.emit(message_type or "")

    def on_login_error(self, message: str) -> None:
        self.login_error.emit(message)

    def on_service_unavailable(self, message: str) -> None:
        self.service_unavailable.emit(message)

    def on_client_command_start(self, command: dict[str, Any]) -> None:
        self.client_command_start.emit(command)

    def on_client_command_result(self, result: dict[str, Any]) -> None:
        self.client_command_result.emit(result)

    def request_command_permission(self, command: dict[str, Any]) -> str:
        request = CommandPermissionRequest(command)
        self.command_permission_requested.emit(request)
        request.done.wait()
        return request.decision


class HyperagentClientWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.state = ClientState()
        self.controller = ChatController(self.state)
        self.client: RabbitMQClient | None = None
        self.bridge: ClientEventBridge | None = None
        self.consumer_stop_event: threading.Event | None = None
        self.settings_return_widget = None
        self.logged_in = False

        self.stack = QStackedWidget()
        self.login_page = LoginPage()
        self.chat_list_page = ChatListPage()
        self.chat_page = ChatPage()
        self.settings_page = SettingsPage()

        self._build()
        self._connect_ui()
        self._load_saved_session()
        self._refresh_chats()

    def _build(self) -> None:
        self.setWindowTitle("Кодобольный AI")
        self.resize(500, 740)
        self.setMinimumSize(380, 520)
        self.setCentralWidget(self.stack)
        self.stack.addWidget(self.login_page)
        self.stack.addWidget(self.chat_list_page)
        self.stack.addWidget(self.chat_page)
        self.stack.addWidget(self.settings_page)
        self.stack.setCurrentWidget(self.login_page)
        self.setStyleSheet(stylesheet(self.controller.theme()))
        self._restore_window_placement()
        self._apply_settings_to_ui()

    def _connect_ui(self) -> None:
        self.login_page.login_requested.connect(self._login)
        self.chat_list_page.chat_opened.connect(self._open_chat)
        self.chat_list_page.create_chat_requested.connect(self._create_chat)
        self.chat_list_page.rename_chat_requested.connect(self._rename_chat)
        self.chat_list_page.settings_requested.connect(self._show_settings)
        self.chat_list_page.logout_requested.connect(self._logout)
        self.chat_page.back_requested.connect(self._show_chat_list)
        self.chat_page.create_chat_requested.connect(self._create_chat)
        self.chat_page.rename_chat_requested.connect(self._rename_chat)
        self.chat_page.settings_requested.connect(self._show_settings)
        self.chat_page.model_selected.connect(self._select_model)
        self.chat_page.access_selected.connect(self._select_access)
        self.chat_page.logout_requested.connect(self._logout)
        self.chat_page.send_requested.connect(self._send_task)
        self.settings_page.back_requested.connect(self._return_from_settings)
        self.settings_page.save_requested.connect(self._save_settings)

    def _load_saved_session(self) -> None:
        session = self.controller.saved_session()
        if not session:
            return
        self.login_page.set_credentials(session["login"], session["password"])
        QTimer.singleShot(0, lambda: self._login(session["login"], session["password"]))

    def _login(self, login: str, password: str) -> None:
        self._close_client()
        self.login_page.set_busy(True)
        self.controller.begin_login(login, password)

        self.bridge = ClientEventBridge()
        self.bridge.ready.connect(self._on_ready)
        self.bridge.result.connect(self._on_result)
        self.bridge.agent_message.connect(self._on_agent_message)
        self.bridge.waiting_result.connect(self._on_waiting_result)
        self.bridge.unknown_message.connect(self._on_unknown_message)
        self.bridge.login_error.connect(self._on_login_error)
        self.bridge.service_unavailable.connect(self._on_service_unavailable)
        self.bridge.client_command_start.connect(self._on_client_command_start)
        self.bridge.client_command_result.connect(self._on_client_command_result)
        self.bridge.command_permission_requested.connect(self._on_command_permission_requested)

        try:
            self.client = RabbitMQClient(event_handler=self.bridge)
            self.controller.attach_client(self.client)
            self.client.send_login(login, password)
        except Exception:
            self.login_page.show_error("Сервис временно недоступен.")
            self.client = None
            self.controller.detach_client()
            return

        self.consumer_stop_event = threading.Event()
        consumer_thread = threading.Thread(
            target=self._consume,
            args=(self.client, self.bridge, self.consumer_stop_event),
            daemon=True,
        )
        consumer_thread.start()

    def _consume(
        self,
        client: RabbitMQClient,
        bridge: ClientEventBridge,
        stop_event: threading.Event,
    ) -> None:
        try:
            client.start_consuming()
        except Exception:
            if stop_event.is_set():
                return
            bridge.service_unavailable.emit("Сервис временно недоступен.")

    def _refresh_chats(self) -> None:
        self.chat_list_page.set_chats(
            self.controller.visible_chats(),
            self.controller.current_chat_id,
        )
        can_create_chat = self.controller.can_create_chat()
        self.chat_list_page.set_new_chat_enabled(can_create_chat)
        self.chat_page.set_new_chat_enabled(can_create_chat)

    def _load_chats(self) -> None:
        try:
            self.controller.load_chats()
        except Exception:
            self.chat_list_page.set_chats([], None)
            self.chat_list_page.set_new_chat_enabled(False)
            self.chat_page.append_status("Не удалось загрузить чаты.")  # noqa: RUF001
            return
        self._refresh_chats()

    def _show_settings(self, model: str | None = None) -> None:
        self.settings_return_widget = self.stack.currentWidget()
        self.settings_page.set_settings(self.controller.settings(), model)
        self.stack.setCurrentWidget(self.settings_page)

    def _return_from_settings(self) -> None:
        self.stack.setCurrentWidget(self.settings_return_widget or self.chat_list_page)

    def _save_settings(self, settings: dict[str, Any]) -> None:
        current = self.controller.settings()
        current.update(settings)
        self.controller.save_settings(current)
        self.setStyleSheet(stylesheet(self.controller.theme()))
        self._apply_settings_to_ui()
        self._return_from_settings()

    def _select_model(self, model: str) -> None:
        if not self.controller.model_configured(model):
            self._show_settings(model)
            return
        self.controller.set_model(model)
        self._apply_settings_to_ui()

    def _select_access(self, access: str) -> None:
        self.controller.set_access(access)
        self._apply_settings_to_ui()

    def _apply_settings_to_ui(self) -> None:
        settings = self.controller.settings()
        self.chat_page.set_model(str(settings.get("model") or MODEL_LOCAL))
        self.chat_page.set_access(str(settings.get("access") or ACCESS_ASK))

    def _show_chat_list(self) -> None:
        if self.logged_in and not self.controller.has_busy_chats():
            self._load_chats()
        self._refresh_chats()
        self.stack.setCurrentWidget(self.chat_list_page)

    def _open_chat(self, chat_id: int, title: str) -> None:
        self.chat_page.open_chat(chat_id, title)
        if chat_id > 0:
            try:
                self.chat_page.load_history(self.controller.open_chat(chat_id))
            except Exception:
                self.chat_page.append_status("Не удалось загрузить историю чата.")  # noqa: RUF001
        else:
            self.controller.open_chat(chat_id)
        self.chat_page.set_busy(self.controller.has_busy_chats())
        self._refresh_chats()
        self.stack.setCurrentWidget(self.chat_page)

    def _create_chat(self) -> None:
        chat = self.controller.create_chat()
        self._refresh_chats()
        self._open_chat(int(chat["id"]), str(chat["title"]))

    def _send_task(self, text: str, chat_id: int) -> None:
        if self.client is None:
            self.chat_page.append_status("Сервис временно недоступен.")
            self.chat_page.set_busy(False)
            return
        if self.controller.has_busy_chats():
            self.chat_page.set_busy(True)
            return
        try:
            chat_id = self.controller.send_task(text, chat_id)
            self.chat_page.chat_id = chat_id
            self._refresh_chats()
        except Exception:
            self.chat_page.append_status("Сервис временно недоступен.")
            self.chat_page.set_busy(False)

    def _rename_chat(self, chat_id: int, title: str) -> None:
        new_title, accepted = QInputDialog.getText(
            self,
            "Rename chat",
            "Chat name:",
            text=title,
        )
        new_title = new_title.strip()
        if not accepted or not new_title:
            return
        try:
            chat = self.controller.rename_chat(chat_id, new_title)
        except Exception:
            self.chat_page.append_status("Не удалось переименовать чат.")  # noqa: RUF001
            return

        if self.chat_page.chat_id == chat_id:
            self.chat_page.set_chat_title(str(chat["title"]))
        self._refresh_chats()

    def _logout(self) -> None:
        self.logged_in = False
        self.controller.logout()
        self._close_client()
        self.login_page.clear_credentials()
        self.login_page.set_busy(False)
        self.stack.setCurrentWidget(self.login_page)

    def _on_ready(self) -> None:
        if not self.logged_in:
            self.logged_in = True
            self.login_page.set_busy(False)
            self.controller.complete_login()
            self._load_chats()
            self.stack.setCurrentWidget(self.chat_list_page)
            return
        result = self.controller.finish_request()
        if result is None:
            return
        chat_id, history = result
        if self._is_open_chat(chat_id):
            self.chat_page.load_history(history)
        if self.stack.currentWidget() == self.chat_page:
            self.chat_page.set_busy(self.controller.has_busy_chats())
        self._load_chats()

    def _on_result(self, message: dict[str, Any]) -> None:
        chat_id = self.controller.event_chat_id(message.get("chat_id"))
        self.controller.record_result(chat_id, message)
        if self._is_open_chat(chat_id):
            self.chat_page.append_result(message)

    def _on_agent_message(self, kind: str, message: Any) -> None:
        chat_id = self.controller.event_chat_id(None)
        if kind == "error":
            self.controller.record_error(chat_id, "" if message is None else str(message))
        else:
            self.controller.record_agent_message(chat_id, kind, message)
        if kind == "title":
            title = "" if message is None else str(message).strip()
            if title:
                try:
                    chat = self.controller.apply_agent_title(chat_id, title)
                except Exception:
                    self.chat_page.append_status("Не удалось обновить название чата.")  # noqa: RUF001
                    return
                if chat is not None:
                    if self._is_open_chat(chat_id):
                        self.chat_page.set_chat_title(str(chat["title"]))
                    self._refresh_chats()
            return
        if self._is_open_chat(chat_id):
            self.chat_page.append_agent_message(kind, message)

    def _on_waiting_result(self) -> None:
        if self.stack.currentWidget() == self.chat_page:
            self.chat_page.set_busy(True)

    def _on_unknown_message(self, message_type: str) -> None:
        self.chat_page.append_status(f"Unknown message type: {message_type}")

    def _on_client_command_start(self, command: dict[str, Any]) -> None:
        chat_id = self.controller.event_chat_id(command.get("chat_id"))
        self.controller.record_client_command_start(chat_id, command)
        if self._is_open_chat(chat_id):
            self.chat_page.append_client_command_start(command)

    def _on_client_command_result(self, result: dict[str, Any]) -> None:
        chat_id = self.controller.event_chat_id(result.get("chat_id"))
        self.controller.record_client_command_result(chat_id, result)
        if self._is_open_chat(chat_id):
            self.chat_page.append_client_command_result(result)

    def _on_command_permission_requested(self, request: CommandPermissionRequest) -> None:
        command = str(request.command.get("command") or "")
        box = QMessageBox(self)
        box.setWindowTitle("Run command")
        box.setText(command)
        allow_button = box.addButton("Разрешить", QMessageBox.ButtonRole.AcceptRole)
        allow_all_button = box.addButton(
            "Разрешить на весь запрос",
            QMessageBox.ButtonRole.AcceptRole,
        )
        deny_button = box.addButton("Отклонить", QMessageBox.ButtonRole.RejectRole)
        box.exec()

        clicked = box.clickedButton()
        if clicked == allow_button:
            request.decision = "allow"
        elif clicked == allow_all_button:
            request.decision = "allow_all"
        elif clicked == deny_button:
            request.decision = "deny"
        request.done.set()

    def _on_login_error(self, message: str) -> None:
        if not self.logged_in:
            self.login_page.show_error(message or "Неправильный пароль.")
            self._close_client()
            return
        self.chat_page.append_status(message or "Неправильный пароль.")

    def _on_service_unavailable(self, message: str) -> None:
        if not self.logged_in:
            self.login_page.show_error(message or "Сервис временно недоступен.")
            self._close_client()
            return
        self.chat_page.append_status(message or "Сервис временно недоступен.")
        self.chat_page.set_busy(False)

    def _is_open_chat(self, chat_id: int) -> bool:
        return self.stack.currentWidget() == self.chat_page and self.chat_page.chat_id == chat_id

    def _close_client(self) -> None:
        client = self.client
        stop_event = self.consumer_stop_event
        if client is None:
            return
        if stop_event is not None:
            stop_event.set()
        self.client = None
        self.controller.detach_client()
        self.consumer_stop_event = None
        with contextlib.suppress(Exception):
            client.channel.stop_consuming()
        with contextlib.suppress(Exception):
            client.connection.close()

    def _restore_window_placement(self) -> None:
        window_state = self.state.window_state()
        geometry = window_state.get("geometry")
        if isinstance(geometry, str) and geometry:
            with contextlib.suppress(Exception):
                self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))

        mode = window_state.get("mode")
        if mode == "fullscreen":
            self.setWindowState(self.windowState() | Qt.WindowState.WindowFullScreen)
        elif mode == "maximized":
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    def _save_window_placement(self) -> None:
        if self.isFullScreen():
            mode = "fullscreen"
        elif self.isMaximized():
            mode = "maximized"
        else:
            mode = "normal"

        geometry = self.normalGeometry() if self.normalGeometry().isValid() else self.geometry()
        self.state.save_window_state(
            {
                "mode": mode,
                "x": geometry.x(),
                "y": geometry.y(),
                "width": geometry.width(),
                "height": geometry.height(),
                "geometry": bytes(self.saveGeometry().toBase64()).decode("ascii"),
            }
        )

    @override
    def closeEvent(self, event) -> None:
        self._save_window_placement()
        self._close_client()
        super().closeEvent(event)
