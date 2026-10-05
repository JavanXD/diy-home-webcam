#!/bin/bash -e
# Required by pi-gen: seed this stage's rootfs from the previous stage (stage2).

if [ ! -d "${ROOTFS_DIR}" ]; then
	copy_previous
fi
