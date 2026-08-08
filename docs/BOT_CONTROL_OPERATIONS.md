# Bot Control Operations Runbook

## Safety principle

Bot Control must prefer an uncertain result over an unsafe retry.

The system must never automatically:

- retry an uncertain Gate write;
- release a lock protecting an uncertain operation;
- assume that a timeout means the Gate operation failed;
- create another bot because the previous response was lost.

---

## Safe baseline

The normal safe state is:

    ALLOW_BOT_CREATE=false
    BOT_CREATE_SIMULATION=true

    ALLOW_BOT_STOP=false
    BOT_STOP_SIMULATION=true

    BOT_CONTROL_LIVE_ARMED=false

Check the current state with:

    PYTHONPATH=. .venv/bin/python \
      scripts/bot_control_operator_status.py

Expected:

    "risk_state": "DISARMED"

---

## Emergency disable the current state with:

    PYTHONPATH=. .venv/bin/python \
      scripts/bot_control_operator_status.py

Expected

Immediately disarm Bot Control with:

    cd /opt/gate-bot-dashboard

    ./scripts/bot_control_emergency_disable.sh

This forces:

    ALLOW_BOT_CREATE=false
    BOT_CREATE_SIMULATION=true
    ALLOW_BOT_STOP=false
    BOT_STOP_SIMULATION=true
    BOT_CONTROL_LIVE_ARMED=false

and recreates only the gate-bot-dashboard service.

The emergency script does not change the configured live account
allowlist.

Run emergency disable if:

- an unexpected live operation occurs;
- the wrong account or strategy appears to be targeted;
- a live API response is ambiguous;
- repeated application errors occur during a live operation;
- Bot Control locking behaves unexpectedly;
- the operator cannot determine whether Gate accepted an operation.

Do not retry the operation immediately afterward.

---

## Live execution controls

A live operation requires all relevant barriers to permit it.

For Create:

    ALLOW_BOT_CREATE=true
    BOT_CREATE_SIMULATION=false
    BOT_CONTROL_LIVE_ARMED=true

For Stop:

    ALLOW_BOT_STOP=true
    BOT_STOP_SIMULATION=false
    BOT_CONTROL_LIVE_ARMED=true

The account must also be present in:

    BOT_CONTROL_LIVE_ACCOUNTS

or the final unrestricted configuration may use:

    BOT_CONTROL_LIVE_ACCOUNTS=*

The initial canary account is:

    zolnode

This is a rollout restriction, not a permanent architectural limit.

---

## Market and investment policy

The final live Spot Grid implementation is not restricted to
EQTY_USDT.

Bot Control may create Spot Grid bots for any supported Gate.io
spot pair that passes Gate pair validation.

Examples include:

    EQTY_USDT
    BTC_USDT
    ETH_BTC
    SOL_USDC

There is no permanent static USDT or fiat investment cap.

The maximum investment is determined dynamically from the
currently available balance of the pair's quote currency.

Examples:

    BTC_USDT -> maximum based on available USDT
    ETH_BTC  -> maximum based on available BTC
    SOL_USDC -> maximum based on available USDC

The requested investment may equal the full currently available
quote balance.

A request above the available quote balance must be rejected
before Gate submission.

---

## Confirmation phrases

Simulation:

    CREATE
    STOP

Live:

    LIVE CREATE
    LIVE STOP

The UI must clearly distinguish live execution from simulation.

---

## Before every live operation

1. Create a database backup.

2. Confirm:

       git status

   contains no unexpected local changes.

3. Run:

       PYTHONPATH=. .venv/bin/python \
         scripts/bot_control_operator_status.py

4. Review Bot Control -> Needs Attention.

5. Confirm there is no unresolved request affecting the intended
   operation.

6. Confirm there is no conflicting held operation lock.

7. Confirm the authenticated dashboard user owns the intended
   account.

8. Confirm Monitor and Bot Control credentials map to the same
   Gate account.

9. Confirm rate limiting is enabled.

10. Confirm startup crash recovery is enabled.

11. Verify the intended account, market and strategy ID.

12. Submit a live operation only once.

Never retry merely because the HTTP response is slow.

---

## Uncertain operations

If an operation becomes uncertain:

1. Do not retry it.
2. Do not release the lock automatically.
3. Open Bot Control -> Needs Attention.
4. Open the request details.
5. Run read-only reconciliation.
6. Review Gate evidence.
7. Reconcile again if the outcome remains inconclusive.

