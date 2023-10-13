import asyncio
import logging
from abc import ABC
from enum import Enum, auto
from math import isclose
from pathlib import Path
from random import choice
from typing import Any, Awaitable, Coroutine

import flet as ft

from hasherino import helix, user_auth
from hasherino.hasherino_dataclasses import Emote, EmoteSource, HasherinoUser, Message
from hasherino.helix import NormalUserColor
from hasherino.storage import AsyncKeyValueStorage, MemoryOnlyStorage, PersistentStorage
from hasherino.twitch_websocket import Command, ParsedMessage, TwitchWebsocket

_LOG_PATH = Path("hasherino.log")


class PubSub:
    def __init__(self) -> None:
        self.funcs: set[Awaitable] = set()

    async def subscribe(self, func: Awaitable):
        self.funcs.add(func)

    async def subscribe_all(self, funcs: list[Awaitable]):
        self.funcs.update(funcs)

    async def send(self, message: Any):
        for func in self.funcs:
            await func(message)


class FontSizeSubscriber(ABC):
    async def on_font_size_changed(self, new_font_size: int):
        ...


class ChatText(ft.Text, FontSizeSubscriber):
    def __init__(self, text: str, color: str, size: int, weight=""):
        super().__init__(text, size=size, weight=weight, color=color, selectable=True)

    async def on_font_size_changed(self, new_font_size: int):
        self.size = new_font_size


class ChatBadge(ft.Image, FontSizeSubscriber):
    def __init__(self, src: str, height: int):
        super().__init__(src=src, height=height)

    async def on_font_size_changed(self, new_font_size: int):
        self.height = new_font_size


class ChatEmote(ft.Image, FontSizeSubscriber):
    async def on_font_size_changed(self, new_font_size: int):
        self.height = new_font_size * 2


class ChatMessage(ft.Row):
    def __init__(self, message: Message, page: ft.Page, font_size: int):
        super().__init__()
        self.vertical_alignment = "start"
        self.wrap = True
        self.width = page.width
        self.page = page
        self.font_size = font_size
        self.spacing = 2
        self.vertical_alignment = ft.CrossAxisAlignment.CENTER

        self.add_control_elements(message)

    def add_control_elements(self, message):
        self.controls = [
            ChatBadge(badge.url, self.font_size) for badge in message.user.badges
        ]

        self.controls.append(
            ChatText(
                f"{message.user.name}: ",
                message.user.chat_color,
                self.font_size,
                weight="bold",
            )
        )

        for element in message.elements:
            if type(element) == str:
                theme_text_color = (
                    ft.colors.WHITE
                    if self.page.platform_brightness == ft.ThemeMode.DARK
                    else ft.colors.BLACK
                )
                color = message.user.chat_color if message.me else theme_text_color
                result = ChatText(element, color, self.font_size)
            elif type(element) == Emote:
                result = ChatEmote(
                    src=element.get_url(),
                    height=self.font_size * 2,
                )
            else:
                raise TypeError

            self.controls.append(result)

    async def subscribe_to_font_size_change(self, pubsub: PubSub):
        await pubsub.subscribe_all(
            [
                control.on_font_size_changed
                for control in self.controls
                if isinstance(control, FontSizeSubscriber)
            ]
        )


