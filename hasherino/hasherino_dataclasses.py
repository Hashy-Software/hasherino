from dataclasses import dataclass
from enum import Enum
from json import dumps


@dataclass
class Badge:
    id: str
    name: str
    url: str


@dataclass
class HasherinoUser:
    name: str
    badges: list[Badge] | None = None
    chat_color: str | None = None


class EmoteSource(Enum):
    TWITCH = 0
    SEVENTV = 1


@dataclass
class Emote:
    name: str
    id: str
    url: str


@dataclass
class Message:
    user: HasherinoUser
    elements: list[str | Emote]
    message_type: str
    me: bool
