import flet as ft

from hasherino.storage import AsyncKeyValueStorage


class StatusColumn(ft.Column):
    def __init__(
        self,
        memory_storage: AsyncKeyValueStorage,
        persistent_storage: AsyncKeyValueStorage,
    ):
        self.reconnecting_status = ft.Row(
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.ProgressRing(width=16, height=16, stroke_width=2),
                ft.Text("Reconnecting..."),
            ],
        )

        self.memory_storage = memory_storage
        self.persistent_storage = persistent_storage

        super().__init__()

    async def set_reconnecting_status(self, reconnecting: bool):
        await self.memory_storage.set("reconnecting", reconnecting)

        if reconnecting:
            self.controls.append(self.reconnecting_status)
        else:
            if self.reconnecting_status in self.controls:
                self.controls.remove(self.reconnecting_status)

            channel = await self.persistent_storage.get("channel")
            if channel:
                websocket = await self.memory_storage.get("websocket")
                await websocket.join_channel(channel)

        await self.page.update_async()