class SettingsView(ft.View):
    def __init__(self, font_size_pubsub: PubSub, storage: AsyncKeyValueStorage):
        self.font_size_pubsub = font_size_pubsub
        self.storage = storage

    async def init(self):
        super().__init__(
            "/settings",
            [
                ft.IconButton(icon=ft.icons.ARROW_BACK, on_click=self._back_click),
                ft.Tabs(
                    tabs=[
                        await self._get_general_tab(),
                        await self._get_appearance_tab(),
                        await self._get_debug_tab(),
                    ]
                ),
            ],
        )

    async def _get_general_tab(self) -> ft.Tab:
        return ft.Tab(
            text="General",
            icon=ft.icons.SETTINGS,
            content=ft.Column(
                controls=[
                    ft.Text(),
                    ft.TextField(
                        value=await self.storage.get("max_messages_per_chat"),
                        label="Max. messages per chat",
                        width=500,
                        on_change=self._max_messages_change,
                    ),
                    ft.Text(),
                    ft.TextField(
                        value=await self.storage.get("chat_update_rate"),
                        label="Chat UI Update rate(lower = higher CPU usage):",
                        width=500,
                        on_change=self._chat_update_rate_change,
                    ),
                ],
            ),
        )

    async def _get_appearance_tab(self) -> ft.Tab:
        return ft.Tab(
            text="Appearance",
            icon=ft.icons.BRUSH,
            content=ft.Column(
                controls=[
                    ft.Text(),
                    ft.Text(
                        "Chat font size:",
                        size=16,
                    ),
                    ft.Slider(
                        value=await self.storage.get("chat_font_size"),
                        min=10,
                        max=50,
                        divisions=40,
                        label="{value}",
                        width=500,
                        on_change_end=self._font_size_change,
                    ),
                    ft.Text(),
                    ft.Text("Theme"),
                    ft.Dropdown(
                        value=await self.storage.get("theme"),
                        options=[
                            ft.dropdown.Option("System"),
                            ft.dropdown.Option("Dark mode"),
                            ft.dropdown.Option("Light mode"),
                        ],
                        on_change=self._theme_select,
                    ),
                    ft.Text(),
                    ft.Checkbox(
                        label="Enable color switcher",
                        value=await self.storage.get("color_switcher"),
                        label_position=ft.LabelPosition.LEFT,
                        on_change=self._on_color_switcher_click,
                    ),
                ],
            ),
        )

    async def _get_debug_tab(self) -> ft.Tab:
        return ft.Tab(
            text="Debug",
            icon=ft.icons.BUG_REPORT,
            content=ft.Column(
                controls=[
                    ft.Text(),
                    ft.Text("Log file location"),
                    ft.Row(
                        controls=[
                            ft.TextField(
                                value=str(_LOG_PATH.absolute()),
                                read_only=True,
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.icons.COPY, on_click=self._log_path_copy_click
                            ),
                        ]
                    ),
                ]
            ),
        )

    async def _on_color_switcher_click(self, e):
        await self.storage.set("color_switcher", e.control.value)

    async def _theme_select(self, e):
        match e.data:
            case "System":
                self.page.theme_mode = ft.ThemeMode.SYSTEM
            case "Dark mode":
                self.page.theme_mode = ft.ThemeMode.DARK
            case "Light mode":
                self.page.theme_mode = ft.ThemeMode.LIGHT
            case _:
                pass

        await self.storage.set("theme", e.data)
        await self.page.update_async()

    async def _log_path_copy_click(self, _):
        await self.page.set_clipboard_async(str(_LOG_PATH.absolute()))

    async def _max_messages_change(self, e):
        try:
            value = int(e.control.value)

            if value < 10 or value > 500:
                raise ValueError

            await self.storage.set("max_messages_per_chat", value)
            e.control.error_text = ""
            logging.debug(f"Updated max_messages_per_chat to {value}")

        except ValueError:
            e.control.error_text = "Value must be an integer between 10 and 500!"

        finally:
            await self.page.update_async()

    async def _back_click(self, _):
        self.page.views.pop()
        await self.page.update_async()

    async def _font_size_change(self, e):
        await self.storage.set("chat_font_size", e.control.value)
        await self.font_size_pubsub.send(e.control.value)
        await self.page.update_async()

    async def _chat_update_rate_change(self, e):
        try:
            value = float(e.control.value)

            if value < 0.3 or value > 1:
                raise ValueError

            e.control.error_text = ""
            await self.storage.set("chat_update_rate", e.control.value)
            logging.debug(f"Set chat_update_rate to {value}")

        except ValueError:
            e.control.error_text = "Value must be a decimal between 0.3 and 1."

        finally:
            await self.page.update_async()


