import logging
import ssl
from collections import defaultdict
from enum import Enum, auto
from typing import Awaitable

import certifi
import websockets
from websockets.exceptions import ConnectionClosedError

from hasherino.hasherino_dataclasses import Badge, Emote

__all__ = ["TwitchWebsocket", "ParsedMessage"]


class Command(Enum):
    PRIVMSG = auto()
    USERSTATE = auto()
    GLOBALUSERSTATE = auto()
    OTHER = auto()


class ParsedMessage:
    def __init__(self, message: str):
        self.source = self.tags = self.parameters = self.command = None

        raw_components = self._get_raw_components(message)
        if not raw_components:
            return None

        self.command = self._parse_command(raw_components["raw_command"])

        if self.command is None:
            return None
        else:
            if raw_components["raw_tags"] is not None:
                self.tags = self._parse_tags(raw_components["raw_tags"])

            self.source = self._parse_source(raw_components["raw_source"])
            self.parameters = raw_components["raw_parameters"]

    def get_badges(self, ttv_badges: dict) -> list[Badge]:
        def get_badge(set_id: str, version: str) -> dict | None:
            try:
                id_match = next((s for s in ttv_badges if s["set_id"] == set_id))
                version_match = next(
                    (s for s in id_match["versions"] if s["id"] == version)
                )
                return version_match
            except:
                return None

        badges = []

        if not self.tags or not self.tags.get("badges"):
            return badges

        try:
            for id, version in self.tags["badges"].items():
                badge = get_badge(id, version)
                if badge:
                    badges.append(Badge(id, badge["title"], badge["image_url_4x"]))
        except Exception as e:
            logging.exception(f"Error {e}. Failed to get badges from message: {self}")
            return []

        return badges

    def get_author_chat_color(self) -> str:
        result = "ffffff"

        if self.tags and self.tags["color"]:
            result = (
                self.tags["color"][1:]
                if self.tags["color"][0] == "#"
                else self.tags["color"]
            )

        assert len(result) <= 7, f"Returned invalid color: {result}"
        assert result[0] != "#"

        return f"#{result}"

    def get_author_displayname(self) -> str:
        if not self.tags or not self.tags.get("display-name"):
            logging.warning(f"Failed to get author display-name fo message: {self}")
            return ""

        return self.tags.get("display-name")

    def get_command(self) -> Command:
        result = Command.OTHER

        if not self.command or not self.command.get("command"):
            return result

        match self.command["command"]:
            case "PRIVMSG":
                result = Command.PRIVMSG
            case "USERSTATE":
                result = Command.USERSTATE
            case "GLOBALUSERSTATE":
                result = Command.GLOBALUSERSTATE
            case _:
                result = Command.OTHER

        return result

    def is_me(self) -> bool:
        """
        Messages sent with /me, coloring the whole line with the user's chat color
        """
        return (
            self.get_command() is Command.PRIVMSG
            and self.parameters[:7] == "\x01ACTION"
        )

    def get_message_text(self) -> str:
        # Remove \r\n from end of text
        result = "" if len(self.parameters) <= 2 else self.parameters[:-2]

        if self.is_me():
            # parameters: '\x01ACTION asd\x01\r\n'
            result = result[8:-1]

        return result

    def get_emote_sets(self) -> list[str]:
        result = []

        if self.tags and self.tags.get("emote-sets"):
            result = [tag for tag in self.tags["emote-sets"].split(",")]

        return result

    def get_emote_map(self) -> dict[str, Emote]:
        """
        Returns map of emote name to emote object for twitch emotes included in the message tags
        """
        if not self.tags:
            return {}

        emote_name_to_id_and_url: dict[str, Emote] = {}

        if self.tags.get("emotes"):
            for emote_id, list_of_index_tuples in self.tags["emotes"].items():
                first_starting_index, first_ending_index = map(
                    int, list_of_index_tuples[0]
                )
                emote_name = self.get_message_text()[
                    first_starting_index : first_ending_index + 1
                ]
                emote_name_to_id_and_url[emote_name] = Emote(
                    emote_name,
                    emote_id,
                    f"https://static-cdn.jtvnw.net/emoticons/v2/{emote_id}/default/dark/2.0",
                )

        return emote_name_to_id_and_url

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

                case "emote-sets":
                    dict_parsed_tags["emote-sets"] = tag_value

                case _:
                    pass

        return dict_parsed_tags


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
