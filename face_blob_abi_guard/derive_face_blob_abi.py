#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2026 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#
"""Measure the libgui ABI facts the Samsung face prebuilt has baked in.

vendor/lib64/libFaceService.so constructs an
android::hardware::graphics::bufferqueue::V1_0::utils::H2BGraphicBufferProducer
with immediates instead of with the vtable and VTT of the libgui it is loaded
against.  Those immediates are patched in device/samsung/a51/extract-files.py,
which runs at extraction time -- long before libgui_vendor.so exists -- so it
cannot check itself.  This script measures the real geometry out of the built
library and emits it as constants; FaceBlobAbiGuard.cpp holds the values the
patched blob needs and fails the build when the two disagree.

Everything here is derived from the ELF.  Nothing about the vtable layout is
assumed, because the layout is not stable under changes that leave no trace in
the source tree: extendSlotCount() sits behind the read-only aconfig flag
COM_ANDROID_GRAPHICS_LIBGUI_FLAGS(WB_UNLIMITED_SLOTS), and flipping that flag
moves every secondary sub-table without a single line of source diff and
without a merge conflict.
"""

import argparse
import re
import struct
import subprocess
import sys

SHT_RELA = 4
SHT_ANDROID_RELA = 0x60000002

R_AARCH64_ABS64 = 257
R_AARCH64_RELATIVE = 1027

PT_LOAD = 1

# Itanium C++ ABI: every sub-table of a vtable group is preceded by
# [offset-to-top, typeinfo], so the sub-table's own two-word header starts two
# words below the address a vptr points at.
SUBTABLE_HEADER_WORDS = 2

H2B = ('N7android8hardware8graphics11bufferqueue4V1_05utils'
       '24H2BGraphicBufferProducerE')
VTABLE_SYMBOL = '_ZTV' + H2B
VTT_SYMBOL = '_ZTT' + H2B
# Construction vtable for the BBinder base; the decimal run after the class
# name is that base's offset inside the complete object.
BBINDER_CONSTRUCTION_VTABLE_RE = re.compile(
    r'^_ZTC' + re.escape(H2B) + r'(\d+)_NS_7BBinderE$'
)

SURFACE_HEADER_SUFFIX = 'gui/Surface.h'
H2B_HEADER_SUFFIX = 'bufferqueue/1.0/H2BGraphicBufferProducer.h'


class ElfError(Exception):
    pass


