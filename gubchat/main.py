import asyncio
import logging

from gubchat.gubchatapp import GubChatApp


def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(name)s | %(filename)s | %(levelname)s | %(funcName)s | %(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler()],  # Outputs logs to the console
    )

    websockets_logger = logging.getLogger("websockets")
    websockets_logger.setLevel(logging.INFO)

    app = GubChatApp()
    asyncio.run(app.async_run())


if __name__ == "__main__":
    main()
