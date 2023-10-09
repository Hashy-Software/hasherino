from PySide6.QtCore import QSize
from PySide6.QtGui import QMovie, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QSizePolicy, QWidget


class TwitchChatMessage(QWidget):
    def __init__(self, author, message, emote_dict):
        super().__init__()

        layout = QHBoxLayout()

        words = message.split()
        for word in words:
            if word in emote_dict:
                label = QLabel()
                movie = QMovie(emote_dict[word])
                movie.setScaledSize(QSize(25, 25))
                label.setMovie(movie)
                movie.start()
            else:
                label = QLabel(word)

            layout.addWidget(label)

        layout.addStretch()
        self.setMinimumSize(QSize(0, 50))
        self.setLayout(layout)


if __name__ == "__main__":
    app = QApplication([])

    emote_dict = {
        ":emote:": "image.gif",
    }

    message = "Hello :emote: This is a test :emote: message!"

    window = TwitchChatMessage("Author", message, emote_dict)
    window.show()

    app.exec_()
