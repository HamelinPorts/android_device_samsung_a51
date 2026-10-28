# Bootloader screens (`up_param`) for the Galaxy A51 (SM-A515F)

Replacement images for the screens the Samsung bootloader (S-Boot) draws itself: the boot logo,
the unlocked-bootloader and custom-software warnings, the off-mode charging splash and the
Download-mode screens. S-Boot reads them from the `up_param` partition, a tar of 25 JPEGs.

> ⚠ **Unofficial, developer feature. Opt-in only.** Nothing here is built into the ROM, and this
> port's (unofficial) OTA never writes `up_param` (it writes only the standard images and `dtbo`);
> a Samsung firmware update would.
> Tested on one bootloader-unlocked A515F with bootloader **A515FXXU8HWI1**. Other bootloader
> versions may expect other member names. Behaviour with a locked bootloader is untested.
> **Back up `up_param` before writing it** (see [Rollback](#rollback)).

## Contents

| path | what |
|---|---|
| `images/` | the 25 JPEGs, the artifact of record |
| `render.py` | the generator for all 25 (Pillow + DejaVu fonts, geometry only) |
| `up-param-pack.py` | packs `images/` into a byte-reproducible `up_param.bin` (Python 3 standard library only) |
| `LICENSE`, `NOTICE` | Apache-2.0; attribution and trademark notes |

## The images

| file | px | screen |
|---|---|---|
| `logo.jpg` | 1080×2400 | boot logo |
| `letter.jpg` | 1080×2400 | second boot splash (stock: the wordmark) |
| `svb_orange.jpg` | 936×1800 | boot warning: bootloader unlocked, "Press power to continue" |
| `booting_warning.jpg` | 936×438 | boot banner: custom (unsigned) software |
| `lpm.jpg` | 528×528 | off-mode charging splash, shown before the Android charger UI |
| `android_logo.jpg` | 390×390 | icon slot (stock: the Android robot); here the swirl mark |
| `setting_logo.jpg` | 390×390 | icon slot (stock: settings gears) |
| `warning.jpg` | 1080×1890 | Download mode entry: continue / cancel / barcode |
| `warning_svb.jpg` | 1080×1893 | Download mode entry with the "long press: device unlock mode" option |
| `download.jpg` | 1080×1020 | Download mode: downloading |
| `download_error.jpg` | 729×771 | Download mode: update failed |
| `secure_error.jpg` | 930×1014 | security error (unauthorized software blocked) |
| `device_unlock.jpg` | 1080×1878 | bootloader unlock prompt |
| `device_lock.jpg` | 1080×1236 | bootloader lock prompt |
| `SUD_0.jpg` … `SUD_10.jpg` | 303×57 | Download mode USB port labels ("USB Port #00" … "#10") |

Constraints when editing an image: keep the pixel size of its slot, save as **baseline** JPEG
(not progressive), and strip all metadata (EXIF/ICC/XMP/comments). `render.py` does all three.

## Regenerating the images

    python3 render.py OUTDIR      # writes the 25 JPEGs into a new, empty OUTDIR

The output depends on the Pillow and DejaVu font versions, so it is not guaranteed to be
byte-identical to `images/`. The committed JPEGs are what `up_param.bin` is built from.

## Building `up_param.bin`

    python3 -I up-param-pack.py --images images --out up_param.bin

Expected result: 8,388,608 bytes, sha256
`d4670807b976c87f80e6da08fc96fe3fd9e777f2ca2ba22ff41de76e73a50fdf`.

The image is a GNU tar of the 25 members in the order and with the header values of the stock
partition (A515FXXU8HWI1), padded to a 10240-byte record and zero-filled to the full 8 MiB, so a
write replaces every byte of the partition. With `--reference <stock up_param image>` the packer
also checks every header against your own stock copy (it is not shipped here).

## Installing (opt-in)

Address the phone explicitly with `adb -s <serial>` if more than one device is connected.

**First, for either route, check the bootloader version** (with the phone booted to Android):

    adb shell getprop ro.boot.bootloader                         # must print A515FXXU8HWI1

If it prints anything else, **stop**: the member list is specific to this bootloader, and the
Download-mode screens themselves come from `up_param`.

### Root `dd` (the tested route)

Needs root adb (`adb root`, a userdebug build). With `su` instead, `adb root` does not apply:
wrap each device command below in `su -c '…'`, keeping `exec-out` for the backup so it stays
binary-clean, e.g. `adb exec-out "su -c 'cat /dev/block/by-name/up_param'" > up_param-backup.img`.

    adb root
    adb shell blockdev --getsize64 /dev/block/by-name/up_param   # must print 8388608
    adb exec-out "cat /dev/block/by-name/up_param" > up_param-backup.img
    adb shell sha256sum /dev/block/by-name/up_param              # the partition's hash ...
    sha256sum up_param-backup.img                                # ... must equal the backup's; keep it safe
    adb push up_param.bin /data/local/tmp/up_param.bin
    adb shell sha256sum /data/local/tmp/up_param.bin             # must be d4670807…0fdf
    adb shell "dd if=/data/local/tmp/up_param.bin of=/dev/block/by-name/up_param bs=1M count=8 conv=fsync && sync"
    adb shell "blockdev --flushbufs /dev/block/by-name/up_param; echo 3 > /proc/sys/vm/drop_caches"
    adb shell sha256sum /dev/block/by-name/up_param              # must be d4670807…0fdf
    adb shell rm /data/local/tmp/up_param.bin
    adb reboot

If the read-back hash differs, write the backup back **before** rebooting.

### Odin, BL slot (untested on this bootloader)

Run the bootloader version check above first (`getprop ro.boot.bootloader` must print
`A515FXXU8HWI1`), and take the backup from Android before entering Download mode.

Wrap the image in a single-file USTAR tar with an appended md5. The member name must be the
partition's PIT flash file name, `up_param.bin` (inferred from the stock BL package, which ships
`up_param.bin.lz4`).

    tar --format=ustar -cf up_param.tar up_param.bin
    md5sum up_param.tar >> up_param.tar
    mv up_param.tar up_param.tar.md5

Load `up_param.tar.md5` into the **BL** slot (Odin) or run `odin4 -b up_param.tar.md5`.
Download mode cannot read partitions; the only backup is the one taken from Android.

## Rollback

1. **Preferred:** write your own backup back with the same `dd` command (from Android or a rooted
   recovery), or as a single-image Odin flash: rename it to `up_param.bin` and wrap it as above.
2. Last resort: flash the stock `BL_….tar.md5` of the **same** bootloader version in the BL slot
   only. It restores the stock `up_param`, but it also rewrites the other bootloader images,
   **including the stock `vbmeta`**: LineageOS may then not boot until this port's `vbmeta` and
   recovery are flashed again.

This port's (unofficial) OTA never writes `up_param`; a Samsung firmware update (OTA or a BL
package) would, and restores the stock images.

## Licence

Apache-2.0, see `LICENSE` and `NOTICE`. Samsung is a trademark of Samsung Electronics Co., Ltd.;
this project is not affiliated with or endorsed by Samsung.
