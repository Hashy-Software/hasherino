import asyncio
import logging

import flet as ft

from hasherino import user_auth
from hasherino.api import helix
from hasherino.components import (
    AccountDialog,
    ChatContainer,
    NewMessageRow,
    SettingsView,
    StatusColumn,
    Tabs,
)
from hasherino.components.settings_view import LOG_PATH
from hasherino.factory import message_factory
from hasherino.hasherino_dataclasses import Emote, HasherinoUser
from hasherino.pubsub import PubSub
from hasherino.storage import (
    AsyncKeyValueStorage,
    MemoryOnlyStorage,
    PersistentStorage,
    get_default_os_settings_path,
)
from hasherino.twitch_websocket import Command, ParsedMessage, TwitchWebsocket


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
        self.page.is_ctrl_pressed = False
        self.message_listener: None | asyncio.Task = None
        self.emote_set_cache: dict[str, list[Emote]] = dict()

    async def login_click(self, _):
        logging.debug("Clicked login")

        app_id = await self.persistent_storage.get("app_id")
        token = await user_auth.request_oauth_token(app_id)
        users = await helix.get_users(app_id, token, [])

        if users:
            websocket: TwitchWebsocket = await self.memory_storage.get("websocket")

            if self.message_listener:
                self.message_listener.cancel()
                self.message_listener = None

            self.message_listener = asyncio.create_task(
                websocket.listen_message(
                    message_callback=self.message_received,
                    reconnect_callback=self.status_column.set_reconnecting_status,
                    token=token,
                    username=users[0].login,
                    join_channel=await self.persistent_storage.get("channel"),
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
            case Command.USERSTATE:
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

                        if not await self.memory_storage.get("ttv_emote_sets"):
                            emotes: dict[str, Emote] = dict()

                            for emote_obj in await helix.get_all_emote_sets(
                                await self.persistent_storage.get("app_id"),
                                await self.persistent_storage.get("token"),
                                set(message.get_emote_sets()),
                            ):
                                emotes[emote_obj["name"]] = Emote(
                                    name=emote_obj["name"],
                                    id=emote_obj["id"],
                                    url=f"https://static-cdn.jtvnw.net/emoticons/v2/{emote_obj['id']}/default/dark/2.0",
                                )

                            tg.create_task(
                                self.memory_storage.set("ttv_emote_sets", emotes)
                            )

            case Command.PRIVMSG:
                author: str = message.get_author_displayname()

                emote_map: dict[str, Emote] = await self.memory_storage.get(
                    "ttv_emote_sets"
                )

                stv_emotes: dict[
                    str, dict[str, Emote]
                ] | None = await self.memory_storage.get("7tv_emotes")
                channel = await self.persistent_storage.get("channel")
                if stv_emotes and channel:
                    channel_stv_emotes = stv_emotes.get(
                        await self.persistent_storage.get("channel"), {}
                    )
                else:
                    channel_stv_emotes = {}

                emote_map.update(channel_stv_emotes)

                message_obj = message_factory(
                    HasherinoUser(
                        name=author,
                        badges=message.get_badges(
                            await self.memory_storage.get("ttv_badges")
                        ),
                        chat_color=message.get_author_chat_color(),
                    ),
                    message,
                    emote_map,
                )
                await self.chat_container_on_msg(message_obj)

            case _:
                pass

    async def select_chat_click(self, _):
        channel = ft.TextField(label="Channel", autofocus=True)
        logging.debug("Clicked on select chat")

        async def join_chat_click(_):
            websocket: TwitchWebsocket = await self.memory_storage.get("websocket")
            channel.error_text = ""

            if await self.persistent_storage.get("channel"):
                logging.info(
                    f"Leaving channel {await self.persistent_storage.get('channel')}"
                )
                await websocket.leave_channel(
                    await self.persistent_storage.get("channel")
                )

            logging.info(f"Joining channel {channel.value}")

            try:
                await websocket.join_channel(channel.value)
            except Exception:
                channel.error_text = f"Not logged in"
                logging.error(channel.error_text)
                await self.page.update_async()
                return

            await self.tabs.add_tab(channel.value)
            await self.persistent_storage.set("channel", channel.value)
            self.page.dialog.open = False

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

    async def on_kb_event(self, e: ft.KeyboardEvent):
        self.page.is_ctrl_pressed = e.ctrl

        if e.key == "E" and e.ctrl:
            await self.new_message_row.emote_completion()

        elif e.key == "U" and e.ctrl:
            await self.new_message_row.user_completion()

    async def run(self):
        self.page.window_width = await self.persistent_storage.get("window_width")
        self.page.window_height = await self.persistent_storage.get("window_height")
        self.page.on_keyboard_event = self.on_kb_event

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
        self.page.title = "Hasherino"

        self.page.dialog = AccountDialog(self.persistent_storage)
        self.page.dialog.open = False

        self.status_column = StatusColumn(self.memory_storage, self.persistent_storage)
        chat_container = ChatContainer(
            self.persistent_storage, self.memory_storage, self.font_size_pubsub
        )
        self.new_message_row = NewMessageRow(
            self.memory_storage,
            self.persistent_storage,
            chat_container.on_message,
            self.status_column.set_reconnecting_status,
        )
        self.tabs = Tabs(self.memory_storage, self.persistent_storage)

        self.chat_container_on_msg = chat_container.on_message

        # Add everything to the page
        await self.page.add_async(
            ft.Row(
                [
                    self.tabs,
                    ft.Row(
                        controls=[
                            ft.IconButton(
                                icon=ft.icons.LOGIN, on_click=self.login_click
                            ),
                            ft.IconButton(
                                icon=ft.icons.CHAT, on_click=self.select_chat_click
                            ),
                            ft.IconButton(
                                icon=ft.icons.SETTINGS, on_click=self.settings_click
                            ),
                        ]
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            chat_container,
            self.new_message_row,
            self.status_column,
        )

        if user_name := await self.persistent_storage.get("user_name"):
            websocket: TwitchWebsocket = await self.memory_storage.get("websocket")

            channel = await self.persistent_storage.get("channel")
            token = await self.persistent_storage.get("token")

            self.message_listener = asyncio.create_task(
                websocket.listen_message(
                    message_callback=self.message_received,
                    reconnect_callback=self.status_column.set_reconnecting_status,
                    token=token,
                    username=user_name,
                    join_channel=channel,
                )
            )

            if channel:
                await self.tabs.add_tab(channel)

            await self.memory_storage.set(
                "ttv_badges",
                await helix.get_global_badges(
                    await self.persistent_storage.get("app_id"),
                    token,
                ),
            )


async def main(page: ft.Page):
    # Make settings folder for user's OS if it doesn't exist
    if not get_default_os_settings_path().exists():
        # Uses print cause logging isn't set up at this point
        print(f"Making settings directory on {get_default_os_settings_path()}")
        get_default_os_settings_path().mkdir(parents=True)

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(name)s | %(filename)s | %(levelname)s | %(funcName)s | %(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),  # Outputs logs to the console
            logging.FileHandler(LOG_PATH, mode="w"),
        ],
    )

    logging.getLogger("websockets").setLevel(logging.INFO)
    logging.getLogger("flet_core").setLevel(logging.INFO)
    logging.getLogger("flet_runtime").setLevel(logging.INFO)

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
            tg.create_task(persistent_storage.set("app_id", app_id))
            tg.create_task(persistent_storage.set("chat_font_size", 18))
            tg.create_task(persistent_storage.set("chat_update_rate", 0.5))
            tg.create_task(persistent_storage.set("color_switcher", False))
            tg.create_task(persistent_storage.set("max_messages_per_chat", 100))
            tg.create_task(persistent_storage.set("not_first_run", True))
            tg.create_task(persistent_storage.set("theme", "System"))
            tg.create_task(persistent_storage.set("window_width", 500))
            tg.create_task(persistent_storage.set("window_height", 800))

    hasherino = Hasherino(PubSub(), memory_storage, persistent_storage, page)
    await hasherino.run()


def run_hasherino():
    # Script entrypoint
    ft.app(target=main)


if __name__ == "__main__":
    run_hasherino()
