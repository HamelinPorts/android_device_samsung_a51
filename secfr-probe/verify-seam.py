#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0

"""Check that a51-secfr-probe really is bounded by the face seam.

The probe exists to answer one question: can the SEC_FR trusted application be
driven from libsecfr_engine.so alone, without the camera and preview layer in
libFaceService.so? A binary that quietly grew a dependency on that layer would
still build and still run, and would answer the wrong question. So the claim is
checked here rather than believed:

  1. The probe's direct dependencies are exactly the seam.
  2. Nothing in the whole transitive closure is a camera, surface, media or
     face-service library.
  3. Every vendor class member the probe calls is exported by the library that
     is supposed to export it, with the parameter list the probe was compiled
     against. This is what keeps SecfrSeam.h honest: Samsung ships no headers,
     so a wrong declaration would otherwise only show up as a link error at some
     later date, or not at all.

Reads ELF files directly so it needs no toolchain.
"""

import argparse
import glob
import os
import struct
import sys

# --- ELF -------------------------------------------------------------------

SHT_DYNSYM = 11
SHT_DYNAMIC = 6
SHN_UNDEF = 0
DT_NULL = 0
DT_NEEDED = 1
DT_SONAME = 14


class ElfError(Exception):
    pass


class Elf:
    """The little of ELF64 this check needs: sonames, dependencies, symbols."""

    def __init__(self, path):
        self.path = path
        with open(path, "rb") as handle:
            self.blob = handle.read()

        if self.blob[:4] != b"\x7fELF" or self.blob[4] != 2:
            raise ElfError("%s: not a 64-bit ELF file" % path)

        e_shoff, e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(
            "<Q", self.blob, 0x28
        ) + struct.unpack_from("<HHH", self.blob, 0x3A)

        self._sections = []
        for i in range(e_shnum):
            base = e_shoff + i * e_shentsize
            name, sh_type, _flags, _addr, offset, size, link, _info, _align, entsize = (
                struct.unpack_from("<IIQQQQIIQQ", self.blob, base)
            )
            self._sections.append(
                {"name": name, "type": sh_type, "offset": offset, "size": size,
                 "link": link, "entsize": entsize}
            )

        shstr = self._sections[e_shstrndx]
        for section in self._sections:
            section["name"] = self._string(shstr, section["name"])

        self.soname = os.path.basename(path)
        self.needed = []
        self.defined = set()
        self.undefined = set()
        self._read_dynamic()
        self._read_dynsym()

    def _string(self, strtab, index):
        start = strtab["offset"] + index
        end = self.blob.index(b"\0", start)
        return self.blob[start:end].decode("utf-8", "replace")

    def _find(self, sh_type):
        for section in self._sections:
            if section["type"] == sh_type:
                return section
        return None

    def _read_dynamic(self):
        dynamic = self._find(SHT_DYNAMIC)
        if dynamic is None:
            return
        strtab = self._sections[dynamic["link"]]

        offset = dynamic["offset"]
        while offset < dynamic["offset"] + dynamic["size"]:
            tag, value = struct.unpack_from("<qQ", self.blob, offset)
            offset += 16
            if tag == DT_NULL:
                break
            if tag == DT_NEEDED:
                self.needed.append(self._string(strtab, value))
            elif tag == DT_SONAME:
                self.soname = self._string(strtab, value)

    def _read_dynsym(self):
        dynsym = self._find(SHT_DYNSYM)
        if dynsym is None:
            return
        strtab = self._sections[dynsym["link"]]

        count = dynsym["size"] // dynsym["entsize"]
        for i in range(count):
            base = dynsym["offset"] + i * dynsym["entsize"]
            name, _info, _other, shndx, _value, _size = struct.unpack_from(
                "<IBBHQQ", self.blob, base
            )
            if name == 0:
                continue
            symbol = self._string(strtab, name)
            if shndx == SHN_UNDEF:
                self.undefined.add(symbol)
            else:
                self.defined.add(symbol)


# --- the contract ----------------------------------------------------------

PROBE_DIRECT_DEPENDENCIES = {
    "libsecfr_engine.so",   # trusted-application client
    "libsecfr_model.so",    # capture-model description
    "libteecl.so",          # GlobalPlatform TEE client API
    "liblog.so",            # the probe's own reporting
    "libutils.so",          # RefBase, for the objects the libraries hand back
    "libc++.so",
    "libc.so",
    "libm.so",
    "libdl.so",
}

# Pulling in any of these would mean the camera and preview layer cannot in fact
# be separated from the trusted-application client, which is the finding this
# probe is built to produce. Matched against the whole transitive closure.
FORBIDDEN_IN_CLOSURE = (
    "libFaceService.so",
    "libgui.so",
    "libgui_vendor.so",
    "libcamera2ndk.so",
    "libcamera2ndk_vendor.so",
    "libmediandk.so",
    "libstagefright_foundation.so",
    "libbinder.so",
    "libbinder_ndk.so",
    "libui.so",
    "libnativewindow.so",
)

