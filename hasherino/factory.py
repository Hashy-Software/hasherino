from hasherino.hasherino_dataclasses import Emote, HasherinoUser, Message
from hasherino.twitch_websocket import ParsedMessage


def message_factory(
    user: HasherinoUser,
    message: str | ParsedMessage,
    emote_map: dict[str, Emote],
) -> Message:
    """
    Makes Message instances.

    When the message parameter is a string, the Message object is being built from a message the user is sending.
    When it's a ParsedMessage, it's being built from a received message, so we need to get twitch emote information from the ParsedMessage.
    """
    if isinstance(message, str):
        elements: list[str | Emote] = [
            emote_map.get(word, word) for word in message.split(" ")
        ]
        return Message(
            user=user,
            elements=elements,
            message_type="chat_message",
            me=False,
        )
    elif isinstance(message, ParsedMessage):
        emote_map = emote_map.copy()
        emote_map.update(message.get_emote_map())
        elements: list[str | Emote] = [
            emote_map.get(word, word) for word in message.get_message_text().split(" ")
        ]
        return Message(
            user=user,
            elements=elements,
            message_type="chat_message",
            me=message.is_me(),
        )
    else:
        raise TypeError("The message parameter can only be an str or ParsedMessage.")
