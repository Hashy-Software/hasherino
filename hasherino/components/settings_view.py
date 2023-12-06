import logging
from pathlib import Path

import flet as ft

from hasherino.pubsub import PubSub
from hasherino.storage import AsyncKeyValueStorage, get_default_os_settings_path

LOG_PATH = get_default_os_settings_path() / "hasherino.log"


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
                    ft.Row(
                        controls=[
                            ft.Text(
                                "Chat font size",
                                size=16,
                            ),
                            ft.Slider(
                                value=await self.storage.get("chat_font_size"),
                                min=10,
                                max=50,
                                divisions=40,
                                label="{value}",
                                on_change_end=self._font_size_change,
                                expand=True,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Text(),
                    ft.Row(
                        controls=[
                            ft.Text("Theme", size=16),
                            ft.Dropdown(
                                value=await self.storage.get("theme"),
                                options=[
                                    ft.dropdown.Option("System"),
                                    ft.dropdown.Option("Dark mode"),
                                    ft.dropdown.Option("Light mode"),
                                ],
                                width=200,
                                on_change=self._theme_select,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Text(),
                    ft.Row(
                        controls=[
                            ft.Text("Chat color cycling", size=16),
                            ft.Checkbox(
                                value=await self.storage.get("color_switcher"),
                                label_position=ft.LabelPosition.LEFT,
                                on_change=self._on_color_switcher_click,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
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
                                value=str(LOG_PATH.absolute()),
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
        await self.page.set_clipboard_async(str(LOG_PATH.absolute()))

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
