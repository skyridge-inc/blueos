---
id: STORY-5
title: 'skynet config: provision mavlink-camera-manager video streams for Cockpit'
status: In Progress
assignee: []
created_date: '2026-11-01 03:44'
labels:
  - skynet
  - video
dependencies: []
priority: medium
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Cockpit only plays video that mavlink-camera-manager (MCM) serves over WebRTC. Before this change `skynet config upload` had no MCM support. sky1's MCM had no streams, so Cockpit showed no video even though MediaMTX WebRTC worked at :8889/front.

Added a `video_streams:` YAML section, the BlueOSClient methods get_video_streams/add_video_stream (via the BlueOS proxy at /mavlink-camera-manager/streams), extract.fetch_video_streams/video_stream_post_body, and an upload step that creates streams missing by name and leaves existing ones alone. sky1 gets a Redirect stream from rtsp://127.0.0.1:8555/front.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 config download captures MCM streams into video_streams
- [ ] #2 config upload creates missing streams by name and skips existing ones
- [ ] #3 --dry-run lists streams without contacting MCM
- [ ] #4 Unit tests cover client, extract and upload paths
- [ ] #5 Live check: after upload, sky1 MCM lists 'front' and Cockpit's video widget plays it
<!-- AC:END -->
