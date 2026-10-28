#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Pack the A51 S-Boot image set into a byte-reproducible up_param image.

    python3 -I up-param-pack.py --images DIR --out FILE [--reference IMG]

The output is a GNU tar of the 25 JPEGs in the member order S-Boot ships
(A515FXXU8HWI1), with S-Boot's own header values (dpi/dpi 1000, mode 0444,
fixed mtime), closed by two zero blocks, padded to a 10240-byte record,
then zero-filled to the full up_param partition (8 MiB), so a dd of the
file replaces every byte and no older tar data survives behind it.

Headers are written by hand instead of with tarfile: tarfile fills
devmajor/devminor with "0000000\\0", S-Boot's image leaves them NUL.

--reference takes the stock image or tar (Samsung firmware; not shipped
with the art). When given, the member order must match and every header
must equal the stock header byte for byte except the size and chksum
fields.

Exit: 0 written, 1 input/verification failure, 2 usage error.
"""

import argparse
import hashlib
import os
import sys

BLOCK = 512
RECORD = 20 * BLOCK                  # GNU tar default blocking factor
PART_SIZE = 8 * 1024 * 1024          # up_param = sda4, 8,388,608 bytes

MEMBERS = (
    "android_logo.jpg", "booting_warning.jpg", "device_lock.jpg",
    "device_unlock.jpg", "download_error.jpg", "download.jpg",
    "letter.jpg", "logo.jpg", "lpm.jpg", "secure_error.jpg",
    "setting_logo.jpg", "SUD_0.jpg", "SUD_10.jpg", "SUD_1.jpg",
    "SUD_2.jpg", "SUD_3.jpg", "SUD_4.jpg", "SUD_5.jpg", "SUD_6.jpg",
    "SUD_7.jpg", "SUD_8.jpg", "SUD_9.jpg", "svb_orange.jpg",
    "warning.jpg", "warning_svb.jpg",
)
MODE = 0o444
OWNER_ID = 1000
OWNER_NAME = b"dpi"
MTIME = 1695281807                   # 2023-09-21 07:36:47 UTC
GNU_MAGIC = b"ustar  \0"             # magic "ustar " + version " \0"

SIZE_FIELD = slice(124, 136)
CHKSUM_FIELD = slice(148, 156)


class PackError(Exception):
    pass


def octal(value, width):
    """NUL-terminated zero-padded octal, as GNU tar writes numeric fields."""
    text = b"%0*o" % (width - 1, value)
    if len(text) != width - 1:
        raise PackError(f"{value} does not fit a {width}-byte field")
    return text + b"\0"


def field(raw, width):
    if len(raw) > width:
        raise PackError(f"{raw!r} longer than {width} bytes")
    return raw.ljust(width, b"\0")


def header(name, size):
    hdr = bytearray(BLOCK)
    hdr[0:100] = field(name.encode("ascii"), 100)
    hdr[100:108] = octal(MODE, 8)
    hdr[108:116] = octal(OWNER_ID, 8)
    hdr[116:124] = octal(OWNER_ID, 8)
    hdr[SIZE_FIELD] = octal(size, 12)
    hdr[136:148] = octal(MTIME, 12)
    hdr[156:157] = b"0"
    hdr[257:265] = GNU_MAGIC
    hdr[265:297] = field(OWNER_NAME, 32)
    hdr[297:329] = field(OWNER_NAME, 32)
    hdr[CHKSUM_FIELD] = b" " * 8
    hdr[CHKSUM_FIELD] = b"%06o\0 " % sum(hdr)
    return bytes(hdr)


def padded(data):
    return data + bytes(-len(data) % BLOCK)


def read_jpeg(path):
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(b"\xff\xd8") or not data.rstrip(b"\0").endswith(b"\xff\xd9"):
        raise PackError(f"{path}: not a complete JPEG (SOI/EOI)")
    return data


def check_image_dir(images):
    present = {e for e in os.listdir(images) if e.lower().endswith(".jpg")}
    missing = sorted(set(MEMBERS) - present)
    unknown = sorted(present - set(MEMBERS))
    if missing or unknown:
        raise PackError(f"image set mismatch: missing={missing} unknown={unknown}")


def build(images):
    check_image_dir(images)
    out = bytearray()
    for name in MEMBERS:
        data = read_jpeg(os.path.join(images, name))
        out += header(name, len(data)) + padded(data)
    tar_end = len(out)
    out += bytes(2 * BLOCK)
    out += bytes(-len(out) % RECORD)
    if len(out) > PART_SIZE:
        raise PackError(f"tar is {len(out)} bytes, partition holds {PART_SIZE}")
    return bytes(out), tar_end


def headers(image):
    """Return ([(offset, header)], end-of-archive offset)."""
    found = []
    pos = 0
    while True:
        hdr = image[pos:pos + BLOCK]
        if len(hdr) < BLOCK:
            raise PackError(f"truncated header at {pos}")
        if hdr == bytes(BLOCK):
            return found, pos
        found.append((pos, hdr))
        size = int(hdr[SIZE_FIELD].rstrip(b"\0 ") or b"0", 8)
        pos += BLOCK + size + (-size % BLOCK)


def masked(hdr):
    m = bytearray(hdr)
    m[SIZE_FIELD] = bytes(12)
    m[CHKSUM_FIELD] = bytes(8)
    return bytes(m)


def compare_reference(tar, reference):
    """Header-for-header equality with the stock image, size/chksum excepted."""
    ours, our_end = headers(tar)
    stock, stock_end = headers(reference)
    our_names = [h[0:100].rstrip(b"\0") for _, h in ours]
    stock_names = [h[0:100].rstrip(b"\0") for _, h in stock]
    if our_names != stock_names:
        raise PackError(f"member order differs from reference: {stock_names}")
    for (_, a), (_, b) in zip(ours, stock):
        if masked(a) != masked(b):
            name = a[0:100].rstrip(b"\0").decode()
            raise PackError(f"{name}: header differs from reference outside size/chksum")
    if any(reference[stock_end:]):
        raise PackError("reference has data after its end-of-archive marker")
    return len(ours), our_end


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--images", required=True, help="directory with the 25 JPEGs")
    p.add_argument("--out", required=True, help="output image (written atomically)")
    p.add_argument("--reference", help="stock up_param image or tar to compare headers with")
    args = p.parse_args()

    try:
        tar, data_end = build(args.images)
        if args.reference:
            with open(args.reference, "rb") as f:
                n, _ = compare_reference(tar, f.read())
            print(f"reference: {n} headers equal outside size/chksum, order equal")
        image = tar + bytes(PART_SIZE - len(tar))
    except (OSError, PackError) as e:
        print(f"up-param-pack: {e}", file=sys.stderr)
        return 1

    tmp = args.out + ".tmp"
    with open(tmp, "wb") as f:
        f.write(image)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, args.out)

    print(f"members:      {len(MEMBERS)}")
    print(f"member data:  {data_end} bytes (headers + 512-padded data)")
    print(f"tar length:   {len(tar)} bytes (with end-of-archive, 10240 record)")
    print(f"partition:    {PART_SIZE} bytes, free {PART_SIZE - len(tar)}")
    print(f"sha256:       {hashlib.sha256(image).hexdigest()}  {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