A missing running bot does not prove that Create failed.

A running bot does not necessarily prove that Stop was never
submitted.

---

## Startup crash recovery

If the application crashes while a Bot Control request is:

    reserved
    submitting

startup recovery changes it to:

    uncertain

while preserving its operation lock.

Startup recovery must:

- perform no Gate retry;
- perform no automatic lock release;
- preserve the original audit evidence;
- surface the request for operator review.

---

## Manual lock release

Manual release is exceptional.

Only consider manual release when:

- the request is uncertain;
- reconciliation has been performed;
- the latest evidence has been reviewed;
- the result is not stop_in_progress;
- the operator understands that release permits another
  operation.

Manual release does not change the original uncertain audit
status.

A reason must always be recorded.

---

# First live canary: Stop only

The first live Gate write will be a controlled Stop.

Create remains disabled and simulated.

Required temporary configuration:

    ALLOW_BOT_CREATE=false
    BOT_CREATE_SIMULATION=true

    ALLOW_BOT_STOP=true
    BOT_STOP_SIMULATION=false

    BOT_CONTROL_LIVE_ARMED=true
    BOT_CONTROL_LIVE_ACCOUNTS=zolnode

Live confirmation:

    LIVE STOP

---

## Selecting the Stop canary

Use one intentionally selected running zolnode bot whose
termination is acceptable.

Before the canary verify:

- account = zolnode;
- strategy ID is correct;
- strategy type is correct;
- market is correct;
- Monitor reports it running;
- no relevant held lock exists;
- no related unresolved Needs Attention request exists.

Do not choose an arbitrary production bot just because it is
available.

---

## Stop canary procedure

1. Backup the database.

2. Enable live Stop only.

3. Keep Create disabled and simulated.

4. Recreate only gate-bot-dashboard.

5. Run operator status.

Expected:

    "risk_state": "LIVE_STOP_ENABLED"

6. Verify Create still reports:

       allowed=false
       simulation=true
       live=false

7. Log in as zolnode.

8. Open the selected bot.

9. Run Stop preparation.

10. Review the current Gate snapshot.

11. Open final confirmation.

12. Confirm the UI clearly states LIVE.

13. Type exactly:

       LIVE STOP

14. Submit exactly once.

15. Record the request ID.

16. Do not retry if the result is delayed or uncertain.

---

## After a successful Stop canary

Verify:

- request status succeeded;
- correct strategy ID was used;
- Gate Monitor view shows the expected stopped state;
- operation lock lifecycle is correct;
- read-only reconciliation confirms the stopped state;
- no unexpected Needs Attention request exists.

Export both:

- JSON audit;
- CSV audit.

Then immediately disarm:

    ./scripts/bot_control_emergency_disable.sh

Confirm:

    "risk_state": "DISARMED"

The canary is not complete until Bot Control is disarmed again.

---

## If the Stop canary is uncertain

Immediately run:

    ./scripts/bot_control_emergency_disable.sh

Then:

1. open the uncertain request;
2. confirm the operation lock remains held;
3. run read-only reconciliation;
4. inspect Gate state;
5. do not submit another Stop.

Never manually release while the latest reconciliation result is:

    stop_in_progress

---

# Future live Create canary

Live Create is considered only after the Stop canary succeeds.

The first Create should use an intentionally selected:

- account;
- market;
- investment amount.

Temporary rollout restrictions are acceptable.

Permanent design:

- arbitrary supported Gate spot pairs;
- no permanent market allowlist;
- no static investment hard cap;
- maximum investment equals current available quote-currency
  balance.

After the first controlled Create, disarm Bot Control and review
the full audit, reconciliation and lock lifecycle before further
live Creates.

---

## Evidence to retain

For every live canary record:

- UTC timestamp;
- Git commit;
- account;
- action;
- market;
- strategy ID;
- request ID;
- Bot Control mode;
- HTTP result;
- reconciliation result;
- operation lock result;
- Needs Attention result;
- audit JSON;
- audit CSV;
- relevant application logs.

Never record Gate API keys or API secrets.

---

## Application rollback

If an application rollback is required:

1. emergency-disable Bot Control;
2. backup the database;
3. identify the known-good Git commit;
4. restore application code;
5. rebuild only gate-bot-dashboard;
6. verify database integrity;
7. verify API health;
8. verify Bot Control remains DISARMED.

Do not roll back the SQLite database solely because application
code was rolled back unless the database itself is proven damaged.
