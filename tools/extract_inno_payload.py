#!/usr/bin/env python3
"""Offline, stdlib-only extraction of the exact Lenovo 74ti05afkkxbyyb0.exe.

This is an artifact-specific extractor, not a general Inno Setup parser.
Never executes the installer or any extracted file. Every output must match
the SHA-1 carried by the installer's CRC-checked data-location table.

Format and x86 instruction decoding adapted from innoextract by Daniel Scharrer:
https://github.com/dscharrer/innoextract/tree/master/src/stream
Altered source: this Python implementation is not the original innoextract.

Copyright (C) 2011-2019 Daniel Scharrer
This software is provided 'as-is', without any express or implied warranty.
In no event will the authors be held liable for any damages arising from the
use of this software.
Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it
freely, subject to the following restrictions:
1. The origin of this software must not be misrepresented; you must not claim
   that you wrote the original software. If you use this software in a product,
   an acknowledgment in the product documentation would be appreciated but is
   not required.
2. Altered source versions must be plainly marked as such, and must not be
   misrepresented as being the original software.
3. This notice may not be removed or altered from any source distribution.
"""
import argparse
import hashlib
import json
import lzma
from pathlib import Path
import re
import struct
import zlib

SOURCE_SHA256 = 'c94d7c866b0fc0be4d62511b780294900eef972f6e8ec9db761b74cfdf1af4ea'
HEADER_OFFSET = 5874018
DATA_OFFSET = 121344
PREFIX = '{code:GetExtractPath|}\\'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read_header_block(data, offset):
    crc, size, compressed = struct.unpack_from('<IIB', data, offset)
    require(zlib.crc32(data[offset + 4:offset + 9]) == crc, 'Header CRC32 mismatch')
    require(compressed == 1, 'Unexpected header compression')
    stored = data[offset + 9:offset + 9 + size]
    require(len(stored) == size, 'Truncated block')
    raw = bytearray()
    chunks = 0
    for pos in range(0, len(stored), 4100):
        block = stored[pos:pos + 4100]
        require(len(block) >= 5, 'Truncated CRC block')
        require(zlib.crc32(block[4:]) == struct.unpack_from('<I', block)[0],
                'Block CRC32 mismatch')
        raw.extend(block[4:])
        chunks += 1
    prop = raw[0]
    filters = [{'id': lzma.FILTER_LZMA1,
                'dict_size': struct.unpack_from('<I', raw, 1)[0],
                'lc': prop % 9, 'lp': prop // 9 % 5, 'pb': prop // 45}]
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
    result = dec.decompress(raw[5:])
    require(dec.eof and not dec.unused_data, 'Incomplete metadata LZMA stream')
    return result, offset + 9 + size, {'offset': offset, 'stored_size': size,
            'decoded_size': len(result), 'crc32_chunks_verified': chunks}


def decode_instructions(payload):
    """Undo Inno 5.3.9+ optimization, with per-file 64 KiB boundaries."""
    result = bytearray(payload)
    pos = 0
    while pos < len(result):
        opcode = result[pos]
        pos += 1
        if opcode not in (0xe8, 0xe9) or 0x10000 - ((pos - 1) % 0x10000) < 5:
            continue
        if pos + 4 > len(result):
            break
        if result[pos + 3] in (0, 255):
            rel = (int.from_bytes(result[pos:pos + 3], 'little') -
                   ((pos + 4) & 0xffffff)) & 0xffffff
            result[pos:pos + 3] = rel.to_bytes(3, 'little')
            if rel & 0x800000:
                result[pos + 3] ^= 0xff
        pos += 4
    return bytes(result)


def parse_names(header):
    names = {}
    for match in re.finditer(re.escape(PREFIX.encode('utf-16le')), header):
        pos = match.start()
        length = struct.unpack_from('<I', header, pos - 4)[0]
        name = header[pos:pos + length].decode('utf-16le')
        if name.endswith('\\'):
            continue
        q = pos + length
        # Font, assembly, components, tasks, languages, check, after, before.
        for _ in range(8):
            n = struct.unpack_from('<I', header, q)[0]
            q += 4 + n
            require(q < len(header), 'Invalid file entry')
        # Two WinVersion records, each Win32 + NT + service pack = 10 bytes.
        location = struct.unpack_from('<I', header, q + 20)[0]
        relative = name[len(PREFIX):].replace('\\', '/')
        require(not Path(relative).is_absolute() and '..' not in Path(relative).parts,
                'Unsafe destination path')
        require(location not in names or names[location] == relative,
                'Conflicting file locations')
        names[location] = relative
    require(set(names) == set(range(35)), 'Unexpected file entry inventory')
    return names


def extract(source, output, manifest):
    data = source.read_bytes()
    require(hashlib.sha256(data).hexdigest() == SOURCE_SHA256,
            'This extractor only accepts the pinned original installer SHA-256')
    require(data[HEADER_OFFSET:HEADER_OFFSET + 35].startswith(
        b'Inno Setup Setup Data (5.5.7) (u)'), 'Unexpected installer version')
    header, next_offset, header_info = read_header_block(data, HEADER_OFFSET + 64)
    locations, _, location_info = read_header_block(data, next_offset)
    require(len(locations) == 35 * 74, 'Unexpected location record size')
    names = parse_names(header)
    require(data[DATA_OFFSET:DATA_OFFSET + 4] == b'zlb\x1a', 'Missing solid chunk')
    prop = data[DATA_OFFSET + 4]
    dictionary = (2 | (prop & 1)) << (prop // 2 + 11)
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW,
        filters=[{'id': lzma.FILTER_LZMA2, 'dict_size': dictionary}])
    solid = dec.decompress(data[DATA_OFFSET + 5:])
    require(dec.eof, 'Incomplete payload LZMA2 stream')
    files = []
    for index in range(35):
        p = index * 74
        first, last, chunk, offset, size, compressed_size = struct.unpack_from(
            '<IIIQQQ', locations, p)
        flags = struct.unpack_from('<H', locations, p + 72)[0]
        require(first == last == chunk == 0 and flags in (0x80, 0x90),
                'Unexpected payload flags or slices')
        payload = solid[offset:offset + size]
        require(len(payload) == size, 'Truncated file')
        if flags & 0x10:
            payload = decode_instructions(payload)
        sha1 = hashlib.sha1(payload).digest()
        require(sha1 == locations[p + 36:p + 56],
                f'File {index} checksum mismatch: {names[index]}')
        target = output / names[index]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        target.chmod(0o644)
        files.append({'index': index, 'path': names[index], 'size': size,
            'solid_offset': offset, 'inno_flags': hex(flags),
            'installer_sha1_verified': sha1.hex(),
            'sha256': hashlib.sha256(payload).hexdigest()})
    require(sum(f['size'] for f in files) == len(solid), 'Unaccounted solid bytes')
    result = {'source': str(source), 'source_sha256': SOURCE_SHA256,
        'source_size': len(data), 'format': 'Inno Setup 5.5.7 Unicode',
        'method': 'Offline stdlib Python; CRC32 metadata, LZMA1/LZMA2, instruction reversal; SHA1 verified for all 35 files',
        'format_reference': 'https://github.com/dscharrer/innoextract',
        'header_blocks': [header_info, location_info],
        'solid_offset': DATA_OFFSET, 'solid_size': len(solid),
        'files': files, 'installer_executed': False, 'payload_executed': False}
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, default=Path('extracted/payload'))
    parser.add_argument('--manifest', type=Path,
                        default=Path('evidence/extraction-manifest.json'))
    args = parser.parse_args()
    result = extract(args.source, args.output, args.manifest)
    print(f"Verified and extracted {len(result['files'])} files; {result['solid_size']} bytes")
