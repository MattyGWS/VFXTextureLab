from __future__ import annotations

import base64

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

THUMBNAIL_SIZE = 256
MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024


def decode_thumbnail_image(encoded: str | None) -> QImage:
    text = str(encoded or "").strip()
    if not text:
        return QImage()
    try:
        payload = base64.b64decode(text, validate=True)
    except Exception:
        return QImage()
    if not payload or len(payload) > MAX_THUMBNAIL_BYTES:
        return QImage()
    image = QImage()
    if not image.loadFromData(payload, "PNG"):
        return QImage()
    return image


def thumbnail_pixmap(encoded: str | None, size: int = THUMBNAIL_SIZE) -> QPixmap:
    image = decode_thumbnail_image(encoded)
    if image.isNull():
        return QPixmap()
    return QPixmap.fromImage(
        image.scaled(
            int(size), int(size),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    )


def encode_thumbnail_image(image: QImage, *, size: int = THUMBNAIL_SIZE) -> str:
    if image is None or image.isNull():
        raise ValueError("No image is available to use as a graph thumbnail.")

    source = image.convertToFormat(QImage.Format.Format_RGBA8888)
    scaled = source.scaled(
        int(size), int(size),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QImage(int(size), int(size), QImage.Format.Format_RGBA8888)
    canvas.fill(QColor(45, 41, 56, 255))
    painter = QPainter(canvas)
    try:
        left = (canvas.width() - scaled.width()) // 2
        top = (canvas.height() - scaled.height()) // 2
        painter.drawImage(left, top, scaled)
    finally:
        painter.end()

    payload = QByteArray()
    buffer = QBuffer(payload)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise ValueError("Could not prepare the graph thumbnail.")
    try:
        if not canvas.save(buffer, "PNG"):
            raise ValueError("Could not encode the graph thumbnail as PNG.")
    finally:
        buffer.close()
    raw = bytes(payload)
    if len(raw) > MAX_THUMBNAIL_BYTES:
        raise ValueError("The graph thumbnail is unexpectedly large.")
    return base64.b64encode(raw).decode("ascii")
