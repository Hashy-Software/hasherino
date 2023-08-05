import asyncio
import logging
from threading import Thread
from attr import dataclass

import dearpygui.dearpygui as dpg
import websockets
from queue import Queue

from gubchat import user_auth


APP_ID = "hvmj7blkwy2gw3xf820n47i85g4sub"

gui_message_queue = Queue()

configs = dict()


@dataclass
class GUIQueueMessage:
    sender_info: dict  # Dictionary with sender UI item info
    data: str          # Data passed by the element on its user_data field, converted to a string

def gui_callback(sender_id: int, user_data):
    message = GUIQueueMessage(dpg.get_item_info(sender_id), str(dpg.get_item_user_data(sender_id)))
    logging.info(f"Added GUI callback to queue: {message.sender_info} {message.data}")
    gui_message_queue.put(message)


def show_new_message(message: str):
    if message:
        dpg.set_value("message_list", f"{dpg.get_value('message_list')}\n{message}")


def send_button_callback(sender_id: int, user_data):
    value = dpg.get_value("message")
    dpg.set_value("message", "")

    # Process chat commands
    split_value = value.split(" ")
    match split_value[0]:
        case "/auth":
            configs["token"] = asyncio.run(user_auth.request_oauth_token(APP_ID))
            logging.info(f"Set token to {configs['token']}")
            show_new_message("Token set!")
            return

        case "/set":
            configs[split_value[1]] = " ".join(split_value[2:])
            message = f"Set {split_value[1]} to {configs[split_value[1]]}"
            show_new_message(message)
            logging.info(message)
            return

        case _:
            pass

    dpg.set_item_user_data("send_button", value)
    show_new_message(f"{configs['user']}: {value}")
    gui_callback(sender_id, user_data)


def start_gui():
    initial_message = """
- Set your user with /set user YOUR_TWITCH_USER
- Get a twitch auth token with /auth
- Set the currently connected channel with /set channel CHANNEL
- You're set, chat normally now!"""
    dpg.create_context()
    dpg.create_viewport(title='GubChat', width=460, height=750)

    with dpg.window(tag="main_window", label="Gubchat"):
        dpg.add_input_text(tag="message_list", enabled=False, multiline=True, default_value=initial_message, height=700, width=445)

        with dpg.group(horizontal=True):
            dpg.add_input_text(tag="message", default_value="", width=400, )
            dpg.add_button(tag="send_button", label="Send", callback=send_button_callback)

    with dpg.handler_registry():
        dpg.add_key_release_handler(dpg.mvKey_Return, callback=send_button_callback)

    dpg.set_primary_window("main_window", True)

    dpg.setup_dearpygui()
    dpg.show_viewport()

    dpg.start_dearpygui()


def parse_recv(text: str) -> str:
    """
    Parses text returned by the websocket in the format:

    :user!user@user.tmi.twitch.tv PRIVMSG #channel :asd
    :user!user@user.tmi.twitch.tv JOIN
    """
    start, *text_without_domain = text.split(" ", maxsplit=2)
    irc_command = text_without_domain[0]
    match irc_command:
        case "JOIN":
            return f"Joined channel {text_without_domain[1]}"
        case "PRIVMSG":
            user = start[1:start.find("!")]
            channel, message = text_without_domain[1].split(" :", maxsplit=1)
            return f"{user}: {message}"
        case _:
            logging.warning(f"Ignoring unimplemented IRC command: {' '.join(text_without_domain)}")
            return ""


async def send_message(websocket):
    """
    Remove GUI message from queue and send message
    """
    while gui_message_queue.empty():
        await asyncio.sleep(0.3)

    message: GUIQueueMessage = gui_message_queue.get()
    logging.info(f"Found GUIQueueMessage, sending message: {message.data} to channel: {configs['channel']}")
    await websocket.send(f"PRIVMSG #{configs['channel']} :{message.data}")


async def get_message(websocket):
    """
    Listen for new websocket messages and add them to the websocket queue for the GUI to render
    """
    recv_task = asyncio.create_task(websocket.recv())
    while not recv_task.done():
        await asyncio.sleep(0.3)
    show_new_message(parse_recv(await recv_task))


async def run_ttv_chat_websocket():
    logging.info("Running websocket")
    twitch_websocket_url = "wss://irc-ws.chat.twitch.tv:443"

    # Wait for user to set a token
    token = channel = user = ""
    while not all((token, channel, user)):
        if not dpg.is_dearpygui_running():
            return

        token, channel, user = (configs.get(value, None) for value in ("token", "channel", "user"))
        await asyncio.sleep(1)

    async with websockets.connect(twitch_websocket_url) as websocket:
        logging.info("Authenticating with twitch...")
        await websocket.send(f"PASS oauth:{token}")
        await websocket.send(f"NICK {user}")
        logging.info(f"Authentication response: {await websocket.recv()}")

        await websocket.send(f"JOIN #{channel}")
        logging.info(f"Joining channel {channel}. Response: {await websocket.recv()}")

        send_task: asyncio.Task = asyncio.create_task(send_message(websocket))
        recv_task: asyncio.Task = asyncio.create_task(get_message(websocket))

        while dpg.is_dearpygui_running():
            if send_task.done():
                logging.debug("send task done")
                await send_task
                send_task = asyncio.create_task(send_message(websocket))

            if recv_task.done():
                logging.debug(f"recv task done: {await recv_task}")
                recv_task = asyncio.create_task(get_message(websocket))

            await asyncio.sleep(0.1)

        send_task.cancel()
        recv_task.cancel()


def start_async_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_ttv_chat_websocket())
    except asyncio.CancelledError:
        logging.warning("Closing with cancelled asyncio tasks")
    finally:
        loop.close()


def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s | %(name)s | %(filename)s | %(levelname)s | %(funcName)s | %(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler()  # Outputs logs to the console
        ]
    )

    websockets_logger = logging.getLogger("websockets")
    websockets_logger.setLevel(logging.INFO)

    # Start the async loop in a separate thread
    async_thread = Thread(target=start_async_loop)
    async_thread.start()

    start_gui()

    
if __name__ == "__main__":
    main()

