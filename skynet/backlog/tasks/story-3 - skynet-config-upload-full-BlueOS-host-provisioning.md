---
id: STORY-3
title: 'skynet config upload: full BlueOS host provisioning'
status: In Progress
assignee: []
created_date: '2026-10-27 19:26'
updated_date: '2026-10-27 19:33'
labels: []
dependencies: []
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Extend config download/upload to provision extensions, DHCP servers (mode: server), DHCP reservations (/etc/blueos/dnsmasq.conf bind-mounted into blueos-core via bootstrap startup.json), and reboot. Plan: ~/.claude/plans/look-in-the-skynet-atomic-puffin.md
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 upload installs missing extensions from YAML
- [x] #2 upload starts DHCP servers for mode: server addresses
- [x] #3 upload writes DHCP reservations and ensures startup.json bind, then reboots
- [x] #4 download captures dhcp_reservations
- [x] #5 tests cover new behavior
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented host provisioning in config download/upload (host_config.py, BlueOSClient add_dhcp_server/install_extension/run_host_command/reboot). Live-verified on sky1: upload wrote reservation, added startup.json bind, rebooted; bind + reservation present after reboot. Camera move to 192.168.10.2 pending camera power-cycle or lease renewal.
<!-- SECTION:NOTES:END -->
