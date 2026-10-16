#!/bin/bash
# Sourced by engine.sh, start-studio.sh and stop-studio.sh (needs WF_SSD_ROOT and WF_SSD_IMAGE
# from wfstudio.envdump, and LOGS). Mounts the optional disk image that holds the WFStudio
# volume, and detaches it again only if the Studio is the one that attached it.

SSD_MARKER="$LOGS/ssd-attached-by-studio"

ssd_mounted() { /sbin/mount | /usr/bin/grep -q " on $WF_SSD_ROOT ("; }

# Name of the drive that holds the image, e.g. /Volumes/WATSON-DEV/x.sparsebundle -> WATSON-DEV
ssd_host_drive() {
  case "$WF_SSD_IMAGE" in
    /Volumes/*) local rest="${WF_SSD_IMAGE#/Volumes/}"; echo "${rest%%/*}" ;;
    *) echo "the drive holding $(basename "$WF_SSD_IMAGE")" ;;
  esac
}

# 0 = SSD is mounted (attaching the image if needed). 1 = not available; reason on stdout.
ssd_ensure() {
  ssd_mounted && return 0
  if [ -z "${WF_SSD_IMAGE:-}" ]; then
    echo "SSD not connected. Plug in $(basename "$WF_SSD_ROOT") and open the Studio again."; return 1
  fi
  if [ ! -e "$WF_SSD_IMAGE" ]; then
    echo "SSD not connected. Plug in $(ssd_host_drive) and open the Studio again."; return 1
  fi
  if /usr/bin/hdiutil attach -nobrowse "$WF_SSD_IMAGE" >> "$LOGS/launch.log" 2>&1 && ssd_mounted; then
    echo "$WF_SSD_IMAGE" > "$SSD_MARKER"; return 0
  fi
  echo "Couldn't mount $(basename "$WF_SSD_IMAGE"). Details are in $LOGS/launch.log."; return 1
}

# Detach the image, but only if the Studio attached it.
ssd_release() {
  [ -f "$SSD_MARKER" ] || return 0
  if ! ssd_mounted; then rm -f "$SSD_MARKER"; return 0; fi
  if /usr/bin/hdiutil detach "$WF_SSD_ROOT" >> "$LOGS/launch.log" 2>&1; then
    rm -f "$SSD_MARKER"; echo "WFStudio disk image detached."
  else
    echo "Couldn't detach $WF_SSD_ROOT (something is still using it). Eject it from Finder."; return 1
  fi
}
