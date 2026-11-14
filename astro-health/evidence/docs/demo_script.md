# Storm Day demo beats

Setup before the demo: backend running with `SIGNING_KEY` set, simulator in
`--storm` mode, three browser tabs on `/ui/`: the crew health monitor
(`tablet/monitor.html`), the helmet HUD (`hud/`), the Earth base (`earth/`).

1. **Normal day.** Monitor shows every channel NOMINAL, each tile labelled
   SIMULATED or REAL with its dataset; the "why trust this" panel explains the
   agreeing assessments.
2. **The real event window opens.** Earth base NASA panel: DONKI flares and
   Kp for 2024-05-08 to 05-14, RadLab dose rates measured inside the ISS in
   that window — context, clearly separated from the live decision.
3. **The storm reaches the crew (simulated).** Dose rate climbs; pipeline A
   says normal, limits escalates; the Checker sides with escalation. The
   monitor shows the split ("the most cautious one decided"); the HUD shows
   the tier, the one authorized action, and the disagreement marker.
4. **Delay dial at Mars.** Earth base downlink log: urgent summaries go
   first, routine GREEN waits for the digest; signed chain anchors ride
   along. Restart the backend with `RECORDS_PATH` set: the queue survives.
5. **Tamper one record.** Edit the store, run verify: the chain breaks
   visibly at the edited record; the checkpoint catches truncation too.
6. **Earth replays the decision** byte-for-byte (same hash) and files a
   simulated review; the crew acknowledgement chain shows who saw what.
7. **Earth tests a rule change on past decisions** before uplink: which
   decisions change, and the loosening that would have softened a taken
   decision is flagged unsafe (`evidence/results/rulechange_replay.md`).
8. **Evidence tables** — only from real runs: `python -m evidence.run_all
   --seed 42` regenerates all of them; the red team is 18 for 18.
9. **Kill the backend.** Every view drops to its explicit no-link state;
   nothing on screen can be mistaken for a current all-clear.
