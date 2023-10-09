"""
TODO:

"""
from abc import ABC
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable

import flet as ft

# from sqlalchemy.sql.compiler import selectable

_FONT_SIZE = 18


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
            await func(func.__self__, message)


class FontSizeSubscriber(ABC):
    async def on_font_size_changed(self, _, new_font_size: int):
        ...


class ChatText(ft.Text, FontSizeSubscriber):
    def __init__(self, text: str, color: str, weight=""):
        super().__init__(
            text, size=_FONT_SIZE, weight=weight, color=color, selectable=True
        )

    async def on_font_size_changed(self, _, new_font_size: int):
        self.size = new_font_size
        await self.page.update_async()


class ChatBadge(ft.Image, FontSizeSubscriber):
    def __init__(self, src: str, height: int):
        super().__init__(src=src, height=height)

    async def on_font_size_changed(self, _, new_font_size: int):
        self.height = new_font_size
        await self.page.update_async()


class ChatEmote(ft.Image, FontSizeSubscriber):
    async def on_font_size_changed(self, _, new_font_size: int):
        self.height = new_font_size * 2
        await self.page.update_async()


class ChatMessage(ft.Row):
    def __init__(self, message: Message, page: ft.Page):
        super().__init__()
        self.vertical_alignment = "start"
        self.wrap = True
        self.width = page.width
        self.page = page
        self.spacing = 5
        self.vertical_alignment = ft.CrossAxisAlignment.CENTER

        self.add_control_elements(message)

    def add_control_elements(self, message):
        self.controls = [
            ChatBadge(badge.get_url(), _FONT_SIZE) for badge in message.user.badges
        ]

        self.controls.append(
            ChatText(f"{message.user.name}: ", message.user.chat_color, weight="bold")
        )

        for element in message.elements:
            if type(element) == str:
                result = ChatText(element, ft.colors.WHITE)
            elif type(element) == Emote:
                result = ChatEmote(
                    src=element.get_url(),
                    height=_FONT_SIZE * 2,
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


async def settings_view(page: ft.Page, font_size_pubsub: PubSub) -> ft.View:
    async def back_click(_):
        page.views.pop()
        await page.update_async()

    async def font_size_change(e):
        global _FONT_SIZE
        _FONT_SIZE = e.control.value
        await font_size_pubsub.send(_FONT_SIZE)

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
                                ft.Text("Font size:", size=_FONT_SIZE),
                                ft.Slider(
                                    value=_FONT_SIZE,
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


async def main(page: ft.Page):
    page.horizontal_alignment = "stretch"
    page.title = "hasharino"

    async def join_chat_click(e):
        if not join_user_name.value:
            join_user_name.error_text = "Name cannot be blank!"
            await join_user_name.update_async()
        else:
            page.session.set("user_name", join_user_name.value)
            page.dialog.open = False
            new_message.prefix = ft.Text(f"{join_user_name.value}: ")
            await page.pubsub.send_all_async(
                Message(
                    user=User(name=join_user_name.value),
                    elements=[f"{join_user_name.value} has joined the chat."],
                    message_type="login_message",
                )
            )
            await page.update_async()

    async def send_message_click(e):
        if new_message.value != "":
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
            await page.pubsub.send_all_async(
                Message(
                    User(
                        name=page.session.get("user_name"),
                        badges=[
                            Badge(
                                "Prime gaming", "bbbe0db0-a598-423e-86d0-f9fb98ca1933"
                            )
                        ],
                        chat_color="#ff0000",
                    ),
                    elements=[
                        emote_map[element] if element in emote_map else element
                        for element in new_message.value.split(" ")
                    ],
                    message_type="chat_message",
                )
            )
            new_message.value = ""
            await new_message.focus_async()
            await page.update_async()

    font_size_pubsub = PubSub()

    async def on_message(message: Message):
        if message.message_type == "chat_message":
            m = ChatMessage(message, page)
            await m.subscribe_to_font_size_change(font_size_pubsub)
        elif message.message_type == "login_message":
            m = ft.Text(
                message.elements[0], italic=True, color=ft.colors.WHITE, size=_FONT_SIZE
            )
        chat.controls.append(m)
        await page.update_async()

    await page.pubsub.subscribe_async(on_message)

    # A dialog asking for a user display name
    join_user_name = ft.TextField(
        label="Enter your name to join the chat",
        autofocus=True,
        on_submit=join_chat_click,
    )
    page.dialog = ft.AlertDialog(
        open=True,
        modal=True,
        title=ft.Text("Welcome!"),
        content=ft.Column([join_user_name], width=300, height=70, tight=True),
        actions=[ft.ElevatedButton(text="Join chat", on_click=join_chat_click)],
        actions_alignment="end",
    )

    async def login_click(_):
        page.dialog.open = True
        await page.update_async()

    async def settings_click(_):
        page.views.append(await settings_view(page, font_size_pubsub))
        await page.update_async()

    # Chat messages
    chat = ft.ListView(
        expand=True,
        spacing=10,
        auto_scroll=True,
    )

    # A new message entry form
    new_message = ft.TextField(
        hint_text="Write a message...",
        autofocus=True,
        shift_enter=True,
        min_lines=1,
        max_lines=5,
        filled=True,
        expand=True,
        on_submit=send_message_click,
    )

    # Add everything to the page
    await page.add_async(
        ft.Row(
            [
                ft.IconButton(icon=ft.icons.PERSON, on_click=login_click),
                ft.IconButton(icon=ft.icons.SETTINGS, on_click=settings_click),
            ]
        ),
        ft.Container(
            content=chat,
            border=ft.border.all(1, ft.colors.OUTLINE),
            border_radius=5,
            padding=10,
            expand=True,
        ),
        ft.Row(
            [
                new_message,
                ft.IconButton(
                    icon=ft.icons.SEND_ROUNDED,
                    tooltip="Send message",
                    on_click=send_message_click,
                ),
            ]
        ),
    )


if __name__ == "__main__":
    ft.app(target=main)
