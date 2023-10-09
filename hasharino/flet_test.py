"""
TODO:

"""
from abc import ABC
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable

import flet as ft

# from sqlalchemy.sql.compiler import selectable


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
    name: str
    id: str

    def get_url(self) -> str:
        return f"https://static-cdn.jtvnw.net/badges/v1/{self.id}/2"


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
            ChatBadge(badge.get_url(), self.font_size) for badge in message.user.badges
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


async def settings_view(
    page: ft.Page, font_size_pubsub: PubSub, storage: AsyncKeyValueStorage
) -> ft.View:
    async def back_click(_):
        page.views.pop()
        await page.update_async()

    async def font_size_change(e):
        await storage.set("font_size", e.control.value)
        await font_size_pubsub.send(e.control.value)

    return ft.View(
        "/settings",
        [
            ft.IconButton(icon=ft.icons.ARROW_BACK, on_click=back_click),
            ft.Tabs(
                tabs=[
                    ft.Tab(
                        text="Appearance",
                        icon=ft.icons.BRUSH,
                        content=ft.Column(
                            controls=[
                                ft.Text(
                                    "Font size:", size=await storage.get("font_size")
                                ),
                                ft.Slider(
                                    value=await storage.get("font_size"),
                                    min=10,
                                    max=50,
                                    divisions=40,
                                    label="{value}",
                                    width=500,
                                    on_change_end=font_size_change,
                                ),
                            ],
                        ),
                    )
                ]
            ),
        ],
    )


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
            await self.page.pubsub.send_all_async(
                Message(
                    user=User(name=self.join_user_name.value),
                    elements=[f"{self.join_user_name.value} has joined the chat."],
                    message_type="login_message",
                )
            )
            await self.page.update_async()


class NewMessageRow(ft.Row):
    def __init__(self, storage: AsyncKeyValueStorage):
        self.storage = storage

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
            await self.page.pubsub.send_all_async(
                Message(
                    User(
                        name=await self.storage.get("user_name"),
                        badges=[
                            Badge(
                                "Prime gaming",
                                "bbbe0db0-a598-423e-86d0-f9fb98ca1933",
                            )
                        ],
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
            m = ChatMessage(message, self.page, await self.storage.get("font_size"))
            await m.subscribe_to_font_size_change(self.font_size_pubsub)
        elif message.message_type == "login_message":
            m = ft.Text(
                message.elements[0],
                italic=True,
                color=ft.colors.WHITE,
                size=await self.storage.get("font_size"),
            )
        self.chat.controls.append(m)
        await self.page.update_async()


class Hasharino:
    def __init__(
        self, font_size_pubsub: PubSub, storage: AsyncKeyValueStorage, page: ft.Page
    ) -> None:
        self.font_size_pubsub = font_size_pubsub
        self.storage = storage
        self.page = page

    async def login_click(self, _):
        self.page.dialog.open = True
        await self.page.update_async()

    async def settings_click(self, _):
        self.page.views.append(
            await settings_view(self.page, self.font_size_pubsub, self.storage)
        )
        await self.page.update_async()

    async def run(self):
        self.page.horizontal_alignment = "stretch"
        self.page.title = "hasharino"

        self.page.dialog = AccountDialog(self.storage)

        chat_container = ChatContainer(self.storage, self.font_size_pubsub)
        await self.page.pubsub.subscribe_async(chat_container.on_message)

        # Add everything to the page
        await self.page.add_async(
            ft.Row(
                [
                    ft.IconButton(icon=ft.icons.PERSON, on_click=self.login_click),
                    ft.IconButton(icon=ft.icons.SETTINGS, on_click=self.settings_click),
                ]
            ),
            chat_container,
            NewMessageRow(self.storage),
        )


async def main(page: ft.Page):
    storage = MemoryOnlyStorage(page)
    await storage.set("font_size", 18)
    hasharino = Hasharino(PubSub(), storage, page)
    await hasharino.run()


if __name__ == "__main__":
    ft.app(target=main)
