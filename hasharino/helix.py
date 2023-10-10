import enum
import logging
from dataclasses import dataclass
from typing import Iterable

from aiohttp import ClientSession

__all__ = ["get_users", "update_chat_color", "User", "NormalUserColor"]

_BASE_URL = "https://api.twitch.tv/helix/"


@dataclass
class User:
    id: str
    login: str
    display_name: str
    type: str  # admin, global_mod, staff, or "" for normal user
    broadcaster_type: str  # affiliate, partner or "" for normal broadcaster
    description: str
    profile_image_url: str
    offline_image_url: str
    created_at: str

    def __init__(self, json_content: dict):
        self.__dict__ = json_content


@dataclass
class UserChatColor:
    user_id: str
    user_login: str
    user_name: str
    color: str

    def __init__(self, json_content: dict):
        self.__dict__ = json_content


class NormalUserColor(enum.StrEnum):
    blue = "#0000ff"
    blue_violet = "#8a2be2"
    cadet_blue = "#5f9ea0"
    chocolate = "#d2691e"
    coral = "#ff7f50"
    dodger_blue = "#1e90ff"
    firebrick = "#b22222"
    golden_rod = "#daa520"
    green = "#008000"
    hot_pink = "#ff69b4"
    orange_red = "#ff4500"
    red = "#ff0000"
    sea_green = "#2e8b57"
    spring_green = "#00ff7f"
    yellow_green = "#9acd32"


async def get_users(
    app_id: str,
    oauth_token: str,
    users: Iterable[str | int],
) -> list[User]:
    """
    Raises Exception for invalid status code or KeyError if the json response is invalid
    """
    users = "&".join(
        f"id={user}" if type(user) == int else f"login={user}" for user in users
    )
    logging.debug(f"Generated helix get user parameters: {users}")

    async with ClientSession() as session:
        async with session.get(
            f"{_BASE_URL}users",
            headers={
                "Authorization": f"Bearer {oauth_token}",
                "Client-Id": app_id,
            },
            params=users,
        ) as response:
            json_result = await response.json()
            logging.debug(f"Helix get user response: {json_result}")

            if response.status != 200:
                raise Exception("Unable to get user")

            return [User(user) for user in json_result["data"]]


async def get_user_chat_color(
    app_id: str,
    oauth_token: str,
    user_ids: Iterable[int],
) -> list[UserChatColor]:
    """
    Raises Exception for invalid status code or KeyError if the json response is invalid
    """
    ids = "&".join(f"user_id={user_id}" for user_id in user_ids)
    logging.debug(f"Generated helix get user id parameters: {ids}")

    async with ClientSession() as session:
        async with session.get(
            f"{_BASE_URL}chat/color",
            headers={
                "Authorization": f"Bearer {oauth_token}",
                "Client-Id": app_id,
            },
            params=ids,
        ) as response:
            json_result = await response.json()
            logging.debug(f"Helix get user response: {json_result}")

            if response.status != 200:
                raise Exception("Unable to get user chat color")

            return [UserChatColor(user) for user in json_result["data"]]


async def update_chat_color(
    app_id: str, oauth_token: str, user_id: str, color_code: str | NormalUserColor
) -> bool:
    async with ClientSession() as session:
        params = {
            "user_id": user_id,
            "color": str(color_code),
        }
        async with session.put(
            f"{_BASE_URL}chat/color",
            headers={
                "Authorization": f"Bearer {oauth_token}",
                "Client-Id": app_id,
            },
            params=params,
        ) as response:
            logging.debug(
                f"Helix tried changing user color, response code: {response.status}. Params: {params}"
            )
            return response.status == 204


async def get_global_badges(
    app_id: str,
    oauth_token: str,
) -> dict:
    """
    Raises Exception for invalid status code
    """
    async with ClientSession() as session:
        async with session.get(
            f"{_BASE_URL}chat/badges/global",
            headers={
                "Authorization": f"Bearer {oauth_token}",
                "Client-Id": app_id,
            },
        ) as response:
            json_result = await response.json()
            logging.debug(f"Helix get global badge response: {json_result}")

            if response.status != 200:
                raise Exception("Unable to get global badges")

            return json_result["data"]
