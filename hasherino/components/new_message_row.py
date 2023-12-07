import asyncio
import logging
from random import choice
from typing import Awaitable

import flet as ft

from hasherino.api import helix
from hasherino.api.helix import NormalUserColor
from hasherino.hasherino_dataclasses import Emote, HasherinoUser, Message
from hasherino.storage import AsyncKeyValueStorage


class NewMessageRow(ft.Row):
    def __init__(
        self,
        memory_storage: AsyncKeyValueStorage,
        persistent_storage: AsyncKeyValueStorage,
        chat_container_on_message: Awaitable,
        reconnect_callback: Awaitable,
    ):
        self.memory_storage = memory_storage
        self.persistent_storage = persistent_storage
        self.chat_container_on_message = chat_container_on_message
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

    async def emote_completion(self):
        if not self.new_message.value:
            return

        stv_emotes = await self.memory_storage.get("7tv_emotes")
        channel_stv_emotes = (
            stv_emotes[await self.persistent_storage.get("channel")]
            if stv_emotes
            else {}
        )
        emote_map: dict[str, Emote] = await self.memory_storage.get("ttv_emote_sets")
        emote_names = sorted(list(emote_map.keys()) + list(channel_stv_emotes.keys()))

        if emote_names:
            last_space_index = self.new_message.value.rfind(" ")

            # If a space is not found it'll return -1, so getting the last word with last_space_index+1 works either way.
            last_word = self.new_message.value[last_space_index + 1 :]

            logging.debug(
                f"Attempting emote completion. last_space_index: {last_space_index} last_word: {last_word}"
            )

            for emote_name in emote_names:
                if emote_name.lower().startswith(last_word.lower()):
                    self.new_message.value = (
                        f"{self.new_message.value[:-len(last_word)]}{emote_name}"
                    )
                    logging.debug(
                        f"Found emote completion for {last_word} -> {emote_name}."
                    )
                    await self.new_message.update_async()
                    return

    async def user_completion(self):
        user_list = await self.memory_storage.get("channel_user_list")

        if user_list and self.new_message.value:
            last_space_index = self.new_message.value.rfind(" ")

            # If a space is not found it'll return -1, so getting the last word with last_space_index+1 works either way.
            last_word = self.new_message.value[last_space_index + 1 :]

            logging.debug(
                f"Attempting username completion. last_space_index: {last_space_index} last_word: {last_word}"
            )

            sorted_user_list = sorted(
                user_list[await self.persistent_storage.get("channel")]
            )

            for user in sorted_user_list:
                if user.lower().startswith(last_word.lower()):
                    self.new_message.value = (
                        f"{self.new_message.value[:-len(last_word)]}{user}"
                    )
                    logging.debug(
                        f"Found username completion for {last_word} -> {user}."
                    )
                    await self.new_message.update_async()
                    return

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

        emote_map: dict[str, Emote] = await self.memory_storage.get("ttv_emote_sets")

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

        await self.chat_container_on_message(
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
