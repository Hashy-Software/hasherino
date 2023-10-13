import asyncio
import json
import logging
from abc import ABC
from io import TextIOBase
from pathlib import Path
from typing import Any

import keyring
from flet import Page


class AsyncKeyValueStorage(ABC):
    async def get(self, key) -> Any:
        pass

    async def set(self, key, value):
        pass

    async def remove(self, key):
        pass


class MemoryOnlyStorage(AsyncKeyValueStorage):
    def __init__(self, page: Page) -> None:
        super().__init__()
        self.page = page

    async def get(self, key) -> Any:
        value = self.page.session.get(key)
        return value

    async def set(self, key, value):
        logging.debug(f"Memory storage set {key} to {value}")
        self.page.session.set(key, value)

    async def remove(self, key):
        logging.debug(f"Memory storage removed {key}")
        self.page.session.remove(key)


class PersistentStorage(AsyncKeyValueStorage):
    """
    Persistent async key-value storage.

    Locks implemented based on wikipedia's pseucode for a Readers–writer lock
    """

    def __init__(self, file: TextIOBase | str = "db.json") -> None:
        """
        File can be the path string to a database file or a TextIOBase if you don't want to use a file,
        such as using a StringIO object for a memory database
        """
        if type(file) == str:
            self._file = open(file, "r+" if Path(file).is_file() else "w+")
        elif isinstance(file, TextIOBase):
            self._file = file
        else:
            raise Exception("Invalid file type")

        self._r = asyncio.Lock()
        self._g = asyncio.Lock()
        self._b = 0

        try:
            self._data: dict = json.load(self._file)
        except json.JSONDecodeError:
            # File is not empty, database exists but failed to load
            if self._file.read():
                raise Exception("Failed to load database.")

            # File is empty so it's a new database, make an empty dict
            self._data: dict = {}

        assert type(self._data) == dict, "Database file is not a dictionary"

    def __del__(self):
        """
        Close file descriptor when object is garbage collected
        """
        self._file.close()

    async def _begin_read(self):
        await self._r.acquire()
        self._b += 1
        if self._b == 1:
            await self._g.acquire()
        self._r.release()

    async def _end_read(self):
        await self._r.acquire()
        self._b -= 1
        if self._b == 0:
            self._g.release()
        self._r.release()

    async def _begin_write(self):
        await self._g.acquire()

    async def _end_write(self):
        self._g.release()

    async def get(self, key) -> Any:
        if key == "token":
            return keyring.get_password("hasherino", "token")

        await self._begin_read()

        result = self._data.get(key, None)

        await self._end_read()

        return result

    async def set(self, key, value):
        if key == "token":
            keyring.set_password("hasherino", "token", value)
            # DO NOT log passwords
            return

        await self._begin_write()

        logging.debug(f"Persistent storage set {key} to {value}")
        self._data[key] = value
        self._file.truncate(0)
        self._file.seek(0)
        json.dump(self._data, self._file, sort_keys=True, indent=4)

        await self._end_write()

    async def remove(self, key):
        await self._begin_write()

        logging.debug(f"Persistent storage removed {key}")
        self._data.pop(key)
        self._file.truncate(0)
        self._file.seek(0)
        json.dump(self._data, self._file, sort_keys=True, indent=4)

        await self._end_write()
