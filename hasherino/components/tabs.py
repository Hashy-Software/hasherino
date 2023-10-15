import logging

import flet as ft

from hasherino.storage import AsyncKeyValueStorage
from hasherino.twitch_websocket import TwitchWebsocket


class Tabs(ft.Tabs):
    def __init__(
        self,
        memory_storage: AsyncKeyValueStorage,
        persistent_storage: AsyncKeyValueStorage,
    ):
        super().__init__(
            tabs=[],
            on_change=self.change,
        )
        self.memory_storage = memory_storage
        self.persistent_storage = persistent_storage

    async def add_tab(self, channel: str):
        tab = ft.Tab(
            tab_content=ft.Row(
                controls=[
                    ft.Text(channel),
                ]
            ),
        )
        tab.tab_name = channel
        close_button = ft.IconButton(icon=ft.icons.CLOSE, on_click=self.close)
        close_button.parent_tab = tab
        tab.tab_content.controls.append(close_button)
        self.tabs = [tab]
        logging.info(f"Added tab {channel}")
        await self.page.add_async()

    async def close(self, button_click: ft.ControlEvent):
        websocket: TwitchWebsocket = await self.memory_storage.get("websocket")
        tab_name = button_click.control.parent_tab.tab_name
        await websocket.leave_channel(tab_name)
        self.tabs.remove(button_click.control.parent_tab)
        await self.persistent_storage.set("channel", None)
        logging.info(f"Closed tab {tab_name}")
        await self.page.add_async()

    async def change(self, e):
        tab = e.control.tabs[e.control.selected_index]
