from dataclasses import dataclass
from enum import Enum


@dataclass
class Badge:
    id: str
    name: str
    url: str


@dataclass
class User:
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
    source: EmoteSource

    def get_url(self) -> str:
        match self.source:
            case EmoteSource.SEVENTV:
                return f"https://cdn.7tv.app/emote/{self.id}/4x.webp"
            case EmoteSource.TWITCH:
                return f"https://static-cdn.jtvnw.net/emoticons/v2/emotesv2_{self.id}/default/dark/3.0"
            case _:
                raise TypeError


@dataclass
class Message:
    user: User
    elements: list[str | Emote]
    message_type: str
