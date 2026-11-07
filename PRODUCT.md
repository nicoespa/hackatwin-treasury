# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
The treasury team of a wallet (fintech). Today they work out by hand how much money to prefund at the
intermediary partner that pays out on the wallet's behalf. With Prefoundly they open the monitoring screen to
check that the agent is covering well, and now and then they change the risk level. Nobody approves transfers.

## Product Purpose
Prefoundly predicts how much the wallet must prefund at its partner to cover users' payments until the next
transfer lands (the whole weekend on a Friday), and sends it automatically within hard limits. Success: the
partner account never runs dry, and less money sits idle than with a fixed buffer.

## Positioning
A forecast of every user segment's payments (k-means segments, LightGBM per segment, Monte Carlo with a shared
macro factor) turned into the exact transfer that covers a bad day, executed by an agent with no human in the
loop. The LLM only explains; it never decides an amount.

## Operating Context
- A wallet usually works with one intermediary partner. Money sent to the partner stays there: the partner does
  not hand a prefunded balance back on demand, so the agent only ever sends, never pulls back.
- One decision a day at 09:00: on business days a plan covering until the next plan lands (Friday covers the
  weekend); on weekend days a check that sends more only if the balance will fall short.
- Banks are closed at night and on weekends; transfers outside banking hours go by stablecoin (24/7).
- An MCP server lets the team's own agent read status and pause or resume the autonomous agent.

## Capabilities and Constraints
- Autonomy limits per currency (ARS: 500 M per transfer, 750 M per partner per day, 1.5 B per day), allow-listed
  destinations, kill switch, idempotent executor.
- The agent decides once a day at 09:00. The only human input is an optional order field: stop or resume sending,
  change the risk level (Bajo, Medio, Alto = covers a bad day of 1 in 100, 1 in 20, 1 in 10), cap or send an
  amount. Orders apply from the next decision; money already sent stays. With `ANTHROPIC_API_KEY` set, Claude
  reads the order; otherwise a keyword parser does.
- The data is simulated (20,000 users); holidays are real.

## Brand Commitments
- Name: Prefoundly. Logo at `src/treasury/monitor_logo.png`. Palette from the pitch deck: petrol #154E4B,
  deep #0E3836, teal #4FA28E (#3E9682 in the console for contrast), mint #9EDDC2, mint-soft #D6F2E5. Typeface: Figtree.
- Spanish (Argentine voseo) in the interface. No real company names. Plain words: no "rieles", no SWIFT/USDT jargon.

## Evidence on Hand
- Backtests in `reports/experiments/` (ex-ante buffer comparison: wire −23 %, stablecoin −41 % capital).
- The live engine `src/treasury/live.py` runs the dataset's settled payments on a simulated clock.
- No customers, prices or testimonials exist; do not invent them.

## Product Principles
- No human in the loop: the screen monitors, it does not ask for approval.
- Show the work: every decision the agent makes is visible step by step.
- Prediction against reality: the screen always shows what the model expected next to what happened.
- Orders are optional and only constrain the agent.
