### Changed

- **Schonung unter Last begrenzt:** Setzt der Agent unter Last Sammler aus, behalten deren Checks ihren letzten Status
  nur noch 15 Minuten ab Beginn der Schonung und werden danach `unknown`, bis sie wieder gemessen werden;
  `agent_resources` warnt ab Beginn der Schonung statt nach 30 Minuten.
