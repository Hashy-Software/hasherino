import logging
import ssl
from enum import StrEnum

import certifi
from aiohttp import ClientSession, TCPConnector

from hasherino.parse_irc import ParsedMessage


class HistorySource(StrEnum):
    ROBOTTY = "https://recent-messages.robotty.de/api/v2/recent-messages/{channel}"


async def get_chat_history(
    channel: str,
    source: HistorySource = HistorySource.ROBOTTY,
) -> list[ParsedMessage]:
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    conn = TCPConnector(ssl=ssl_context)

    async with ClientSession(connector=conn) as session:
        async with session.get(
            source.value.format(channel=channel),
        ) as response:
            json_result = await response.json()
            logging.debug(f"Get chat history for {channel} response: {json_result}")

            if not response.ok:
                message = f"Unable to get chat history for {channel} with response {json_result}"
                logging.debug(message)
                raise Exception(message)

            res = []

            for message in json_result["messages"]:
                pm = ParsedMessage(message)
                res.append(pm)

            return res


async def main():
    for pm in await get_chat_history("hash_table"):
        print(pm.get_message_text())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
