import asyncio
import json
from abc import ABC
from io import TextIOBase
from pathlib import Path
from typing import Any

import keyring
from aiorwlock import RWLock
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
        return self.page.session.get(key)

    async def set(self, key, value):
        self.page.session.set(key, value)

    async def remove(self, key):
        self.page.session.remove(key)


class PersistentStorage(AsyncKeyValueStorage):
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

        self._lock = asyncio.Lock()

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

    async def get(self, key) -> Any:
        if key == "token":
            return keyring.get_password("hasherino", "token")

        async with self._lock:
            try:
                return self._data.get(key, None)
            except:
                return None

    async def set(self, key, value):
        if key == "token":
            keyring.set_password("hasherino", "token", value)
            return

        async with self._lock:
            self._data[key] = value
            self._file.truncate(0)
            self._file.seek(0)
            json.dump(self._data, self._file, sort_keys=True, indent=4)

    async def remove(self, key):
        async with self._lock:
            self._data.pop(key)
            self._file.truncate(0)
            self._file.seek(0)
            json.dump(self._data, self._file, sort_keys=True, indent=4)
