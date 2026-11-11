# Runbook: stopping a live ProOrder script by hand (draft)

**Status: draft, written in Phase 1 to apply owner decision 5 (2026-11-10).** It becomes final in the broker
phase, against a real deployment. Steps marked **VERIFY** must be checked against your ProRealTime version; I have
not seen its user interface.

## Why this runbook exists

A live ProOrder script runs on ProRealTime's servers. Once started it places orders on its own. This system's kill
switch, daily loss limit, reconciliation and approval gate cannot stop it. Only you can, in ProRealTime or
through your broker. That is why a live script counts as M3 (owner decision 5).

## Rules before any live script is started

- The strategy holds an effective, signed M3 grant. The code checks this (`PolicyEngine.may_deploy_outside_gate`).
- Every generated script carries hard limits in its own code: a maximum position, a daily loss stop that ends
  the system, a stop-loss on every entry, and a flat-after time.
- ProRealTime's own maximum position size for the system is set as well. Per the ProBacktest and ProOrder
  documentation, it overrides larger quantities in the code.
- A daily read-only reconciliation import compares the broker's trades and positions with what the script was
  expected to do. It is built in the broker phase, from a sample export.

## When to stop it

- Any downgrade that halts the bot: kill switch, daily loss limit, drawdown, reconciliation mismatch.
- The daily reconciliation shows a trade or position you cannot explain.
- The script behaves differently from its backtest, or you have any doubt.

## Steps

1. **Stop the system in ProRealTime first.** Open the list of running ProOrder systems and stop this one.
   **VERIFY** the menu path. **VERIFY** whether stopping also closes its position; assume it does not.
   It must come first: per the ProBacktest and ProOrder documentation, manual orders on an instrument are
   unavailable while a system runs on it.
2. **Close what it left open.** Close the position and cancel any working orders on that instrument, in
   ProRealTime or in the broker's own platform.
3. **If ProRealTime is unreachable,** log in to the broker's own platform, or contact its dealing desk by phone,
   and close the position there. Keep the broker's support number with this runbook. **VERIFY** it.
4. **Halt the bot as well.** Create the file `data/KILL` in the project folder. The bot halts on its next step
   and stays halted across restarts.
5. **Check.** The broker shows no position and no working order on the instrument. The next reconciliation
   import is clean.
6. **Write down what happened:** the time, what you saw, what you did. It goes into the post-mortem.
7. **Restart only after the cause is understood.** Releasing the kill switch needs a command signed with your
   operator key. A live script is restarted only through the same M3 promotion rules.
