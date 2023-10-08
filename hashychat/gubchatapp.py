import asyncio
import logging

import flet as ft

from gubchat import database, helix
from gubchat.twitch_websocket import ParsedMessage, TwitchWebsocket
from gubchat.user_auth import request_oauth_token

_APP_ID = "hvmj7blkwy2gw3xf820n47i85g4sub"
_FONT_SIZE = "18sp"

_twitch_websocket = None
_message_queue = asyncio.Queue()


async def connect_from_saved():
    try:
        user = await database.get_active_twitch_account()

        if user:
            await twitch_connect(user.username, user.last_used_channel)
    except Exception as e:
        logging.error(
            f"Exception thrown while trying to connect to twitch using database data: {e}"
        )
        user = None


async def twitch_connect(username: str, channel: str):
    account = await database.get_twitch_account(username)

    if account is None:
        account = database.TwitchAccount(username=username)

        user = (await helix.get_users(_APP_ID, account.oauth_token, [username]))[0]
        color_info = (
            await helix.get_user_chat_color(_APP_ID, account.oauth_token, [user.id])
        )[0]

        account.twitch_id = user.id
        account.chat_color = color_info.color
        account.is_active = True

    # Update current/get a new token
    account.oauth_token = await request_oauth_token(_APP_ID, account.oauth_token)
    account.last_used_channel = channel

    await database.add_twitch_accounts(account)

    global _twitch_websocket

    _twitch_websocket = TwitchWebsocket()
    await _twitch_websocket.connect_websocket()

    await _twitch_websocket.authenticate(account.oauth_token, username)

    await _twitch_websocket.join_channel(channel)


async def update_configs_from_parsed_messages(messages: list[ParsedMessage]):
    """
    Get user-id and update user's chat color from USERSTATE messages
    """
    try:
        for message in messages:
            if not message:
                continue

            if not hasattr(message, "command"):
                continue

            if not hasattr(message, "tags"):
                continue

            if message.command is None or message.tags is None:
                continue

            command = message.command.get("command", "")
            username = message.tags.get("display-name", "")

            if not command or not username:
                continue

            if command not in ("USERSTATE", "GLOBALUSERSTATE", "PRIVMSG"):
                continue

            account = await database.get_active_twitch_account()
            if not account:
                continue

            if command == "PRIVMSG" and account.username != username:
                continue

            logging.debug(f"Using data from userstate: {message}")
            account.chat_color = message.tags["color"]
            is_updated = await database.add_twitch_accounts(account)
            if not is_updated:
                logging.warn(f"Failed to update color for {account.username}")

    except Exception as e:
        logging.error(
            f"Failed to get user chat color from parsed global state message: {e}"
        )


class Message:
    def __init__(self, user_name: str, text: str, message_type: str):
        self.user_name = user_name
        self.text = text
        self.message_type = message_type


class ChatMessage(ft.Row):
    def __init__(self, message: Message):
        super().__init__()
        self.vertical_alignment = "start"
        self.controls = [
            ft.CircleAvatar(
                content=ft.Text(self.get_initials(message.user_name)),
                color=ft.colors.WHITE,
                bgcolor=self.get_avatar_color(message.user_name),
            ),
            ft.Column(
                [
                    ft.Text(message.user_name, weight="bold"),
                    ft.Text(message.text, selectable=True),
                ],
                tight=True,
                spacing=5,
            ),
        ]

    def get_initials(self, user_name: str):
        return user_name[:1].capitalize()

    def get_avatar_color(self, user_name: str):
        colors_lookup = [
            ft.colors.AMBER,
            ft.colors.BLUE,
            ft.colors.BROWN,
            ft.colors.CYAN,
            ft.colors.GREEN,
            ft.colors.INDIGO,
            ft.colors.LIME,
            ft.colors.ORANGE,
            ft.colors.PINK,
            ft.colors.PURPLE,
            ft.colors.RED,
            ft.colors.TEAL,
            ft.colors.YELLOW,
        ]
        return colors_lookup[hash(user_name) % len(colors_lookup)]


async def main(page: ft.Page):
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
                    user_name=join_user_name.value,
                    text=f"{join_user_name.value} has joined the chat.",
                    message_type="login_message",
                )
            )
            page.update()

    def send_message_click(e):
        if new_message.value != "":
            page.pubsub.send_all(
                Message(
                    page.session.get("user_name"),
                    new_message.value,
                    message_type="chat_message",
                )
            )
            new_message.value = ""
            new_message.focus()
            page.update()

    def on_message(message: Message):
        if message.message_type == "chat_message":
            m = ChatMessage(message)
        elif message.message_type == "login_message":
            m = ft.Text(message.text, italic=True, color=ft.colors.BLACK45, size=12)
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


if __name__ == "__main__":
    ft.app(main)
    # asyncio.run(chat_app.async_run())