class AccountDialog(ft.AlertDialog):
    def __init__(self, storage: AsyncKeyValueStorage):
        # A dialog asking for a user display name
        self.join_user_name = ft.TextField(
            label="Enter your name to join the chat",
            autofocus=True,
            on_submit=self.join_chat_click,
        )
        self.storage = storage
        super().__init__(
            open=True,
            modal=True,
            title=ft.Text("Welcome!"),
            content=ft.Column([self.join_user_name], width=300, height=70, tight=True),
            actions=[
                ft.ElevatedButton(text="Join chat", on_click=self.join_chat_click)
            ],
            actions_alignment="end",
        )

    async def join_chat_click(self, _):
        if not self.join_user_name.value:
            self.join_user_name.error_text = "Name cannot be blank!"
            await self.join_user_name.update_async()
        else:
            await self.storage.set("user_name", self.join_user_name.value)
            self.page.dialog.open = False
            await self.page.update_async()


class NewMessageRow(ft.Row):
    def __init__(
        self,
        memory_storage: AsyncKeyValueStorage,
        persistent_storage: AsyncKeyValueStorage,
        chat_message_pubsub: PubSub,
        reconnect_callback: Coroutine,
    ):
        self.memory_storage = memory_storage
        self.persistent_storage = persistent_storage
        self.chat_message_pubsub = chat_message_pubsub
        self.reconnect_callback = reconnect_callback

        # A new message entry form
        self.new_message = ft.TextField(
            hint_text="Write a message...",
            autofocus=True,
            shift_enter=True,
            min_lines=1,
            max_lines=5,
            filled=True,
            expand=True,
            on_submit=self.send_message_click,
            on_focus=self.new_message_focus,
            on_blur=self.new_message_clear_error,
            on_change=self.new_message_clear_error,
        )
        self.send_message = ft.IconButton(
            icon=ft.icons.SEND_ROUNDED,
            tooltip="Send message",
            on_click=self.send_message_click,
        )

        super().__init__([self.new_message, self.send_message])

    async def new_message_clear_error(self, e):
        e.control.error_text = ""
        await self.page.update_async()

    async def new_message_focus(self, e):
        if await self.persistent_storage.get("user_name"):
            e.control.prefix = ft.Text(
                f"{await self.persistent_storage.get('user_name')}: "
            )

            channel = await self.persistent_storage.get("channel")
            if channel:
                e.control.hint_text = f"Write a message on channel {channel}"
            else:
                e.control.hint_text = "Write a message..."

            await self.page.update_async()

    async def send_message_click(self, _):
        if self.new_message.value == "":
            return

        self.new_message.error_style = ft.TextStyle(size=16)

        disconnect_error = "Please connect to twitch before sending messages."

        websocket = await self.memory_storage.get("websocket")
        is_connected = websocket and await websocket.is_connected()
        if not is_connected:
            self.new_message.error_text = disconnect_error
            await self.update_async()
            return

        if not bool(await self.persistent_storage.get("user_name")):
            self.new_message.error_text = (
                "Please connect to twitch before sending messages."
            )
            await self.update_async()
            return

        if not await self.persistent_storage.get("channel"):
            self.new_message.error_text = (
                "Please connect to a channel before sending messages."
            )
            await self.update_async()
            return

        emote_map = {
            "catFight": Emote(
                id="643d8003f6c0390df3367b04",
                name="catFight",
                source=EmoteSource.SEVENTV,
            ),
            "Slapahomie": Emote(
                id="60f22ed831ba6ae62262f234",
                name="Slapahomie",
                source=EmoteSource.SEVENTV,
            ),
            "hola": Emote(
                id="9b76f5f0f02d42738d337082c0872b2c",
                name="hola",
                source=EmoteSource.TWITCH,
            ),
        }
        try:
            async with asyncio.timeout(2):
                await websocket.send_message(
                    await self.persistent_storage.get("channel"), self.new_message.value
                )
        except (asyncio.TimeoutError, Exception):
            await self.reconnect_callback(True)
            self.new_message.error_text = disconnect_error
            await self.update_async()
            return

        if await self.persistent_storage.get("color_switcher"):
            color = choice(list(NormalUserColor))
            try:
                await helix.update_chat_color(
                    await self.persistent_storage.get("app_id"),
                    await self.persistent_storage.get("token"),
                    await self.persistent_storage.get("user_id"),
                    str(color),
                )
            except Exception as e:
                logging.error(f"Switcher failed to switch user chat color: {e}")

        await self.chat_message_pubsub.send(
            Message(
                HasherinoUser(
                    name=await self.persistent_storage.get("user_name"),
                    badges=await self.memory_storage.get("user_badges"),
                    chat_color=await self.memory_storage.get("user_color"),
                ),
                elements=[
                    emote_map[element] if element in emote_map else element
                    for element in self.new_message.value.split(" ")
                ],
                message_type="chat_message",
                me=False,
            )
        )

        self.new_message.value = ""
        await self.new_message.focus_async()
        await self.page.update_async()


