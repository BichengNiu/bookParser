# Copyright (c) Opendatalab. All rights reserved.
from typing import BinaryIO


def rewind_stream(file_stream: BinaryIO) -> bool:
    """将可复位的二进制流移动到起点；不可复位时返回 False。"""
    try:
        file_stream.seek(0)
    except (AttributeError, OSError, ValueError):
        return False
    return True
