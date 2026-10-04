#!/usr/bin/env bash
# Clone live OS from SD → NVMe with a unique PARTUUID.
# Desired disks: pi/host/desired.env. Run as root while still booted from SRC_DISK.
# Does not reboot — follow with apply-bootloader.sh (or remigrate-to-nvme.sh).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
DESIRED="${ROOT}/pi/host/desired.env"
if [[ -f "$DESIRED" ]]; then
  # shellcheck source=/dev/null
  source "$DESIRED"
fi

SRC_DISK="${SRC_DISK:-/dev/mmcblk0}"
DST_DISK="${DST_DISK:-/dev/nvme0n1}"
DST_BOOT="${DST_DISK}p1"
DST_ROOT="${DST_DISK}p2"
MNT="${MNT:-/mnt/nvme-migrate}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root" >&2
  exit 1
fi

root_src="$(findmnt -no SOURCE /)"
case "$root_src" in
  ${SRC_DISK}*|${SRC_DISK#/dev/}*) ;;
  *)
    echo "refusing: root is $root_src (expected ${SRC_DISK}p2). Already migrated? use verify-host.sh" >&2
    exit 1
    ;;
esac

if [[ ! -b "$DST_DISK" ]]; then
  echo "missing $DST_DISK" >&2
  exit 1
fi

if findmnt "$DST_DISK" >/dev/null 2>&1 || findmnt "$DST_BOOT" >/dev/null 2>&1 || findmnt "$DST_ROOT" >/dev/null 2>&1; then
  echo "refusing: destination has mounted partitions" >&2
  exit 1
fi

echo "==> partitioning $DST_DISK (match SD boot layout, root fills disk)"
wipefs -a "$DST_DISK"
# Match Imager layout: boot starts at sector 16384, 512MiB FAT, rest ext4
parted -s "$DST_DISK" mklabel msdos
parted -s "$DST_DISK" mkpart primary fat32 16384s 1064959s
parted -s "$DST_DISK" mkpart primary ext4 1064960s 100%
parted -s "$DST_DISK" set 1 lba on
partprobe "$DST_DISK"
sleep 2

# Unique disk identifier → unique PARTUUIDs (avoid clash with SD)
NEW_ID="$(printf '0x%08x' "$(od -An -N4 -tu4 /dev/urandom | tr -d ' ')")"
echo "==> disk identifier $NEW_ID"
sfdisk --disk-id "$DST_DISK" "$NEW_ID"
partprobe "$DST_DISK"
sleep 1

DISK_HEX="$(echo "${NEW_ID#0x}" | tr 'A-F' 'a-f')"
PART_BOOT="${DISK_HEX}-01"
PART_ROOT="${DISK_HEX}-02"
echo "    PARTUUID boot=$PART_BOOT root=$PART_ROOT"

echo "==> formatting"
mkfs.vfat -F 32 -n bootfs "$DST_BOOT"
mkfs.ext4 -F -L rootfs "$DST_ROOT"

echo "==> mounting"
mkdir -p "$MNT"
mount "$DST_ROOT" "$MNT"
mkdir -p "$MNT/boot/firmware"
mount "$DST_BOOT" "$MNT/boot/firmware"
findmnt "$MNT/boot/firmware" | grep -q "$DST_BOOT" || {
  echo "FATAL: $DST_BOOT is not mounted at $MNT/boot/firmware" >&2
  exit 1
}

echo "==> rsync root (this takes a while)"
rsync -aAXH --info=progress2 --delete \
  --exclude={"/dev/*","/proc/*","/sys/*","/tmp/*","/run/*","/mnt/*","/media/*","/lost+found","/boot/firmware/*"} \
  / "$MNT/"

echo "==> rsync boot firmware"
rsync -aAXH --info=progress2 --delete /boot/firmware/ "$MNT/boot/firmware/"
BOOT_COUNT="$(find "$MNT/boot/firmware" -type f | wc -l)"
if [[ "$BOOT_COUNT" -lt 50 ]]; then
  echo "boot firmware copy looks empty ($BOOT_COUNT files) — is $DST_BOOT mounted at $MNT/boot/firmware?" >&2
  findmnt "$MNT/boot/firmware" || true
  exit 1
fi
echo "    boot files copied: $BOOT_COUNT"

echo "==> rewrite cmdline + fstab for NVMe PARTUUIDs"
CMDLINE="$MNT/boot/firmware/cmdline.txt"
if [[ ! -f "$CMDLINE" ]]; then
  echo "missing $CMDLINE" >&2
  exit 1
fi
python3 - "$CMDLINE" "$PART_ROOT" <<'PY'
import pathlib, re, sys
path, part_root = pathlib.Path(sys.argv[1]), sys.argv[2]
text = path.read_text()
text2, n = re.subn(r"root=PARTUUID=[^ \n]+", f"root=PARTUUID={part_root}", text)
if n != 1:
    raise SystemExit(f"cmdline root replace failed n={n}")
path.write_text(text2.rstrip() + "\n")
PY
cat >"$MNT/etc/fstab" <<EOF
proc            /proc           proc    defaults          0       0
PARTUUID=${PART_BOOT}  /boot/firmware  vfat    defaults          0       2
PARTUUID=${PART_ROOT}  /               ext4    defaults,noatime  0       1
EOF

sync
echo "NVMe cmdline.txt:"
cat "$CMDLINE"
umount "$MNT/boot/firmware"
umount "$MNT"
rmdir "$MNT" 2>/dev/null || true

echo "==> done. NVMe PARTUUID root=$PART_ROOT"
echo "    Next: sudo $HERE/apply-bootloader.sh && sudo reboot"
echo "    Or:   sudo $HERE/remigrate-to-nvme.sh  (includes apply + reboot)"
lsblk -o NAME,SIZE,FSTYPE,LABEL,PARTUUID "$DST_DISK"
blkid "$DST_BOOT" "$DST_ROOT"
