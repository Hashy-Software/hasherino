"""
TODO:
- convert to async

"""
from dataclasses import dataclass

import flet as ft
from sqlalchemy.sql.compiler import selectable


@dataclass
class Badge:
    name: str
    id: str

    def get_url_1x(self) -> str:
        return f"https://static-cdn.jtvnw.net/badges/v1/{self.id}/1"


@dataclass
class User:
    name: str
    badges: list[Badge] | None = None
    chat_color: str | None = None


@dataclass
class Emote:
    name: str
    id: str

    def get_url_1x(self) -> str:
        return f"https://cdn.7tv.app/emote/{self.id}/1x.webp"


@dataclass
class Message:
    user: User
    elements: list[str | Emote]
    message_type: str


class ChatMessage(ft.Row):
    def __init__(self, message: Message, width: int):
        super().__init__()
        self.vertical_alignment = "start"
        self.wrap = True
        self.width = width
        self.spacing = 5
        height = 20
        self.controls = [
            ft.Image(src=badge.get_url_1x()) for badge in message.user.badges
        ]
        self.controls.append(
            ft.Text(
                f"{message.user.name}: ",
                color=message.user.chat_color,
                weight="bold",
            )
        )
        for element in message.elements:
            if type(element) == str:
                result = ft.Text(element, selectable=True)
            elif type(element) == Emote:
                result = ft.Image(
                    src=element.get_url_1x(), height=height, fit=ft.ImageFit.CONTAIN
                )
            else:
                raise TypeError

            self.controls.append(result)


def main(page: ft.Page):
    page.horizontal_alignment = "stretch"
    page.title = "Flet Chat"

    def join_chat_click(e):
        if not join_user_name.value:
            join_user_name.error_text = "Name cannot be blank!"
            join_user_name.update()
        else:
            page.session.set("user_name", join_user_name.value)
            page.dialog.open = False
            new_message.prefix = ft.Text(f"{join_user_name.value}: ")
            page.pubsub.send_all(
                Message(
                    user=User(name=join_user_name.value),
                    elements=[f"{join_user_name.value} has joined the chat."],
                    message_type="login_message",
                )
            )
            page.update()

    def send_message_click(e):
        if new_message.value != "":
            emote_map = {
                "baseg": Emote(id="62306782b88633b42c0bdd7b", name="baseg"),
            }
            page.pubsub.send_all(
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
            new_message.focus()
            page.update()

    def on_message(message: Message):
        if message.message_type == "chat_message":
            m = ChatMessage(message, page.window_width)
        elif message.message_type == "login_message":
            m = ft.Text(
                message.elements[0], italic=True, color=ft.colors.BLACK45, size=12
            )
        chat.controls.append(m)
        page.update()

    page.pubsub.subscribe(on_message)

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

    def login_click(e):
        page.dialog.open = True
        page.update()

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
    page.add(
        ft.ElevatedButton("Login", on_click=login_click),
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


ft.app(target=main)
