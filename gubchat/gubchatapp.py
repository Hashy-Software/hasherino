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

from gubchat.twitch_websocket import TwitchWebsocket
from gubchat.user_auth import request_oauth_token

Window.softinput_mode = "pan"


_settings = {
    "token": "",
    "user": "",
    "channel": "",
}

_twitch_websocket = None


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

    def update_chat_history(self, message):
        self.chat_history.text += "\n" + message

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
            size_hint_x=None, multiline=False, pos_hint={"center_x": 0, "center_y": 1}
        )
        bottom_line = GridLayout(cols=1)
        bottom_line.add_widget(self.new_msg)
        self.add_widget(bottom_line)

        Window.bind(on_key_down=self.on_key_down)

        Clock.schedule_once(self.focus_text_input, 0.4)

        Clock.schedule_once(lambda _: asyncio.ensure_future(self.listen_for_messages()))

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

    def on_key_down(self, instance, keyboard, keycode, text, modifiers):
        if keycode == 40:
            self.send_local_message(None)
            Clock.schedule_once(self.focus_text_input, 0.1)

    def focus_text_input(self, _):
        self.new_msg.focus = True

    def send_local_message(self, _):
        msg = self.new_msg.text
        self.new_msg.text = ""
        username = "hash_table"
        if msg:
            Clock.schedule_once(
                lambda _: asyncio.ensure_future(
                    _twitch_websocket.send_message("hash_table", msg)
                )
            )
            self.history.update_chat_history(
                f"[color=dd2020]{username}[/color] [color=20dddd]:[/color] {msg}"
            )

    def incoming_message(self, username, message):
        if message and username:
            self.history.update_chat_history(
                f"[color=20dd20]{username}[/color] [color=20dddd]:[/color] {message}"
            )

    async def listen_for_messages(self):
        logging.debug("Listening for messages")
        while True:
            task = asyncio.create_task(
                _twitch_websocket.listen_message(self.incoming_message)
            )
            while not task.done():
                await asyncio.sleep(0.3)


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
        self.user = MDTextField(text="", multiline=False, pos_hint={"x": 0, "y": 0.2})
        self.float.add_widget(self.user)
        self.add_widget(self.float)

        self.add_widget(
            MDLabel(text="Channel: ", halign="center", theme_text_color="Primary")
        )
        self.float = FloatLayout()
        self.channel = MDTextField(
            text="", multiline=False, pos_hint={"x": 0, "y": 0.2}
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

    def connect_button(self, _):
        logging.debug("Clicked connect button")

        global _settings

        _settings["user"] = self.user.text
        _settings["channel"] = self.channel.text

        Clock.schedule_once(lambda _: asyncio.ensure_future(self.twitch_connect()))

    async def twitch_connect(self):
        global _twitch_websocket
        global _settings

        await request_oauth_token(
            "hvmj7blkwy2gw3xf820n47i85g4sub",  # twitch app_id
            lambda token, s=_settings: _settings.__setitem__("token", token),
        )

        logging.debug("Waiting for token, channel and user")

        while not all((_settings["token"], _settings["user"], _settings["channel"])):
            await asyncio.sleep(0.2)

        logging.debug("Found token, channel and user. Connecting to twitch.")

        token, user, channel = (_settings[key] for key in ("token", "user", "channel"))

        _twitch_websocket = TwitchWebsocket()
        await _twitch_websocket.connect_websocket()
        await _twitch_websocket.authenticate(token, user)
        await _twitch_websocket.join_channel(channel)

        Clock.schedule_once(
            lambda _, chat_app=App.get_running_app(): chat_app.create_chat_page()
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

        self.create_settings_page()

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
        self.iconitem = IconLeftWidget(
            icon="settings", pos_hint={"center_x": 1, "center_y": 0.55}
        )
        self.sub_nav.add_widget(self.iconitem)
        self.fl.add_widget(self.sub_nav)
        self.settings_btn = OneLineAvatarIconListItem(
            text="Dark Mode",
            on_press=self.theme_change,
            on_release=lambda x: self.nav_drawer.set_state(new_state="toggle"),
            pos_hint={"center_x": 0.5, "center_y": 0.86},
        )
        self.iconitem = IconLeftWidget(
            icon="theme-light-dark", pos_hint={"center_x": 1, "center_y": 0.55}
        )
        self.settings_btn.add_widget(self.iconitem)
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
        self.screen_manager.current = "Chat"

    def create_settings_page(self):
        self.settings_page = SettingsPage()
        screen = Screen(name="Settings")
        screen.add_widget(self.settings_page)
        self.screen_manager.add_widget(screen)
        self.screen_manager.current = "Settings"

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
