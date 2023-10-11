import asyncio
import logging
from abc import ABC
from math import isclose
from typing import Any, Awaitable

import flet as ft

from hasherino import helix, user_auth
from hasherino.dataclasses import Emote, EmoteSource, Message, User
from hasherino.twitch_websocket import Command, ParsedMessage, TwitchWebsocket


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
                ft.Tabs(
                    tabs=[
                        await self._get_general_tab(),
                        await self._get_appearance_tab(),
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
                ],
            ),
        )

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
            ws: TwitchWebsocket = await self.storage.get("websocket")
            await ws.send_message(
                await self.storage.get("channel"), self.new_message.value
            )

            await self.chat_message_pubsub.send(
                Message(
                    User(
                        name=await self.storage.get("user_name"),
                        badges=await self.storage.get("user_badges"),
                        chat_color=await self.storage.get("user_color"),
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
            m = ft.Text(
                message.elements[0],
                italic=True,
                color=ft.colors.WHITE,
                size=await self.storage.get("chat_font_size"),
            )

        self.chat.controls.append(m)

        n_messages_to_remove = len(self.chat.controls) - await self.storage.get(
            "max_messages_per_chat"
        )
        if n_messages_to_remove > 0:
            del self.chat.controls[:n_messages_to_remove]

        if self.is_chat_scrolled_down:
            await self.chat.scroll_to_async(offset=-1, duration=10)
        else:
            await self.page.update_async()

        logging.debug(f"Chat has {len(self.chat.controls)} lines in it")


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

    async def settings_click(self, _):
        sv = SettingsView(self.font_size_pubsub, self.storage)
        await sv.init()
        self.page.views.append(sv)
        await self.page.update_async()

    async def message_received(self, message: ParsedMessage):
        match message.get_command():
            case Command.USERSTATE | Command.GLOBALUSERSTATE:
                if (
                    message.get_author_displayname().lower()
                    == (await self.storage.get("user_name")).lower()
                ):
                    await self.storage.set(
                        "user_badges",
                        message.get_badges(await self.storage.get("ttv_badges")),
                    )
                    await self.storage.set(
                        "user_color", message.get_author_chat_color()
                    )

            case Command.PRIVMSG:
                author: str = message.get_author_displayname()

                emote_map = {}

                await self.chat_message_pubsub.send(
                    Message(
                        User(
                            name=author,
                            badges=message.get_badges(
                                await self.storage.get("ttv_badges")
                            ),
                            chat_color=message.get_author_chat_color(),
                        ),
                        elements=[
                            emote_map[element] if element in emote_map else element
                            for element in message.get_message_text().split(" ")
                        ],
                        message_type="chat_message",
                    )
                )
            case _:
                pass

    async def select_chat_click(self, _):
        channel = ft.TextField(label="Channel")

        async def join_chat_click(_):
            websocket: TwitchWebsocket = await self.storage.get("websocket")
            self.page.dialog.open = False
            await self.page.update_async()
            await websocket.join_channel(channel.value)
            await self.storage.set("channel", channel.value)

            while True:
                task = asyncio.create_task(
                    websocket.listen_message(self.message_received)
                )

                while not task.done():
                    await asyncio.sleep(0.3)

        channel.on_submit = join_chat_click

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
        storage.set("max_messages_per_chat", 100),
        storage.set("app_id", "hvmj7blkwy2gw3xf820n47i85g4sub"),
        storage.set("websocket", websocket),
    )
    hasherino = Hasherino(PubSub(), storage, page)
    await hasherino.run()


def run_hasherino():
    # Script entrypoint
    ft.app(target=main)


if __name__ == "__main__":
    run_hasherino()