class Elf:
    """Just enough ELF64 little-endian to read symbols, data and relocations."""

    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as f:
            self.data = f.read()

        if self.data[:6] != b'\x7fELF\x02\x01':
            raise ElfError(f'{path}: not a 64-bit little-endian ELF')

        (e_phoff,) = struct.unpack_from('<Q', self.data, 0x20)
        (e_shoff,) = struct.unpack_from('<Q', self.data, 0x28)
        e_phentsize, e_phnum = struct.unpack_from('<HH', self.data, 0x36)
        e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(
            '<HHH', self.data, 0x3A
        )

        self.sections = []
        for i in range(e_shnum):
            off = e_shoff + i * e_shentsize
            (name, sh_type, _, addr, offset, size, link, _, _,
             entsize) = struct.unpack_from('<IIQQQQIIQQ', self.data, off)
            self.sections.append({
                'name_offset': name,
                'type': sh_type,
                'addr': addr,
                'offset': offset,
                'size': size,
                'link': link,
                'entsize': entsize,
            })

        strings = self.sections[e_shstrndx]['offset']
        for section in self.sections:
            section['name'] = self._string_at(
                strings + section['name_offset']
            )

        self.segments = []
        for i in range(e_phnum):
            off = e_phoff + i * e_phentsize
            (p_type, _, p_offset, p_vaddr, _, p_filesz, _,
             _) = struct.unpack_from('<IIQQQQQQ', self.data, off)
            if p_type == PT_LOAD:
                self.segments.append((p_vaddr, p_offset, p_filesz))

    def _string_at(self, offset):
        end = self.data.index(b'\0', offset)
        return self.data[offset:end].decode()

    def section_by_name(self, name):
        for section in self.sections:
            if section['name'] == name:
                return section
        raise ElfError(f'{self.path}: no {name} section')

    def section_bytes(self, section):
        start = section['offset']
        return self.data[start:start + section['size']]

    def read_word(self, vaddr):
        """Read the 8-byte image word mapped at vaddr, as a signed value."""
        for seg_vaddr, seg_offset, seg_size in self.segments:
            if seg_vaddr <= vaddr < seg_vaddr + seg_size:
                offset = seg_offset + (vaddr - seg_vaddr)
                (word,) = struct.unpack_from('<q', self.data, offset)
                return word
        raise ElfError(f'{self.path}: vaddr {vaddr:#x} is not in any PT_LOAD')

    def symbols(self, section_name):
        section = self.section_by_name(section_name)
        strings = self.sections[section['link']]['offset']
        result = []
        for i in range(section['size'] // 24):
            off = section['offset'] + i * 24
            (st_name, _, _, _, st_value,
             st_size) = struct.unpack_from('<IBBHQQ', self.data, off)
            result.append(
                (self._string_at(strings + st_name), st_value, st_size)
            )
        return result

    def relocations(self):
        """Every dynamic relocation, as (offset, symbol_index, type, addend)."""
        result = []
        for section in self.sections:
            if section['type'] == SHT_ANDROID_RELA:
                entries = decode_android_rela(self.section_bytes(section))
            elif section['type'] == SHT_RELA:
                entries = decode_rela(self.section_bytes(section))
            else:
                continue
            for offset, info, addend in entries:
                result.append((offset, info >> 32, info & 0xFFFFFFFF, addend))
        return result


def decode_rela(buf):
    entries = []
    for off in range(0, len(buf) - 23, 24):
        entries.append(struct.unpack_from('<QQq', buf, off))
    return entries


def read_sleb128(buf, pos):
    result = 0
    shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            if shift < 64 and byte & 0x40:
                result -= 1 << shift
            return result, pos


# Group flags of the APS2 packed relocation encoding.
RELOCATION_GROUPED_BY_INFO = 1
RELOCATION_GROUPED_BY_OFFSET_DELTA = 2
RELOCATION_GROUPED_BY_ADDEND = 4
RELOCATION_GROUP_HAS_ADDEND = 8

MASK64 = (1 << 64) - 1


def decode_android_rela(buf):
    """Decode SHT_ANDROID_RELA (the 'APS2' group-delta encoding)."""
    if buf[:4] != b'APS2':
        raise ElfError('packed relocations do not start with APS2')

    pos = 4
    count, pos = read_sleb128(buf, pos)
    offset, pos = read_sleb128(buf, pos)
    info = 0
    addend = 0
    entries = []

    while len(entries) < count:
        group_size, pos = read_sleb128(buf, pos)
        flags, pos = read_sleb128(buf, pos)

        group_offset_delta = 0
        if flags & RELOCATION_GROUPED_BY_OFFSET_DELTA:
            group_offset_delta, pos = read_sleb128(buf, pos)
        if flags & RELOCATION_GROUPED_BY_INFO:
            info, pos = read_sleb128(buf, pos)
        if flags & RELOCATION_GROUP_HAS_ADDEND:
            if flags & RELOCATION_GROUPED_BY_ADDEND:
                delta, pos = read_sleb128(buf, pos)
                addend += delta
        else:
            addend = 0

        for _ in range(group_size):
            if flags & RELOCATION_GROUPED_BY_OFFSET_DELTA:
                offset += group_offset_delta
            else:
                delta, pos = read_sleb128(buf, pos)
                offset += delta
            if not flags & RELOCATION_GROUPED_BY_INFO:
                info, pos = read_sleb128(buf, pos)
            if (flags & RELOCATION_GROUP_HAS_ADDEND
                    and not flags & RELOCATION_GROUPED_BY_ADDEND):
                delta, pos = read_sleb128(buf, pos)
                addend += delta
            entries.append((offset & MASK64, info & MASK64, addend))

    # A decoder that has drifted out of step almost always ends up here with
    # bytes left over, so this doubles as the format check.
    if pos != len(buf):
        raise ElfError(
            f'packed relocations: {len(buf) - pos} trailing bytes after '
            f'{count} entries'
        )
    return entries


def find_symbol(symbols, name):
    matches = {(value, size) for sym, value, size in symbols if sym == name}
    if len(matches) != 1:
        raise ElfError(f'{name}: expected one definition, found {len(matches)}')
    return matches.pop()


def measure_vtable_geometry(elf):
    """Derive the H2BGraphicBufferProducer sub-table offsets from the VTT.

    The VTT holds the very pointers a constructor installs, so the addends of
    the relocations that target the vtable are the sub-table offsets by
    definition.  Each one is then named by the offset-to-top word that sits
    directly above it, which is the negated offset of the base subobject the
    sub-table serves.
    """
    symbols = elf.symbols('.dynsym')
    vtable_addr, vtable_size = find_symbol(symbols, VTABLE_SYMBOL)
    vtt_addr, vtt_size = find_symbol(symbols, VTT_SYMBOL)

    bbinder_subobject = None
    for name, _, _ in symbols:
        match = BBINDER_CONSTRUCTION_VTABLE_RE.match(name)
        if match is not None:
            bbinder_subobject = int(match.group(1))
            break
    if bbinder_subobject is None:
        raise ElfError('no BBinder construction vtable for H2BGBP')

    # The first word of the primary sub-table's header block is the virtual
    # base offset of the only virtual base, RefBase.
    refbase_subobject = elf.read_word(vtable_addr)
    if refbase_subobject <= 0:
        raise ElfError(
            f'virtual base offset is {refbase_subobject}, expected positive'
        )

    relocations_by_offset = {
        offset: (symbol, reloc_type, addend)
        for offset, symbol, reloc_type, addend in elf.relocations()
    }

    sub_table_offsets = set()
    for slot in range(vtt_addr, vtt_addr + vtt_size, 8):
        target = elf.read_word(slot) & MASK64
        if target == 0:
            reloc = relocations_by_offset.get(slot)
            if reloc is None:
                raise ElfError(f'VTT slot {slot:#x} is neither set nor relocated')
            symbol, reloc_type, addend = reloc
            if reloc_type == R_AARCH64_ABS64:
                target = symbols[symbol][1] + addend
            elif reloc_type == R_AARCH64_RELATIVE:
                target = addend
            else:
                raise ElfError(
                    f'VTT slot {slot:#x} has unexpected relocation type '
                    f'{reloc_type}'
                )
        if vtable_addr <= target < vtable_addr + vtable_size:
            sub_table_offsets.add(target - vtable_addr)

    by_subobject = {}
    for offset in sub_table_offsets:
        offset_to_top = elf.read_word(
            vtable_addr + offset - SUBTABLE_HEADER_WORDS * 8
        )
        if -offset_to_top in by_subobject:
            raise ElfError(
                f'two sub-tables serve subobject {-offset_to_top}'
            )
        by_subobject[-offset_to_top] = offset

    missing = [
        name for name, subobject in (
            ('primary', 0),
            ('BBinder', bbinder_subobject),
            ('RefBase', refbase_subobject),
        ) if subobject not in by_subobject
    ]
    if missing:
        raise ElfError(
            f'VTT has no sub-table for: {", ".join(missing)} '
            f'(found subobjects {sorted(by_subobject)})'
        )

    return {
        'kH2BPrimaryVTableOffset': by_subobject[0],
        'kH2BBBinderVTableOffset': by_subobject[bbinder_subobject],
        'kH2BRefBaseVTableOffset': by_subobject[refbase_subobject],
        'kH2BBBinderSubobjectOffset': bbinder_subobject,
        'kH2BRefBaseSubobjectOffset': refbase_subobject,
        'kH2BVttSize': vtt_size,
    }


def measure_class_size(dwarfdump, elf_path, name, header_suffix):
    """Read a class' size out of the library's own debug info.

    The class name alone does not identify it -- the 1.0 and 2.0 bufferqueue
    wrappers share one -- so the declaring header picks the definition.
    """
    output = subprocess.run(
        [dwarfdump, f'--name={name}', '--show-children=false', elf_path],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    sizes = set()
    tag = None
    attributes = {}

    def take(tag, attributes):
        if tag not in ('DW_TAG_class_type', 'DW_TAG_structure_type'):
            return
        if 'DW_AT_byte_size' not in attributes:
            return
        if not attributes.get('DW_AT_decl_file', '').endswith(header_suffix):
            return
        sizes.add(int(attributes['DW_AT_byte_size'], 0))

    for line in output.splitlines():
        die = re.match(r'^0x[0-9a-f]+:\s+(DW_TAG_\w+)', line)
        if die is not None:
            take(tag, attributes)
            tag = die.group(1)
            attributes = {}
            continue
        attribute = re.match(r'^\s+(DW_AT_\w+)\s+\((.*)\)\s*$', line)
        if attribute is not None and tag is not None:
            attributes[attribute.group(1)] = attribute.group(2).strip('"')
    take(tag, attributes)

    if len(sizes) != 1:
        raise ElfError(
            f'expected exactly one sizeof({name}) declared in '
            f'{header_suffix}, got {sorted(sizes)}'
        )
    return sizes.pop()


HEADER_PREAMBLE = """\
/*
 * SPDX-FileCopyrightText: 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 *
 * GENERATED by device/samsung/a51/face_blob_abi_guard/derive_face_blob_abi.py
 * from the built libgui_vendor.so.  Do not edit.
 *
 * The values the face prebuilt needs these to be live in
 * device/samsung/a51/face_blob_abi_guard/FaceBlobAbiGuard.cpp.
 */

#pragma once

#include <stddef.h>

namespace a51::face_blob_abi {

"""

HEADER_EPILOGUE = """
}  // namespace a51::face_blob_abi
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dwarfdump', required=True,
                        help='path to llvm-dwarfdump')
    parser.add_argument('--out', required=True, help='header to generate')
    parser.add_argument('library', help='unstripped libgui_vendor.so')
    args = parser.parse_args()

    try:
        elf = Elf(args.library)
        values = measure_vtable_geometry(elf)
        values['kH2BSize'] = measure_class_size(
            args.dwarfdump, args.library, 'H2BGraphicBufferProducer',
            H2B_HEADER_SUFFIX,
        )
        values['kSurfaceSize'] = measure_class_size(
            args.dwarfdump, args.library, 'Surface', SURFACE_HEADER_SUFFIX,
        )
    except (ElfError, OSError, subprocess.CalledProcessError) as error:
        print(f'{sys.argv[0]}: {args.library}: {error}', file=sys.stderr)
        return 1

    with open(args.out, 'w') as out:
        out.write(HEADER_PREAMBLE)
        for name, value in values.items():
            out.write(f'inline constexpr size_t {name} = {value:#x};\n')
        out.write(HEADER_EPILOGUE)
    return 0


if __name__ == '__main__':
    sys.exit(main())
