"""
TODO:
- twitch emote support
- 7tv emote support
- add 7tv emotes via chat
"""
import asyncio
import logging
from abc import ABC
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable

import flet as ft
import uvloop

from hasherino import helix, user_auth
from hasherino.twitch_websocket import ParsedMessage, TwitchWebsocket


class AsyncKeyValueStorage(ABC):
    async def get(self, key) -> Any:
        pass

    async def set(self, key, value):
        pass

    async def remove(self, key):
        pass


class MemoryOnlyStorage(AsyncKeyValueStorage):
    def __init__(self, page: ft.Page) -> None:
        super().__init__()
        self.page = page

    async def get(self, key) -> Any:
        return self.page.session.get(key)

    async def set(self, key, value):
        self.page.session.set(key, value)

    async def remove(self, key):
        self.page.session.remove(key)


@dataclass
class Badge:
    id: str
    name: str
    url: str


@dataclass
class User:
    name: str
    badges: list[Badge] | None = None
    chat_color: str | None = None


class EmoteSource(Enum):
    TWITCH = 0
    SEVENTV = 1


@dataclass
class Emote:
    name: str
    id: str
    source: EmoteSource

    def get_url(self) -> str:
        match self.source:
            case EmoteSource.SEVENTV:
                return f"https://cdn.7tv.app/emote/{self.id}/4x.webp"
            case EmoteSource.TWITCH:
                return f"https://static-cdn.jtvnw.net/emoticons/v2/emotesv2_{self.id}/default/dark/3.0"
            case _:
                raise TypeError


@dataclass
class Message:
    user: User
    elements: list[str | Emote]
    message_type: str


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
        await self.page.update_async()


class ChatBadge(ft.Image, FontSizeSubscriber):
    def __init__(self, src: str, height: int):
        super().__init__(src=src, height=height)

    async def on_font_size_changed(self, new_font_size: int):
        self.height = new_font_size
        await self.page.update_async()


class ChatEmote(ft.Image, FontSizeSubscriber):
    async def on_font_size_changed(self, new_font_size: int):
        self.height = new_font_size * 2
        await self.page.update_async()


class ChatMessage(ft.Row):
    def __init__(self, message: Message, page: ft.Page, font_size: int):
        super().__init__()
        self.vertical_alignment = "start"
        self.wrap = True
        self.width = page.width
        self.page = page
        self.font_size = font_size
        self.spacing = 5
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
                result = ChatText(element, ft.colors.WHITE, self.font_size)
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
                ft.Tabs(tabs=[await self._get_appearance_tab()]),
            ],
        )

    async def _get_appearance_tab(self) -> ft.Tab:
        return ft.Tab(
            text="Appearance",
            icon=ft.icons.BRUSH,
            content=ft.Column(
                controls=[
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
                ],
            ),
        )

    async def _back_click(self, _):
        self.page.views.pop()
        await self.page.update_async()

    async def _font_size_change(self, e):
        await self.storage.set("chat_font_size", e.control.value)
        await self.font_size_pubsub.send(e.control.value)


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
    def __init__(self, storage: AsyncKeyValueStorage, chat_message_pubsub: PubSub):
        self.storage = storage
        self.chat_message_pubsub = chat_message_pubsub

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
        )
        super().__init__(
            [
                self.new_message,
                ft.IconButton(
                    icon=ft.icons.SEND_ROUNDED,
                    tooltip="Send message",
                    on_click=self.send_message_click,
                ),
            ]
        )

    async def new_message_focus(self, e):
        if await self.storage.get("user_name"):
            e.control.prefix = ft.Text(f"{await self.storage.get('user_name')}: ")
            await self.page.update_async()

    async def send_message_click(self, _):
        if self.new_message.value != "":
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
            await self.chat_message_pubsub.send(
                Message(
                    User(
                        name=await self.storage.get("user_name"),
                        badges=[],
                        chat_color="#ff0000",
                    ),
                    elements=[
                        emote_map[element] if element in emote_map else element
                        for element in self.new_message.value.split(" ")
                    ],
                    message_type="chat_message",
                )
            )
            self.new_message.value = ""
            await self.new_message.focus_async()
            await self.page.update_async()


class ChatContainer(ft.Container):
    def __init__(self, storage: AsyncKeyValueStorage, font_size_pubsub: PubSub):
        self.storage = storage
        self.font_size_pubsub = font_size_pubsub
        self.chat = ft.ListView(
            expand=True,
            spacing=10,
            auto_scroll=True,
        )
        super().__init__(
            content=self.chat,
            border=ft.border.all(1, ft.colors.OUTLINE),
            border_radius=5,
            padding=10,
            expand=True,
        )

    async def on_message(self, message: Message):
        if message.message_type == "chat_message":
            m = ChatMessage(
                message, self.page, await self.storage.get("chat_font_size")
            )
            await m.subscribe_to_font_size_change(self.font_size_pubsub)
        elif message.message_type == "login_message":
            m = ft.Text(
                message.elements[0],
                italic=True,
                color=ft.colors.WHITE,
                size=await self.storage.get("chat_font_size"),
            )
        self.chat.controls.append(m)
        await self.page.update_async()


