---
id: STORY-4
title: >-
  skynet: rename config→config_blueos; add config_gps (USB GNSS receiver
  download/upload)
status: Done
assignee: []
created_date: '2026-10-28 09:55'
updated_date: '2026-10-28 09:57'
labels:
  - skynet
dependencies: []
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Rename the BlueOS 'config' command group to 'config_blueos'. Add 'config_gps' with download/upload that scan USB serial ports for the RTK+heading receiver (Septentrio mosaic-H) and read/write its boot config as YAML.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 'skynet config_blueos download/upload' work; 'skynet config' removed
- [x] #2 'skynet config_gps download' finds the receiver over USB and writes identity + boot config YAML
- [x] #3 'skynet config_gps upload' resets to defaults, replays the YAML config, saves to Boot and verifies
- [x] #4 Tests cover port scan, reply parsing, apply/verify and CLI; README updated
<!-- AC:END -->
