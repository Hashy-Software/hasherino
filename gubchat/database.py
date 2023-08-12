import logging

import keyring
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

_engine = create_async_engine("sqlite+aiosqlite:///db.sqlite3")
_session_maker = async_sessionmaker(_engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    pass


class TwitchAccount(Base):
    __tablename__ = "user"

    twitch_id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str]
    # TODO: let only one account be active, multiple account support
    is_active: Mapped[bool]
    last_used_channel: Mapped[str]
    """
    Color doesn't need to be persisted, but this is a convenient way to keep
    its value consistent while the application is setting and getting it
    """
    chat_color: Mapped[str]

    @property
    def oauth_token(self):
        return keyring.get_password("gubchat", self.username)

    @oauth_token.setter
    def oauth_token(self, token):
        keyring.set_password("gubchat", self.username, token)

    def __str__(self):
        return str(self.__dict__)


async def create_db():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_twitch_account(id_or_username: str | int) -> TwitchAccount | None:
    async with _session_maker() as session:
        field = (
            TwitchAccount.twitch_id
            if type(id_or_username) == int
            else TwitchAccount.username
        )
        query = select(TwitchAccount).where(field == id_or_username).limit(1)

        try:
            return (await session.execute(query)).scalars().one()
        except NoResultFound:
            return None


async def get_active_twitch_account() -> TwitchAccount | None:
    async with _session_maker() as session:
        query = select(TwitchAccount).where(TwitchAccount.is_active).limit(1)

        try:
            return (await session.execute(query)).scalars().one()
        except NoResultFound:
            return None


async def add_twitch_accounts(*twitch_accounts) -> bool:
    """
    Returns True if the insertion was successful
    """
    async with _session_maker() as session:
        try:
            async with session.begin():
                session.add_all(twitch_accounts)
                accs = "\n".join(str(acc) for acc in twitch_accounts)
                logging.debug(f"Persisting twitch accounts: {accs}")
                return True
        except IntegrityError:
            return False
