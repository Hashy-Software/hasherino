import asyncio
import logging
from random import choice
from typing import Coroutine

import flet as ft

from hasherino import helix
from hasherino.hasherino_dataclasses import Emote, EmoteSource, HasherinoUser, Message
from hasherino.helix import NormalUserColor
from hasherino.pubsub import PubSub
from hasherino.storage import AsyncKeyValueStorage


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

        if not self.page.is_ctrl_pressed:
            self.new_message.value = ""

        await self.new_message.focus_async()
        await self.page.update_async()

        if await self.persistent_storage.get("color_switcher"):
            # Using user_color can cause the color to repeat , since it gets replaced on USERSTATE messages
            color_index = await self.memory_storage.get("user_color_index")

            if not color_index:
                color_index = 0

            color_list = [str(c).upper() for c in list(NormalUserColor)]

            color_index = (color_index + 1) % len(color_list)

            try:
                next_color = color_list[color_index]
                logging.debug(
                    f"Next color index: {color_index}. List: {', '.join(color_list)}"
                )
                await self.memory_storage.set("user_color_index", color_index)
            except (ValueError, IndexError) as e:
                logging.error(f"Error trying to get next switcher chat color: {e}")
                next_color = choice(color_list)

            try:
                await helix.update_chat_color(
                    await self.persistent_storage.get("app_id"),
                    await self.persistent_storage.get("token"),
                    await self.persistent_storage.get("user_id"),
                    next_color,
                )
                logging.info(f"Switcher set user color to {next_color}")

            except Exception as e:
                logging.error(f"Switcher failed to switch user chat color: {e}")