class SelectChatButton(ft.IconButton):
    def __init__(self, select_chat_click: Awaitable):
        super().__init__(icon=ft.icons.CHAT, on_click=select_chat_click)


class ChatContainer(ft.Container):
    class _UiUpdateType(Enum):
        NO_UPDATE = (auto(),)
        SCROLL = (auto(),)
        PAGE = (auto(),)

    def __init__(self, storage: AsyncKeyValueStorage, font_size_pubsub: PubSub):
        self.storage = storage
        self.font_size_pubsub = font_size_pubsub
        self.is_chat_scrolled_down = False
        self.chat = ft.Column(
            expand=True,
            spacing=0,
            run_spacing=0,
            scroll=ft.ScrollMode.ALWAYS,
            auto_scroll=False,
            on_scroll=self.on_scroll,
        )
        super().__init__(
            content=self.chat,
            border=ft.border.all(1, ft.colors.OUTLINE),
            border_radius=5,
            padding=10,
            expand=True,
        )
        self.scheduled_ui_update: self._UiUpdateType = self._UiUpdateType.NO_UPDATE
        asyncio.ensure_future(self.update_ui())

    async def update_ui(self):
        while True:
            match self.scheduled_ui_update:
                case self._UiUpdateType.SCROLL:
                    await self.chat.scroll_to_async(offset=-1, duration=10)
                case self._UiUpdateType.PAGE:
                    await self.page.update_async()
                case self._UiUpdateType.NO_UPDATE | _:
                    pass

            self.scheduled_ui_update = self._UiUpdateType.NO_UPDATE

            await asyncio.sleep(float(await self.storage.get("chat_update_rate")))

    async def on_scroll(self, event: ft.OnScrollEvent):
        self.is_chat_scrolled_down = isclose(
            event.pixels, event.max_scroll_extent, rel_tol=0.01
        )

    async def on_message(self, message: Message):
        if message.message_type == "chat_message":
            m = ChatMessage(
                message, self.page, await self.storage.get("chat_font_size")
            )
            await m.subscribe_to_font_size_change(self.font_size_pubsub)
        elif message.message_type == "login_message":
            theme_text_color = (
                ft.colors.WHITE
                if self.page.platform_brightness == ft.ThemeMode.DARK
                else ft.colors.BLACK
            )
            m = ft.Text(
                message.elements[0],
                italic=True,
                color=theme_text_color,
                size=await self.storage.get("chat_font_size"),
            )

        self.chat.controls.append(m)

        n_messages_to_remove = len(self.chat.controls) - await self.storage.get(
            "max_messages_per_chat"
        )
        if n_messages_to_remove > 0:
            del self.chat.controls[:n_messages_to_remove]
            logging.debug(
                f"Chat has {len(self.chat.controls)} lines in it, removed {n_messages_to_remove}"
            )

        if self.is_chat_scrolled_down:
            self.scheduled_ui_update = self._UiUpdateType.SCROLL
        elif (
            self.scheduled_ui_update != self._UiUpdateType.SCROLL
        ):  # Scroll already updates
            self.scheduled_ui_update = self._UiUpdateType.PAGE


