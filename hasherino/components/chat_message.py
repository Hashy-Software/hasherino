from abc import ABC

import flet as ft

from hasherino.hasherino_dataclasses import Emote, Message
from hasherino.pubsub import PubSub


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
        self.run_spacing = 0
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
                color = message.user.chat_color if message.me else ""
                result = ChatText(element, color, self.font_size)
            elif type(element) == Emote:
                result = ChatEmote(
                    src=element.url,
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
