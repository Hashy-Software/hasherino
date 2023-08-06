import logging
from typing import Callable

import websockets
from kivy.clock import Clock

__all__ = ["TwitchWebsocket"]


def _parse_recv(text: str) -> tuple[str, ...]:
    """
    Parses text returned by the websocket in the format:

    :user!user@user.tmi.twitch.tv PRIVMSG #channel :asd
    :user!user@user.tmi.twitch.tv JOIN
    """
    start, *text_without_domain = text.split(" ", maxsplit=2)
    irc_command = text_without_domain[0]
    match irc_command:
        case "JOIN":
            return (f"Joined channel {text_without_domain[1]}",)
        case "PRIVMSG":
            user = start[1 : start.find("!")]
            channel, message = text_without_domain[1].split(" :", maxsplit=1)
            return user, message[:-2]  # Remove \r\n send by the server
        case _:
            logging.warning(
                f"Unimplemented IRC command: {' '.join(text_without_domain)}"
            )
            return ("",)


class TwitchWebsocket:
    def __init__(self) -> None:
        self._websocket = None

    async def connect_websocket(self):
        if self._websocket is None:
            self._websocket = await websockets.connect(
                "wss://irc-ws.chat.twitch.tv:443"
            )

    async def disconnect_websocket(self):
        if self._websocket:
            await self._websocket.close()
            self._websocket = None

    async def authenticate(self, token: str, user: str) -> str:
        if self._websocket is None:
            raise Exception("Websocket not connected")

        await self._websocket.send(f"PASS oauth:{token}")
        await self._websocket.send(f"NICK {user}")
        response = await self._websocket.recv()
        logging.info(f"Authentication response: {response}")
        return response

    async def join_channel(self, channel: str) -> str:
        if self._websocket is None:
            raise Exception("Websocket not connected")

        await self._websocket.send(f"JOIN #{channel}")

        response = await self._websocket.recv()
        logging.info(f"Tried joining channel {channel}. Response: {response}")
        return response

    async def send_message(self, channel: str, message: str):
        logging.debug(f"Sending message on channel {channel} message: {message}")

        if self._websocket is None:
            raise Exception("Websocket not connected")

        logging.debug("Acquired lock, sending message")
        await self._websocket.send(f"PRIVMSG #{channel} :{message}")

    async def listen_message(self, callback: Callable):
        if self._websocket is None:
            raise Exception("Websocket not connected")

        message = await self._websocket.recv()
        parsed_message = _parse_recv(message)
        logging.debug(
            f"Received websocket message: {message}. Parsed as: {parsed_message}"
        )

        if len(parsed_message) > 1:
            author, message = parsed_message
            Clock.schedule_once(lambda _, a=author, b=message: callback(a, b))
