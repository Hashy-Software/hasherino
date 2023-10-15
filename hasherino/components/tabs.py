import flet as ft


class Tabs(ft.Tabs):
    def __init__(self):
        super().__init__(
            tabs=[],
            on_change=self.change,
        )

    async def add_tab(self, channel: str):
        self.tabs.append(
            ft.Tab(
                tab_content=ft.Row(
                    controls=[
                        ft.Text(channel),
                        ft.IconButton(icon=ft.icons.CLOSE),
                    ]
                ),
            )
        )

    async def change(self, e):
        tab = e.control.tabs[e.control.selected_index]