class Hasherino:
    def __init__(
        self,
        font_size_pubsub: PubSub,
        memory_storage: AsyncKeyValueStorage,
        persistent_storage: AsyncKeyValueStorage,
        page: ft.Page,
    ) -> None:
        self.font_size_pubsub = font_size_pubsub
        self.memory_storage = memory_storage
        self.persistent_storage = persistent_storage
        self.page = page

    async def login_click(self, _):
        logging.debug("Clicked login")

        app_id = await self.persistent_storage.get("app_id")
        token = await user_auth.request_oauth_token(app_id)
        users = await helix.get_users(app_id, token, [])

        if users:
            websocket: TwitchWebsocket = await self.memory_storage.get("websocket")

            asyncio.ensure_future(
                websocket.listen_message(
                    message_callback=self.message_received,
                    reconnect_callback=self.status_column.set_reconnecting_status,
                    token=token,
                    username=users[0].login,
                )
            )

            asyncio.gather(
                self.persistent_storage.set("token", token),
                self.persistent_storage.set("user_name", users[0].display_name),
                self.persistent_storage.set("user_id", users[0].id),
                self.memory_storage.set(
                    "ttv_badges", await helix.get_global_badges(app_id, token)
                ),
            )
        else:
            self.page.dialog = ft.AlertDialog(
                content=ft.Text("Failed to authenticate.")
            )
            self.page.dialog.open = True

        await self.page.update_async()

    async def settings_click(self, _):
        logging.debug("Clicked on settings")
        sv = SettingsView(self.font_size_pubsub, self.persistent_storage)
        await sv.init()
        self.page.views.append(sv)
        await self.page.update_async()

    async def message_received(self, message: ParsedMessage):
        logging.debug(f"Received message with command {message.get_command()}")

        match message.get_command():
            case Command.USERSTATE | Command.GLOBALUSERSTATE:
                if (
                    message.get_author_displayname().lower()
                    == (await self.persistent_storage.get("user_name")).lower()
                ):
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(
                            self.memory_storage.set(
                                "user_badges",
                                message.get_badges(
                                    await self.memory_storage.get("ttv_badges")
                                ),
                            )
                        )

                        tg.create_task(
                            self.memory_storage.set(
                                "user_color", message.get_author_chat_color()
                            )
                        )

            case Command.PRIVMSG:
                author: str = message.get_author_displayname()

                emote_map = {}

                await self.chat_message_pubsub.send(
                    Message(
                        HasherinoUser(
                            name=author,
                            badges=message.get_badges(
                                await self.memory_storage.get("ttv_badges")
                            ),
                            chat_color=message.get_author_chat_color(),
                        ),
                        elements=[
                            emote_map[element] if element in emote_map else element
                            for element in message.get_message_text().split(" ")
                        ],
                        message_type="chat_message",
                        me=message.is_me(),
                    )
                )
            case _:
                pass

    async def select_chat_click(self, _):
        channel = ft.TextField(label="Channel")
        logging.debug("Clicked on select chat")

        async def join_chat_click(_):
            websocket: TwitchWebsocket = await self.memory_storage.get("websocket")
            self.page.dialog.open = False
            await self.page.update_async()

            if await self.persistent_storage.get("channel"):
                logging.info(
                    f"Leaving channel {await self.persistent_storage.get('channel')}"
                )
                await websocket.leave_channel(
                    await self.persistent_storage.get("channel")
                )

            logging.info(f"Joining channel {channel.value}")
            await websocket.join_channel(channel.value)
            await self.persistent_storage.set("channel", channel.value)
            await self.page.update_async()

        channel.on_submit = join_chat_click

        self.page.dialog = ft.AlertDialog(
            content=channel,
            actions=[ft.ElevatedButton(text="Join", on_click=join_chat_click)],
        )
        self.page.dialog.open = True
        await self.page.update_async()

    async def on_resize(self, _):
        if self.page.window_height > 100 and self.page.window_width > 100:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(
                    self.persistent_storage.set(
                        "window_height", self.page.window_height
                    )
                )
                tg.create_task(
                    self.persistent_storage.set("window_width", self.page.window_width)
                )

    async def run(self):
        self.page.window_width = await self.persistent_storage.get("window_width")
        self.page.window_height = await self.persistent_storage.get("window_height")

        match await self.persistent_storage.get("theme"):
            case "System":
                self.page.theme_mode = ft.ThemeMode.SYSTEM
            case "Dark mode":
                self.page.theme_mode = ft.ThemeMode.DARK
            case "Light mode":
                self.page.theme_mode = ft.ThemeMode.LIGHT
            case _:
                pass

        self.page.on_resize = self.on_resize
        self.page.horizontal_alignment = "stretch"
        self.page.title = "hasherino"

        self.chat_message_pubsub = PubSub()
        self.page.dialog = AccountDialog(self.persistent_storage)
        self.status_column = StatusColumn(self.memory_storage, self.persistent_storage)
        chat_container = ChatContainer(self.persistent_storage, self.font_size_pubsub)
        self.new_message_row = NewMessageRow(
            self.memory_storage,
            self.persistent_storage,
            self.chat_message_pubsub,
            self.status_column.set_reconnecting_status,
        )
        self.select_chat_button = SelectChatButton(self.select_chat_click)

        await self.chat_message_pubsub.subscribe(chat_container.on_message)

        # Add everything to the page
        await self.page.add_async(
            ft.Row(
                [
                    ft.IconButton(icon=ft.icons.LOGIN, on_click=self.login_click),
                    self.select_chat_button,
                    ft.IconButton(icon=ft.icons.SETTINGS, on_click=self.settings_click),
                ]
            ),
            chat_container,
            self.new_message_row,
            self.status_column,
        )

        if await self.persistent_storage.get("user_name"):
            websocket: TwitchWebsocket = await self.memory_storage.get("websocket")

            asyncio.ensure_future(
                websocket.listen_message(
                    message_callback=self.message_received,
                    reconnect_callback=self.status_column.set_reconnecting_status,
                    token=await self.persistent_storage.get("token"),
                    username=await self.persistent_storage.get("user_name"),
                    join_channel=await self.persistent_storage.get("channel"),
                )
            )
            await self.memory_storage.set(
                "ttv_badges",
                await helix.get_global_badges(
                    await self.persistent_storage.get("app_id"),
                    await self.persistent_storage.get("token"),
                ),
            )


