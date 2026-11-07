# How Prefoundly decides how much to send

A wallet pays its users' bills, card purchases, and transfers through intermediary partners. Each partner pays out of a balance the wallet funds in advance. If that balance runs out, the partner charges a penalty and user payments stop. If it is too large, the money sits idle. Treasury teams usually size it by hand with a fixed buffer of a few days of payments.

Prefoundly replaces the fixed buffer with a forecast. Every day at 09:00 it predicts how much each partner will pay out until the next transfer lands, and sends the difference between that need and the balance the partner already holds.

This page explains the pipeline, in the order the code runs it, and why each step exists. For the commands, see [Command reference](cli.md). For the limits around execution, see [The autonomous agent](agent.md).

## The data is simulated, the calendar is real

No wallet shared transaction data, so `treasury simulate` builds a population that behaves like one:

- 20,000 users in seven archetypes from `config/archetypes.yaml`: formal salaried, informal, ANSES beneficiaries, young heavy users, investors, active crypto users, and merchants. Each user has paydays and recurring bills.
- One year of events, from 2025-11-01 to 2026-10-31: about 4.26 million payments.
- A shared macro factor, monthly inflation of 2 %, campaigns, and cohort waves (`src/treasury/simulate/`).
- Real Argentine holidays, aguinaldo and ANSES payment windows from `config/calendar_ar.yaml`.

`treasury.routing` sends each payment product to the partner that settles it (`config/partners.yaml`). A bill payment always settles at `bills_aggregator`, a crypto purchase always at `crypto_exchange`. That fixed mapping is why the forecast is per partner: the agent never chooses where a payment goes, it only funds the partner that will pay it.

The simulator checks itself against stylized facts: weekly seasonality stronger than 3-day seasonality, salaried spending peaking in the first five business days, and a heavy right tail. `data/sim/base/params.json` records the checks for the committed seed.

## Step 1. Group users by behavior

A real wallet does not know which archetype a user belongs to. `treasury.segmentation.KMeansSegmenter` infers segments from each user's transactions before the decision date: k-means on spending features, with k chosen by silhouette between 2 and 8. Users with less than 30 days of history or fewer than 5 events in the last 90 days go to a `new` segment.

Segmenting matters because groups move differently. Retirees spend in the ANSES window, salaried users at the start of the month, crypto buyers when the exchange rate jumps. A single model on the total blurs these patterns.

## Step 2. Forecast each segment, product, and partner

`treasury.models.segment_lgbm.SegmentLGBM` fits one LightGBM model per node, where a node is a segment, a product, and a partner. Each model predicts the ratio of the day's payments to a seasonal-naive baseline, with a Tweedie objective because many node-days are zero. The drivers are known in advance: active users per segment, planned campaigns, and payments already scheduled (autodebits).

Scheduled payments are certain, so the model adds them on top of the forecast instead of predicting them.

## Step 3. Simulate 1,000 scenarios

A point forecast says nothing about a bad day. `treasury.montecarlo` draws 1,000 paths for the coming days. Each path multiplies every node by its own noise and by one shared factor, an AR(1) process in logs. The shared factor matters: on a day when everyone spends more, all segments move together, and a model that treats them as independent produces intervals that are too narrow. The ablation in `reports/experiments/` shows it. Without the factor, the probability integral transform (PIT) histogram is U-shaped.

## Step 4. Size the deposit

`treasury.policy.recommend_deposit` takes the paths and the partner's position at 09:00:

- the available balance,
- transfers already in transit,
- when a transfer sent now would land (`treasury.rails.arrival_time`: wire on business days, stablecoin any day),
- and the window to cover, which runs until the next transfer can land. On a Friday that window is the whole weekend.

It finds, on each path, the lowest point the balance would reach in that window, and takes the alpha quantile across paths. With alpha 0.99 the deposit covers 99 of every 100 scenarios. The deposit is that need minus what the partner already holds, rounded up to `lot_size`, and zero when the partner already holds enough.

Money sent to a partner stays there. The agent never pulls a balance back, so it errs on the side of sending in time, not of sending more often.

## Step 5. Send it within hard limits

The amount goes to the autonomous agent, which applies hard limits, holds anything that looks like a broken forecast, and records the transfer. Claude writes the explanation of each decision but never changes the amount. [The autonomous agent](agent.md) covers this step.

## What the backtests show

`treasury experiments` replays eight weekly decision dates ending 2026-10-31, with a 14-day horizon, and compares the proposed policy with a fixed buffer at the same service level. Against a buffer chosen ahead of time (the fewest days that never fell short in the 16 weeks before), the proposed policy holds 23 % less capital on wire and 41 % less on stablecoin, with no day short. Source: `reports/experiments/exante_buffer.md`.

| rail | proposed policy | fixed buffer set ahead | capital saved |
|---|---|---|---|
| wire | 3.62e9 ARS, 0 % short | 4.71e9 ARS (11.6 days), 0 % short | 23 % |
| stablecoin | 1.97e9 ARS, 0 % short | 3.35e9 ARS (7.8 days), 0 % short | 41 % |

The full tables, including the model ablation and the case designed for the segment model to lose, are in [`reports/experiments/README.md`](../reports/experiments/README.md).

## Known limitations

- The data is synthetic. The results show the mechanism and its sensitivity to stated assumptions, not savings at a real wallet.
- The estimated autocorrelation of the shared factor is close to zero, so the model treats macro shocks as not lasting from one day to the next.
- Alpha is a quantile per decision, not the realized service level. The realized service sits above alpha because the policy is conservative.
- k-means segments cost some capital compared with the simulator's true labels at home (`reports/experiments/segmentation.md`).

## International variant

The same pipeline runs for partners abroad: `pix_br` (BRL) and `usd_acquirer` (USD), funded by `swift` or `stablecoin`. Its configuration lives in `config/intl/`, and its results in `reports/experiments/intl_README.md`.