# Exactly the members SecfrSeam.h declares, and where each has to come from.
SEAM = {
    "libsecfr_engine.so": [
        "_ZN7android10FaceEngineC1Ev",
        "_ZN7android10FaceEngine4initEv",
        "_ZN7android10FaceEngine6loadTAEv",
        "_ZN7android10FaceEngine8unloadTAEv",
        "_ZN7android10FaceEngine7releaseEv",
        "_ZN7android10FaceEngine16getSecurityLevelERj",
        "_ZN7android10FaceEngine17generateChallengeEjjR26sec_fr_generated_challenge",
    ],
    "libsecfr_model.so": [
        "_ZN7android5Model11getInstanceEv",
        "_ZN7android5Model9getConfigEv",
        "_ZN7android13Configuration9printDataEv",
        "_ZN7android13Configuration14getCameraCountEv",
        "_ZN7android13Configuration16getCameraInfoIdxEj",
        "_ZN7android10CameraInfo9printDataEv",
        "_ZN7android10CameraInfo11getRotationEv",
        "_ZN7android10CameraInfo15getSurfaceCountEv",
        "_ZN7android10CameraInfo14getSurfaceInfoEj",
        "_ZN7android10CameraInfo20getCurrentCameraTypeEv",
        "_ZN7android11SurfaceInfo9printDataEv",
        "_ZN7android11SurfaceInfo11getRotationEv",
    ],
}

# Imported from libutils, not from the vendor libraries: the vendor classes are
# reference counted with the platform's own RefBase.
ALLOWED_PLATFORM_CXX_IMPORTS = {
    "_ZNK7android7RefBase9incStrongEPKv",
    "_ZNK7android7RefBase9decStrongEPKv",
    "_ZnwmRKSt9nothrow_t",
    "_ZSt7nothrow",
}


def find_library(soname, roots):
    for root in roots:
        candidate = os.path.join(root, soname)
        if os.path.exists(candidate):
            return candidate
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", help="the built a51-secfr-probe binary")
    parser.add_argument(
        "--root", action="append", default=[], dest="roots",
        help="directory to resolve DT_NEEDED entries in (repeatable)")
    args = parser.parse_args()

    roots = list(args.roots)
    if not roots:
        product_out = os.environ.get("PRODUCT_OUT")
        if not product_out:
            parser.error("no --root given and PRODUCT_OUT is not set")
        roots = [os.path.join(product_out, "vendor", "lib64"),
                 os.path.join(product_out, "system", "lib64")]
        roots += sorted(glob.glob(os.path.join(product_out, "apex", "*", "lib64")))

    failures = []
    notes = []

    probe = Elf(args.probe)

    # 1. direct dependencies
    direct = set(probe.needed)
    unexpected = direct - PROBE_DIRECT_DEPENDENCIES
    if unexpected:
        failures.append("probe links libraries outside the seam: %s"
                        % ", ".join(sorted(unexpected)))
    print("direct dependencies: %s" % ", ".join(sorted(direct)))

    # 2. transitive closure
    closure = {}
    pending = list(probe.needed)
    unresolved = []
    while pending:
        soname = pending.pop()
        if soname in closure or soname in unresolved:
            continue
        path = find_library(soname, roots)
        if path is None:
            unresolved.append(soname)
            continue
        library = Elf(path)
        closure[soname] = library
        pending.extend(library.needed)

    for forbidden in FORBIDDEN_IN_CLOSURE:
        if forbidden in closure or forbidden in unresolved:
            failures.append("FORBIDDEN in the dependency closure: %s" % forbidden)
    print("closure: %d libraries resolved, %d not found in the given roots"
          % (len(closure), len(unresolved)))
    if unresolved:
        notes.append("not resolved (checked for forbidden names only): %s"
                     % ", ".join(sorted(unresolved)))

    # 3. the seam itself
    for soname, symbols in SEAM.items():
        library = closure.get(soname)
        if library is None:
            failures.append("%s is not in the closure, so its seam cannot be checked"
                            % soname)
            continue
        for symbol in symbols:
            if symbol not in library.defined:
                failures.append("%s does not export %s — SecfrSeam.h no longer "
                                "matches the shipped library" % (soname, symbol))
            elif symbol not in probe.undefined:
                failures.append("probe does not import %s; the seam declared in "
                                "SecfrSeam.h is no longer exercised" % symbol)
    declared = {symbol for symbols in SEAM.values() for symbol in symbols}
    print("seam: %d vendor entry points declared and imported" % len(declared))

    # 4. nothing crept in beside the declared seam
    crept_in = {symbol for symbol in probe.undefined
                if symbol.startswith(("_Z", "sec_fr", "TEEC"))}
    crept_in -= declared | ALLOWED_PLATFORM_CXX_IMPORTS
    if crept_in:
        failures.append("probe imports C++ symbols outside the declared seam: %s"
                        % ", ".join(sorted(crept_in)))

    for note in notes:
        print("note: %s" % note)
    for failure in failures:
        print("FAIL: %s" % failure)

    if failures:
        print("verify-seam: FAILED (%d)" % len(failures))
        return 1
    print("verify-seam: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
