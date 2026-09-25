# analysis/ — Stage 2 scaffold

Stage 2 of the Week-1 overreaction study (the fit / simulate / horse-race
stage; the contract is `../method-spec.md`, the scope and open questions are
`STAGE2_SCOPE.md`). **Nothing here is implemented yet:** every function is a
typed, documented stub that raises `NotImplementedError` — no model has been
fitted, no season simulated, no score computed. Intended run order once
built: `loso.run_loso` (which drives `ratings` → `estimators` →
`checkpoints` → per-fold simulation) → `horse_race` scoring and the
full-sample `estimators` / `decay` estimands → `ratings.fill_panel_priors`
for the three deferred panel columns → `loso.freeze_outputs` so the post
reads only frozen frames in `../data/`. Ten open questions (Q1–Q10 in the
scope doc) need owner resolution before implementation — Q1 (2008/09 seed),
Q2 (β̂/K̂ units), and Q5 (simulation conditioning) are blocking.
