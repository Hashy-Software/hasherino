import asyncio
import logging
import sys

from kivy.app import App
from kivy.clock import Clock
from kivy.config import Config
from kivy.core.window import Window
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.font_definitions import theme_font_styles
from kivymd.theming import ThemeManager
from kivymd.uix.button import MDFloatingActionButton
from kivymd.uix.label import MDLabel
from kivymd.uix.list import IconLeftWidget, OneLineAvatarIconListItem
from kivymd.uix.navigationdrawer import MDNavigationDrawer, MDNavigationLayout
from kivymd.uix.textfield import MDTextField
from kivymd.uix.toolbar import MDTopAppBar

from gubchat import database, helix
from gubchat.twitch_websocket import ParsedMessage, TwitchWebsocket
from gubchat.user_auth import request_oauth_token

Window.softinput_mode = "pan"


_APP_ID = "hvmj7blkwy2gw3xf820n47i85g4sub"
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

    App.get_running_app().screen_manager.current = "Chat" if user else "Settings"


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
    App.get_running_app().screen_manager.current = "Chat"


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


class ScrollableLabel(ScrollView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = GridLayout(cols=1, size_hint_y=None)
        self.add_widget(self.layout)

        self.chat_history = MDLabel(
            size_hint_y=None,
            markup=True,
            font_style=theme_font_styles[6],
            theme_text_color="Primary",
        )
        self.scroll_to_point = MDLabel()

        self.layout.add_widget(self.chat_history)
        self.layout.add_widget(self.scroll_to_point)

    def update_chat_history(self, message_queue: asyncio.Queue):
        """
        Messages are tuples of chat_color, username, message
        """
        messages: str = ""

        while True:
            try:
                chat_color, username, message = message_queue.get_nowait()
                message = f"[color={chat_color}]{username} :[/color] {message}"
                messages = f"{messages}\n{message}"
            except asyncio.QueueEmpty:
                break

        while len(self.chat_history.text) > 10_000:
            self.chat_history.text = self.chat_history.text[
                self.chat_history.text.find("\n") + 1 :
            ]

        self.chat_history.text = f"{self.chat_history.text}{messages}"

        self.layout.height = self.chat_history.texture_size[1] + 15
        self.chat_history.height = self.chat_history.texture_size[1]
        self.chat_history.text_size = (self.chat_history.width * 0.98, None)

        self.scroll_to(self.scroll_to_point)

    def update_chat_history_layout(self, _=None):
        self.layout.height = self.chat_history.texture_size[1] + 15
        self.chat_history.height = self.chat_history.texture_size[1]
        self.chat_history.text_size = (self.chat_history.width * 0.98, None)


class ChatPage(GridLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cols = 1
        self.rows = 3
        self.padding = 5

        self.add_widget(MDLabel())
        self.history = ScrollableLabel(height=Window.size[1] * 0.788, size_hint_y=None)
        self.add_widget(self.history)

        self.new_msg = MDTextField(
            size_hint_x=None,
            multiline=False,
            pos_hint={"center_x": 0, "center_y": 1},
            on_text_validate=self.on_new_msg_enter_pressed,
        )
        bottom_line = GridLayout(cols=1)
        bottom_line.add_widget(self.new_msg)
        self.add_widget(bottom_line)

        Clock.schedule_once(self.focus_text_input, 0.4)

        Clock.schedule_once(lambda _: asyncio.ensure_future(self.listen_for_messages()))

        Clock.schedule_interval(
            lambda _: self.history.update_chat_history(_message_queue),
            0.3,
        )

        self.bind(size=self.adjust_fields)

    def adjust_fields(self, *_):
        if Window.size[1] * 0.1 < 70:
            new_height = Window.size[1] - 135
        else:
            new_height = Window.size[1] * 0.81
        self.history.height = new_height
        if Window.size[0] * 0.2 < 160:
            new_width = Window.size[0] - 70
        else:
            new_width = Window.size[0] * 0.91
        self.new_msg.width = new_width
        Clock.schedule_once(self.history.update_chat_history_layout, 0.01)

    def on_new_msg_enter_pressed(self, _):
        logging.debug("Sending message")
        asyncio.ensure_future(self.send_local_message())
        Clock.schedule_once(self.focus_text_input, 0.1)

    def focus_text_input(self, _):
        self.new_msg.focus = True

    async def send_local_message(self):
        msg = self.new_msg.text
        self.new_msg.text = ""

        if not msg:
            return

        account: database.TwitchAccount = await database.get_active_twitch_account()

        await _twitch_websocket.send_message(account.last_used_channel, msg)

        await _message_queue.put((account.chat_color, account.username, msg))

    def incoming_message(self, parsed_message: ParsedMessage):
        if parsed_message.command["command"] == "PRIVMSG":
            try:
                user = parsed_message.tags["display-name"]
                color = parsed_message.tags["color"]
                message = parsed_message.parameters
            except KeyError as e:
                logging.error(f"Failed to get parsed message data: {e}")
                return

            asyncio.ensure_future(_message_queue.put((color, user, message)))

        Clock.schedule_once(
            lambda _: asyncio.ensure_future(
                update_configs_from_parsed_messages([parsed_message])
            )
        )

    async def listen_for_messages(self):
        logging.debug("Listening for messages")

        while not _twitch_websocket:
            await asyncio.sleep(2)

        while True:
            task = asyncio.create_task(
                _twitch_websocket.listen_message(self.incoming_message)
            )

            while not task.done():
                await asyncio.sleep(0.2)


class SettingsPage(GridLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cols = 2
        self.padding = 10

        self.add_widget(MDLabel())
        self.add_widget(MDLabel())
        self.add_widget(
            MDLabel(text="User: ", halign="center", theme_text_color="Primary")
        )
        self.float = FloatLayout()
        self.user = MDTextField(
            text="",
            multiline=False,
            pos_hint={"x": 0, "y": 0.2},
            write_tab=False,
        )
        self.float.add_widget(self.user)
        self.add_widget(self.float)

        self.add_widget(
            MDLabel(
                text="Channel: ",
                halign="center",
                theme_text_color="Primary",
            )
        )
        self.float = FloatLayout()
        self.channel = MDTextField(
            text="",
            multiline=False,
            pos_hint={"x": 0, "y": 0.2},
            write_tab=False,
            on_text_validate=self.connect_button,
        )
        self.float.add_widget(self.channel)
        self.add_widget(self.float)

        self.float_layout = FloatLayout()
        self.connect_fab = MDFloatingActionButton(
            icon="arrow-right", pos_hint={"x": 0.68, "y": 0}
        )
        self.connect_fab.bind(on_release=self.connect_button)
        self.float_layout.add_widget(self.connect_fab)
        self.add_widget(MDLabel())
        self.add_widget(MDLabel())
        self.add_widget(MDLabel())
        self.add_widget(MDLabel())
        self.add_widget(MDLabel())
        self.add_widget(self.float_layout)

        # Uses Clock to focus so the animation doesn't look bugged
        Clock.schedule_once(self.focus_on_user_input, 0.5)

    def focus_on_user_input(self, _):
        self.user.focus = True

    def connect_button(self, _):
        logging.debug("Clicked connect button")

        Clock.schedule_once(
            lambda _: asyncio.ensure_future(
                twitch_connect(self.user.text.strip(), self.channel.text.strip())
            )
        )


class GubChatApp(MDApp):
    def build(self):
        app = MDApp.get_running_app()
        app.theme_cls = ThemeManager()
        app.theme_cls.primary_palette = "DeepPurple"
        app.theme_cls.accent_palette = "DeepPurple"
        app.theme_cls.theme_style = "Light"
        Window.borderless = False
        self.title = "GubChat"
        Config.set("kivy", "window_title", self.title)

        asyncio.ensure_future(database.create_db())

        self.root_sm = ScreenManager()
        rscreen = Screen(name="Root")

        self.nav_layout = MDNavigationLayout()
        self.nl_sm = ScreenManager()
        nl_screen = Screen(name="nl")
        self.toolbar = MDTopAppBar(
            pos_hint={"top": 1},
            elevation=9,
            title=self.title,
            md_bg_color=self.theme_cls.primary_color,
        )
        self.toolbar.left_action_items = [
            ["menu", lambda x: self.nav_drawer.set_state(new_state="toggle")]
        ]
        nl_screen.add_widget(self.toolbar)
        self.screen_manager = ScreenManager()

        self.create_chat_page()
        self.create_settings_page()

        asyncio.ensure_future(connect_from_saved())

        nl_screen.add_widget(self.screen_manager)
        self.nl_sm.add_widget(nl_screen)

        self.nav_drawer = MDNavigationDrawer(elevation=0)

        self.ndbox = BoxLayout(orientation="vertical", spacing="8dp")

        self.avatar = Image(
            size_hint=(None, None),
            size=(Window.size[0] * 0.65, Window.size[0] * 0.55),
            source="icon.png",
        )
        self.anchor = AnchorLayout(
            anchor_x="center", size_hint_y=None, height=self.avatar.height * 1.3
        )
        self.anchor.add_widget(MDLabel())

        self.fl = FloatLayout()
        self.fl.padding = 8
        self.sub_nav = OneLineAvatarIconListItem(
            text="Settings",
            theme_text_color="Primary",
            pos_hint={"center_x": 0.5, "center_y": 1},
            font_style="Button",
        )
        self.darkmode_icon = IconLeftWidget(
            icon="settings", pos_hint={"center_x": 1, "center_y": 0.55}
        )
        self.sub_nav.add_widget(self.darkmode_icon)
        self.fl.add_widget(self.sub_nav)
        self.darkmode_btn = OneLineAvatarIconListItem(
            text="Dark Mode",
            on_press=self.theme_change,
            on_release=lambda x: self.nav_drawer.set_state(new_state="toggle"),
            pos_hint={"center_x": 0.5, "center_y": 0.86},
        )
        self.darkmode_icon = IconLeftWidget(
            icon="theme-light-dark", pos_hint={"center_x": 1, "center_y": 0.55}
        )
        self.settings_icon = IconLeftWidget(
            icon="cog-outline", pos_hint={"center_x": 1, "center_y": 0.55}
        )
        self.settings_btn = OneLineAvatarIconListItem(
            text="Settings",
            on_press=lambda _: self.show_settings_screen(),
            on_release=lambda x: self.nav_drawer.set_state(new_state="toggle"),
            pos_hint={"center_x": 0.5, "center_y": 0.72},
        )
        self.darkmode_btn.add_widget(self.darkmode_icon)
        self.settings_btn.add_widget(self.settings_icon)
        self.fl.add_widget(self.darkmode_btn)
        self.fl.add_widget(self.settings_btn)
        self.ndbox.add_widget(self.fl)
        self.toolbar = MDTopAppBar(
            elevation=8,
            title=self.title,
            md_bg_color=self.theme_cls.primary_color,
        )
        self.toolbar.left_action_items = [["close", sys.exit]]
        self.ndbox.add_widget(self.toolbar)
        self.nav_drawer.add_widget(self.ndbox)
        self.nav_layout.add_widget(self.nl_sm)
        self.nav_layout.add_widget(self.nav_drawer)

        rscreen.add_widget(self.nav_layout)
        self.root_sm.add_widget(rscreen)

        return self.root_sm

    def show_settings_screen(self):
        self.screen_manager.current = "Settings"

    def on_stop(self):
        logging.info("Closing requested. Waiting for websocket to disconnect.")
        if _twitch_websocket:
            asyncio.ensure_future(_twitch_websocket.disconnect_websocket())

    def theme_change(self, instance):
        if self.theme_cls.theme_style == "Dark":
            self.theme_cls.theme_style = "Light"
        else:
            self.theme_cls.theme_style = "Dark"

    def create_chat_page(self):
        self.chat_page = ChatPage()
        screen = Screen(name="Chat")
        screen.add_widget(self.chat_page)
        self.screen_manager.add_widget(screen)

    def create_settings_page(self):
        self.settings_page = SettingsPage()
        screen = Screen(name="Settings")
        screen.add_widget(self.settings_page)
        self.screen_manager.add_widget(screen)

    def on_start(self):
        from kivy.base import EventLoop

        EventLoop.window.bind(on_keyboard=self.hook_keyboard)

    def hook_keyboard(self, window, key, *largs):
        if key == 27:
            if self.screen_manager.current != "Connect":
                self.screen_manager.current = "Connect"
            return True

    def show_error(self, message):
        self.info_page.update_info(message)
        self.screen_manager.current = "Info"
        Clock.schedule_once(sys.exit, 3)


if __name__ == "__main__":
    chat_app = GubChatApp()
    asyncio.run(chat_app.async_run())
