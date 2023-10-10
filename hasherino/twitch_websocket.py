import logging
import ssl
from collections import defaultdict
from typing import Callable

import certifi
import websockets

__all__ = ["TwitchWebsocket", "ParsedMessage"]


class ParsedMessage:
    def __init__(self, message: str):
        raw_components = self._get_raw_components(message)
        if not raw_components:
            return None

        self.command = self._parse_command(raw_components["raw_command"])
        self.source = self.tags = self.parameters = None

        if self.command is None:
            return None
        else:
            if raw_components["raw_tags"] is not None:
                self.tags = self._parse_tags(raw_components["raw_tags"])

            self.source = self._parse_source(raw_components["raw_source"])
            self.parameters = raw_components["raw_parameters"]

    def __str__(self) -> str:
        return str(self.__dict__)

    def _get_raw_components(self, message: str) -> dict[str, str]:
        if not message:
            return None

        raw_tags = raw_source = raw_command = raw_parameters = ""

        # Start index
        idx = 0

        # Get tags
        if message[idx] == "@":
            end_idx = message.find(" ")
            raw_tags = message[1:end_idx]
            idx = end_idx + 1

        # Get source(nick and host)
        if message[idx] == ":":
            idx += 1
            end_idx = message.find(" ", idx)
            raw_source = message[idx:end_idx]
            idx = end_idx + 1

        # Command
        end_idx = message.find(":", idx)
        if -1 == end_idx:
            end_idx = len(message)

        raw_command = message[idx:end_idx].strip()

        # Parameters
        if end_idx != len(message):
            idx = end_idx + 1
            raw_parameters = message[idx:]

        return {
            "raw_tags": raw_tags,
            "raw_source": raw_source,
            "raw_command": raw_command,
            "raw_parameters": raw_parameters,
        }

    def _parse_command(self, raw_command: str) -> dict:
        parsed_command = None
        command_parts = raw_command.split(" ")

        match command_parts[0]:
            case "JOIN" | "PART" | "NOTICE" | "CLEARCHAT" | "HOSTTARGET":
                pass
            case "PRIVMSG":
                parsed_command = {
                    "command": command_parts[0],
                    "channel": command_parts[1],
                }
            case "PING":
                parsed_command = {"command": command_parts[0]}
            case "CAP":
                """
                The parameters part of the messages contains the
                enabled capabilities.
                """
                parsed_command = {
                    "command": command_parts[0],
                    "isCapRequestEnabled": command_parts[2] == "ACK",
                }
            case "GLOBALUSERSTATE":
                """
                Included only if you request the /commands capability.
                But it has no meaning without also including the /tags capability.
                """
                parsed_command = {"command": command_parts[0]}
            case "USERSTATE":
                """
                Included only if you request the /commands capability.
                But it has no meaning without also including the /tags capability.
                """
                parsed_command = {"command": command_parts[0]}
            case "ROOMSTATE":
                """
                Included only if you request the /commands capability.
                But it has no meaning without also including the /tags capability.
                """
                parsed_command = {
                    "command": command_parts[0],
                    "channel": command_parts[1],
                }
            case "RECONNECT":
                logging.info(
                    "The Twitch IRC server is about to terminate the connection for maintenance."
                )
                parsed_command = {"command": command_parts[0]}
            case "421":
                logging.warning(f"Unsupported IRC command: {command_parts[2]}")
                return None
            case "001":
                # Logged in (successfully authenticated)
                parsed_command = {
                    "command": command_parts[0],
                    "channel": command_parts[1],
                }
            case "002" | "003" | "004" | "353" | "366" | "372" | "375":
                """
                Ignoring all other numeric messages.
                353 tells you who else is in the chat room you're joining.
                """
                pass
            case "376":
                logging.info(f"Numeric message: {command_parts[0]}")
                return None
            case _:
                logging.warning(f"Unexpected command: {command_parts[0]}")
                return None

        return parsed_command

    def _parse_source(self, raw_source: str) -> None | dict[str, str]:
        if not raw_source:
            return None
        else:
            source_parts = raw_source.split("!")
            return {
                "nick": source_parts[0] if len(source_parts) == 2 else None,
                "host": source_parts[1] if len(source_parts) == 2 else source_parts[0],
            }

    def _parse_tags(self, raw_tags: str):
        dict_parsed_tags = {}

        if not raw_tags:
            return dict_parsed_tags

        for tag in raw_tags.split(";"):
            tag_key, tag_value = tag.split("=")

            match tag_key:
                case "badges-info":
                    """
                    Contains metadata related to the chat badges in the badges tag.
                    Currently, this tag contains metadata only for subscriber badges, to indicate the number of months the user has been a subscriber.
                    """
                    pass
                case "badges":
                    # badges=staff/1,broadcaster/1,turbo/1;
                    if tag_value:
                        badges = dict()
                        for badge_and_version in tag_value.split(","):
                            badge, version = badge_and_version.split("/")
                            badges[badge] = version
                    else:
                        badges = None

                    dict_parsed_tags[tag_key] = badges

                case "emotes":
                    """
                    emotes=25:0-4,12-16/1902:6-10
                    emotes=emotesv2_c51307f86f6241bc8cd8385efd7c7509:0-9/emotesv2_d9f1e820ca8e42bab70fc2f22dea0d5a:31-44

                    Comma-delimited list of emotes and their positions in the message.
                    Each emote is in the form, <emote ID>:<start position>-<end position>
                    """
                    if tag_value:
                        id_to_positions = defaultdict(list)

                        for emote_id_and_pos in tag_value.split("/"):
                            emote_id, positions = emote_id_and_pos.split(":")

                            for start_end in positions.split(","):
                                start, end = start_end.split("-")

                                id_to_positions[emote_id].append((start, end))

                        dict_parsed_tags[tag_key] = dict(id_to_positions)
                    else:
                        dict_parsed_tags[tag_key] = None

                case "color":
                    dict_parsed_tags["color"] = tag_value[1:]

                case "user-id":
                    dict_parsed_tags["user-id"] = tag_value

                case "display-name":
                    dict_parsed_tags["display-name"] = tag_value

                case _:
                    pass

        return dict_parsed_tags


