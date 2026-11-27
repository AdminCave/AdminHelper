### Fixed

- Agent (FreeBSD): the warning for mounts that did not answer statfs no longer counts a path listed twice and names mounts below a network share, not only network mounts.
- Hooks: the failure notice of a hook that raised no longer says the details are in the "server" log, since schedule and server.startup hooks log in the scheduler service.
