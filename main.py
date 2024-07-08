import logging
import os
import struct
import sys
import time
import urllib.request
from collections import deque
from subprocess import PIPE, Popen
from threading import Thread

import reedsolo
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logging.basicConfig(level=logging.DEBUG)

baudrate = 1000
mark_freq = 5000
confidence = 1.5
rs_codec = reedsolo.RSCodec(20)


def rx_minimodem():
    logging.info("listening")
    buffer = deque([], 9)

    rx = Popen(
        [
            "/usr/bin/minimodem",
            "--rx",
            str(baudrate),
            "--mark",
            str(mark_freq),
            "--confidence",
            str(confidence),
        ],
        stdout=PIPE,
    )

    while rx.stdout is not None:
        buffer.append(rx.stdout.read(1))

        if b"".join(buffer) == b"STARTDATA":
            final_buffer = []
            last_update = time.time()
            logging.info("Start of message received")
            while True:
                new_byte = rx.stdout.read(1)
                final_buffer.append(new_byte)
                buffer.append(new_byte)

                if time.time() - last_update > 10:
                    last_update = time.time()
                    if len(final_buffer) > 14:
                        _, datalen = struct.unpack("<HQ", b"".join(final_buffer[4:14]))
                        logging.info(f"{len(final_buffer)}/{datalen} bytes received")
                    else:
                        logging.info(f"{len(final_buffer)} bytes received")

                if b"".join(buffer) == b"STOP DATA":
                    logging.info("End of message received")
                    # end hit!
                    data, dataerrs, dataerrata = rs_codec.decode(
                        b"".join(final_buffer)[:-9]
                    )

                    if data[:4] == b"FILE":
                        filenamelen, datalen = struct.unpack("<HQ", data[4:14])
                        filename = bytes(data[14 : 14 + filenamelen]).decode("utf-8")

                        with open(filename, "w+b") as f:
                            f.write(data[14 + filenamelen :])
                            logging.info(f"Written `{filename}`")
                    elif data[:4] == b"HTTP":
                        (
                            filenamelen,
                            urllen,
                        ) = struct.unpack("<HQ", data[4:14])
                        filename = bytes(data[14 : 14 + filenamelen]).decode("utf-8")
                        url = bytes(
                            data[14 + filenamelen : 14 + filenamelen + urllen]
                        ).decode("utf-8")

                        req = urllib.request.urlopen(url)
                        with open(filename, "w+b") as f:
                            f.write(req.read())
                            logging.info(f"Written `{filename}`")

                    else:
                        logging.error(f"Unhandled action {data[:4]}")

                    rx.kill()
                    return


def tx_minimodem(filename: str, data: bytes):
    logging.info("Playing audio...")
    tx = Popen(
        [
            "/usr/bin/minimodem",
            "--tx",
            str(baudrate),
            "--mark",
            str(mark_freq),
        ],
        stdin=PIPE,
    )

    metadata = (
        b"FILE"
        + struct.pack("<HQ", len(filename), len(data))
        + filename.encode("utf-8")
    )
    tx.communicate(
        b"0000000000"
        + b"STARTDATA"
        + rs_codec.encode(metadata + data)
        + b"STOP DATA"
        + b"0000000000"
    )

    """
    filename = "google.html"
    url = "http://google.com"
    metadata = (
        b"HTTP"
        + struct.pack("<HQ", len(filename), len(url))
        + filename.encode("utf-8")
        + url.encode("utf-8")
    )
    tx.communicate(
        b"0000000000"
        + b"STARTDATA"
        + rs_codec.encode(metadata)
        + b"STOP DATA"
        + b"0000000000"
    )
    """


def record_cassette(file: str):
    with open(file, "rb") as f:
        data = f.read()

    filename = os.path.basename(file)

    t = Thread(target=tx_minimodem, args=(filename, data))
    t.start()
    t.join()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Data Cassette")

        layout = QVBoxLayout()

        self.file = ""
        self.file_label = QLabel("Choose a file...")
        layout.addWidget(self.file_label)

        row = QHBoxLayout()
        browse = QPushButton("Browse")
        browse.clicked.connect(self.browse_clicked)
        row.addWidget(browse)

        self.play = QPushButton("Play")
        self.play.clicked.connect(lambda: record_cassette(self.file))
        self.play.setDisabled(True)
        row.addWidget(self.play)
        layout.addLayout(row)

        listen = QPushButton("Listen")
        listen.clicked.connect(rx_minimodem)
        layout.addWidget(listen)

        widget = QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)

    def browse_clicked(self):
        picker = QFileDialog(self)
        if picker.exec():
            self.file = picker.selectedFiles()[0]
            self.file_label.setText(self.file)
            self.play.setEnabled(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    w = MainWindow()
    w.show()

    sys.exit(app.exec())