class Hasherino:
    def __init__(
        self, font_size_pubsub: PubSub, storage: AsyncKeyValueStorage, page: ft.Page
    ) -> None:
        self.font_size_pubsub = font_size_pubsub
        self.storage = storage
        self.page = page

    async def login_click(self, _):
        app_id = await self.storage.get("app_id")
        token = await user_auth.request_oauth_token(app_id)
        users = await helix.get_users(app_id, token, [])

        if users:
            await self.storage.set("token", token)
            await self.storage.set("user_name", users[0].display_name)
            await self.storage.set("user", users[0])
            socket: TwitchWebsocket = await self.storage.get("websocket")
            await self.storage.set(
                "ttv_badges", await helix.get_global_badges(app_id, token)
            )
            await socket.authenticate(token, users[0].login)
        else:
            self.page.dialog = ft.AlertDialog(
                content=ft.Text("Failed to authenticate.")
            )
            self.page.dialog.open = True

        await self.page.update_async()

    async def get_badge(self, set_id: str, version: str) -> dict | None:
        try:
            emotes = await self.storage.get("ttv_badges")
            id_match = next((s for s in emotes if s["set_id"] == set_id))
            version_match = next(
                (s for s in id_match["versions"] if s["id"] == version)
            )
            return version_match
        except:
            return None

    async def settings_click(self, _):
        sv = SettingsView(self.font_size_pubsub, self.storage)
        await sv.init()
        self.page.views.append(sv)
        await self.page.update_async()

    async def select_chat_click(self, _):
        async def message_received(message: ParsedMessage):
            if message.command["command"] != "PRIVMSG":
                return

            author: str = message.source["nick"]
            color = message.tags["color"]
            badges: list[Badge] = []
            for id, version in message.tags["badges"].items():
                badge = await self.get_badge(id, version)
                if badge:
                    badges.append(Badge(id, badge["title"], badge["image_url_4x"]))
            message_text: str = message.parameters
            emote_map = {}

            await self.chat_message_pubsub.send(
                Message(
                    User(
                        name=author,
                        badges=badges,
                        chat_color=f"#{color}",
                    ),
                    elements=[
                        emote_map[element] if element in emote_map else element
                        for element in message_text.split(" ")
                    ],
                    message_type="chat_message",
                )
            )

        channel = ft.TextField(label="Channel")

        async def join_chat_click(_):
            websocket: TwitchWebsocket = await self.storage.get("websocket")
            self.page.dialog.open = False
            await self.page.update_async()
            await websocket.join_channel(channel.value)

            while True:
                task = asyncio.create_task(websocket.listen_message(message_received))
                while not task.done():
                    await asyncio.sleep(0.3)

        self.page.dialog = ft.AlertDialog(
            content=channel,
            actions=[ft.ElevatedButton(text="Join", on_click=join_chat_click)],
        )
        self.page.dialog.open = True
        await self.page.update_async()

    async def run(self):
        self.page.horizontal_alignment = "stretch"
        self.page.title = "hasherino"

        self.page.dialog = AccountDialog(self.storage)

        chat_container = ChatContainer(self.storage, self.font_size_pubsub)
        self.chat_message_pubsub = PubSub()
        await self.chat_message_pubsub.subscribe(chat_container.on_message)

        # Add everything to the page
        await self.page.add_async(
            ft.Row(
                [
                    ft.IconButton(icon=ft.icons.LOGIN, on_click=self.login_click),
                    ft.IconButton(icon=ft.icons.CHAT, on_click=self.select_chat_click),
                    ft.IconButton(icon=ft.icons.SETTINGS, on_click=self.settings_click),
                ]
            ),
            chat_container,
            NewMessageRow(self.storage, self.chat_message_pubsub),
        )


async def main(page: ft.Page):
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(name)s | %(filename)s | %(levelname)s | %(funcName)s | %(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler()],  # Outputs logs to the console
    )

    websockets_logger = logging.getLogger("websockets")
    websockets_logger.setLevel(logging.INFO)

    storage = MemoryOnlyStorage(page)
    websocket = TwitchWebsocket()
    asyncio.gather(
        websocket.connect_websocket(),
        storage.set("chat_font_size", 18),
        storage.set("app_id", "hvmj7blkwy2gw3xf820n47i85g4sub"),
        storage.set("websocket", websocket),
    )
    hasherino = Hasherino(PubSub(), storage, page)
    await hasherino.run()


def run_hasherino():
    # Script entrypoint
    uvloop.install()
    ft.app(target=main)


if __name__ == "__main__":
    run_hasherino()
