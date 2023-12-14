import logging
import ssl
from typing import Awaitable

import certifi
import websockets
from websockets.exceptions import ConnectionClosedError

from hasherino.parse_irc import ParsedMessage


class TwitchWebsocket:
    def __init__(self) -> None:
        self._websocket = None

    async def is_connected(self) -> bool:
        return self._websocket is not None

    async def _authenticate(self, token: str, user: str):
        """
        Returns parsed authentication response
        """
        if self._websocket is None:
            raise Exception("Websocket not connected")

        await self._websocket.send(f"PASS oauth:{token}")
        await self._websocket.send(f"NICK {user}")
        await self._websocket.send(f"USER {user} 8 * :{user}")

    async def join_channel(self, channel: str):
        if self._websocket is None:
            raise Exception("Websocket not connected")

        await self._websocket.send(f"JOIN #{channel}")

    async def leave_channel(self, channel: str):
        if self._websocket is None:
            raise Exception("Websocket not connected")

        await self._websocket.send(f"PART #{channel}")

    async def send_message(self, channel: str, message: str):
        logging.debug(f"Sending message on channel {channel} message: {message}")

        if self._websocket is None:
            raise Exception("Websocket not connected")

        logging.debug("Acquired lock, sending message")
        await self._websocket.send(f"PRIVMSG #{channel} :{message}")

    async def listen_message(
        self,
        message_callback: Awaitable,
        reconnect_callback: Awaitable[bool],
        token: str,
        username: str,
        join_channel: str | None = None,
    ):
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        async for websocket in websockets.connect(
            "wss://irc-ws.chat.twitch.tv:443",
            ping_interval=3,
            ping_timeout=2,
            ssl=ssl_context,
        ):
            try:
                self._websocket = websocket

                await websocket.send(
                    "CAP REQ :twitch.tv/commands twitch.tv/membership twitch.tv/tags"
                )
                await self._authenticate(token, username)
                await reconnect_callback(False)

                if join_channel:
                    await self.join_channel(join_channel)

                async for message in websocket:
                    try:
                        parsed_message: ParsedMessage = ParsedMessage(message)
                        await message_callback(parsed_message)
                    except Exception as e:
                        logging.exception(e)

            except ConnectionClosedError:
                logging.warning("Websocket connection closed, reconnecting")
                self._websocket = None
                await reconnect_callback(True)

            except Exception as e:
                logging.exception(f"Websocket connection failed: {e}")
