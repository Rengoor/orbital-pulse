# 7 slides (including title)

1. **Title and hook line.** "An astronaut health tool that can never talk
   itself into reassuring you." Decision support, not diagnosis.
2. **The constraint.** 4-22 min one-way delay at Mars; astronauts
   self-monitor; NASA's stated need for autonomy with post hoc confirmation
   (see `sources.md`).
3. **NASA data used and what each layer drives.** Inspiration4 baselines and
   blood panels, RadLab dose rates (context only, unit note), DONKI window;
   REAL vs SIMULATED labels everywhere; remove a dataset and its output
   disappears (table in the README).
4. **Architecture in three boxes: assess, referee, prove.** Blind pipelines
   -> deterministic Checker (escalate freely, lower only through the
   confirmed-data-fault path) -> hashed, signed, chained records with
   checkpoints; fail-safe GREY when the system itself fails.
5. **Screenshots.** Helmet HUD (one tier, one action), crew health monitor
   ("why should I trust this decision?"), Earth base with the chain breaking
   on a tampered record, and a no-link state.
6. **Results.** Ablation table (full system 0 unsafe approvals vs 4-10 for
   every ablation), red team 18/18 blocked, rule-change replay flagging the
   loosening, downlink summaries at 0.13x the bytes.
7. **Limits and next steps.** Placeholder thresholds awaiting sourcing and
   medical review; LLM untested against a real model; shared HMAC key ->
   asymmetric signatures; no API auth; blind scenarios reserved for an
   unbiased author. (Same list as `limits.md` — say it plainly.)