class StatusColumn(ft.Column):
    def __init__(
        self,
        memory_storage: AsyncKeyValueStorage,
        persistent_storage: AsyncKeyValueStorage,
    ):
        self.reconnecting_status = ft.Row(
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.ProgressRing(width=16, height=16, stroke_width=2),
                ft.Text("Reconnecting..."),
            ],
        )

        self.memory_storage = memory_storage
        self.persistent_storage = persistent_storage

        super().__init__()

    async def set_reconnecting_status(self, reconnecting: bool):
        await self.memory_storage.set("reconnecting", reconnecting)

        if reconnecting:
            self.controls.append(self.reconnecting_status)
        else:
            if self.reconnecting_status in self.controls:
                self.controls.remove(self.reconnecting_status)

            channel = await self.persistent_storage.get("channel")
            if channel:
                websocket = await self.memory_storage.get("websocket")
                await websocket.join_channel(channel)

        await self.page.update_async()


async def main(page: ft.Page):
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(name)s | %(filename)s | %(levelname)s | %(funcName)s | %(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),  # Outputs logs to the console
            logging.FileHandler("hasherino.log", mode="w"),
        ],
    )

    websockets_logger = logging.getLogger("websockets")
    websockets_logger.setLevel(logging.INFO)

    persistent_storage = PersistentStorage()
    memory_storage = MemoryOnlyStorage(page)

    app_id = "hvmj7blkwy2gw3xf820n47i85g4sub"

    websocket = TwitchWebsocket()
    await memory_storage.set("websocket", websocket)

    if await persistent_storage.get("token"):
        renewed_token = await user_auth.request_oauth_token(
            app_id, await persistent_storage.get("token")
        )
        await persistent_storage.set("token", renewed_token)

    if not await persistent_storage.get("not_first_run"):
        async with asyncio.TaskGroup() as tg:
            tg.create_task(persistent_storage.set("window_width", 500))
            tg.create_task(persistent_storage.set("chat_font_size", 18))
            tg.create_task(persistent_storage.set("chat_update_rate", 0.5))
            tg.create_task(persistent_storage.set("max_messages_per_chat", 100))
            tg.create_task(persistent_storage.set("window_height", 800))
            tg.create_task(persistent_storage.set("theme", "System"))
            tg.create_task(persistent_storage.set("app_id", app_id))
            tg.create_task(persistent_storage.set("not_first_run", True))
            tg.create_task(persistent_storage.set("color_switcher", False))

    hasherino = Hasherino(PubSub(), memory_storage, persistent_storage, page)
    await hasherino.run()


def run_hasherino():
    # Script entrypoint
    ft.app(target=main)


if __name__ == "__main__":
    run_hasherino()