class TwitchWebsocket:
    def __init__(self) -> None:
        self._websocket = None

    async def connect_websocket(self):
        if self._websocket is None:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            # TODO: remove ping_timeout=None and properly detect timeout, and show on the UI when it disconnects/reconnects
            self._websocket = await websockets.connect(
                "wss://irc-ws.chat.twitch.tv:443",
                ping_timeout=None,
                ping_interval=None,
                ssl=ssl_context,
            )
            await self._websocket.send(
                "CAP REQ :twitch.tv/commands twitch.tv/membership twitch.tv/tags"
            )

    async def disconnect_websocket(self):
        if self._websocket:
            await self._websocket.close()
            self._websocket = None

    async def authenticate(self, token: str, user: str):
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

    async def send_message(self, channel: str, message: str):
        logging.debug(f"Sending message on channel {channel} message: {message}")

        if self._websocket is None:
            raise Exception("Websocket not connected")

        logging.debug("Acquired lock, sending message")
        await self._websocket.send(f"PRIVMSG #{channel} :{message}")

    async def listen_message(self, callback: Callable):
        if self._websocket is None:
            raise Exception("Websocket not connected")

        raw_msg = await self._websocket.recv()

        # Multiple messages can be received at once
        for message in raw_msg.split("\r\n"):
            parsed_message = ParsedMessage(message)
            if parsed_message:
                logging.debug(
                    f"Received websocket message: {message}. Parsed as: {parsed_message}"
                )

                try:
                    if parsed_message.command.get("command", None) in (
                        "PRIVMSG",
                        "USERSTATE",  # USERSTATE messages are used to get color and user-id
                        "GLOBALUSERSTATE",
                    ):
                        await callback(parsed_message)
                except AttributeError:
                    pass
