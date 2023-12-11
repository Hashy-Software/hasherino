import asyncio
import enum
import itertools
import logging
import ssl
from dataclasses import dataclass
from typing import Iterable

import certifi
from aiohttp import ClientSession, TCPConnector

__all__ = ["get_users", "update_chat_color", "TwitchUser", "NormalUserColor"]

_BASE_URL = "https://api.twitch.tv/helix/"


@dataclass
class TwitchUser:
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
) -> list[TwitchUser]:
    """
    Raises Exception for invalid status code or KeyError if the json response is invalid
    """
    users = "&".join(
        f"id={user}" if type(user) == int else f"login={user}" for user in users
    )
    logging.debug(f"Generated helix get user parameters: {users}")

    ssl_context = ssl.create_default_context(cafile=certifi.where())
    conn = TCPConnector(ssl=ssl_context)

    async with ClientSession(connector=conn) as session:
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

            return [TwitchUser(user) for user in json_result["data"]]


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

    ssl_context = ssl.create_default_context(cafile=certifi.where())
    conn = TCPConnector(ssl=ssl_context)

    async with ClientSession(connector=conn) as session:
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
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    conn = TCPConnector(ssl=ssl_context)

    async with ClientSession(connector=conn) as session:
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
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    conn = TCPConnector(ssl=ssl_context)

    async with ClientSession(connector=conn) as session:
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


async def get_channel_emotes(app_id: str, oauth_token: str, broadcaster_id: str):
    """
    Raises Exception for invalid status code
    """
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    conn = TCPConnector(ssl=ssl_context)

    async with ClientSession(connector=conn) as session:
        async with session.get(
            f"{_BASE_URL}chat/emotes",
            headers={
                "Authorization": f"Bearer {oauth_token}",
                "Client-Id": app_id,
            },
            params=f"broadcaster_id={broadcaster_id}",
        ) as response:
            json_result = await response.json()
            logging.debug(f"Helix get channel emotes response: {json_result}")

            if not response.ok:
                raise Exception(
                    f"Unable to get channel emotes for {broadcaster_id} with response {json_result}"
                )

            return json_result["data"]


async def get_emote_sets(
    app_id: str, oauth_token: str, emote_set_ids: set[str]
) -> list[dict]:
    """
    Returns a list of dicts where each key-value pair is the information for an emote.

    Raises Exception for invalid status code or passing more than 25 set ids
    """
    if not emote_set_ids:
        return []

    if len(emote_set_ids) > 25:
        raise Exception("You may specify a maximum of 25 IDs.")

    ssl_context = ssl.create_default_context(cafile=certifi.where())
    conn = TCPConnector(ssl=ssl_context)

    ids = "&".join(f"emote_set_id={user_id}" for user_id in emote_set_ids)
    logging.debug(f"Generated params for emote sets query: {ids}")

    async with ClientSession(connector=conn) as session:
        async with session.get(
            f"{_BASE_URL}chat/emotes/set",
            headers={
                "Authorization": f"Bearer {oauth_token}",
                "Client-Id": app_id,
            },
            params=ids,
        ) as response:
            json_result = await response.json()
            logging.debug(f"Helix get channel emotes response: {json_result}")

            if not response.ok:
                raise Exception(
                    f"Unable to get emote sets {','.join(emote_set_ids)} with response {json_result}"
                )

            return json_result["data"]


async def get_all_emote_sets(
    app_id: str, oauth_token: str, emote_set_ids: set[str]
) -> list[dict]:
    """
    Instead of thowing an exception when the number of emote_set_ids exceeds 25
    like get_emote_sets, this function tries to get all the emote sets by turning
    the ids into batches of 25 and requesting for each batch concurrently.

    Returns a list of dicts where each key-value pair is the information for an emote.
    """

    def batched(iterable, n):
        """
        batched('ABCDEFG', 3) --> ABC DEF G

        Taken from python 3.12 itertools(not officially in 3.11)
        """
        if n < 1:
            raise ValueError("n must be at least one")
        it = iter(iterable)
        while batch := tuple(itertools.islice(it, n)):
            yield batch

    emote_tasks = []
    emote_sets = []

    try:
        async with asyncio.timeout(5):
            for batch in batched(emote_set_ids, 25):
                task = asyncio.create_task(
                    get_emote_sets(app_id, oauth_token, set(batch))
                )
                emote_tasks.append(task)

            for task in asyncio.as_completed(emote_tasks):
                emote_sets += await task
    except Exception as e:
        logging.warning(
            f"Returning incomplete set of emotes {emote_sets} because of exception {e}"
        )

    return emote_sets
