from __future__ import annotations

import struct
import zlib
from collections.abc import Iterable


def build_legacy_gbk_zip(entries: Iterable[tuple[str, bytes]]) -> bytes:
    """Build a stored ZIP whose member names use legacy GBK metadata."""

    local_parts: list[bytes] = []
    central_parts: list[bytes] = []
    local_offset = 0
    count = 0
    for filename, payload in entries:
        encoded_name = filename.encode("gbk")
        checksum = zlib.crc32(payload) & 0xFFFFFFFF
        local_header = struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,
            20,
            0,
            0,
            0,
            0,
            checksum,
            len(payload),
            len(payload),
            len(encoded_name),
            0,
        )
        local_record = local_header + encoded_name + payload
        local_parts.append(local_record)

        central_header = struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,
            20,
            20,
            0,
            0,
            0,
            0,
            checksum,
            len(payload),
            len(payload),
            len(encoded_name),
            0,
            0,
            0,
            0,
            0,
            local_offset,
        )
        central_parts.append(central_header + encoded_name)
        local_offset += len(local_record)
        count += 1

    local_directory = b"".join(local_parts)
    central_directory = b"".join(central_parts)
    end_record = struct.pack(
        "<IHHHHIIH",
        0x06054B50,
        0,
        0,
        count,
        count,
        len(central_directory),
        len(local_directory),
        0,
    )
    return local_directory + central_directory + end_record
