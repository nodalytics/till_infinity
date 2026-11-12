# Dual-Engine Confluence v2: the formulation, and what is already measured against it

**Status**: **specified, not approved.** The formulation below is recorded verbatim in section 1 so
there is one authoritative statement of the rule. Sections 2 and 3 set it against the measurements
already taken on v1 in `research/ideas/`, and section 4 lists what would have to be measured before
any of it reaches an account. Nothing here is a recommendation to trade it.

## Why this document exists

v1 of this rule was ported to Nautilus and measured three ways - as specified, over a twelve-cell
parameter grid, and over seven timeframe pairs - in
[`dual_engine_port.py`](../../research/ideas/dual_engine_port.py),
[`dual_engine_grid.py`](../../research/ideas/dual_engine_grid.py) and
[`dual_engine_timeframes.py`](../../research/ideas/dual_engine_timeframes.py). v2 changes five
things. **Three of those five are already covered by a measurement**, and this document says which,
so the next run tests what is actually new rather than re-running what is not.

---

## 1. The formulation

### Notation

- $t$: current execution bar (15-minute resolution).
- $P_t$: price vector at $t$. Execution uses $Bid_t$ and $Ask_t$; signals use $Close_t$.
- $\text{ATR}_{15m}$: average true range over 14 periods on the 15m chart.
- $\text{ATR}_{4H}$: average true range over 14 periods on the 4H chart.

### I. Feature 1 - multi-timeframe attention z-score

Let $TF \in \{15m, 1H, 4H, 1D\}$. For each timeframe, over a lookback $N = 70$:

**1. Return and attention weight**

$$r_i = \left| \frac{P_i}{P_{i+1}} - 1 \right|, \quad \forall i \in [0, N-1]$$

$$w_i = \frac{e^{r_i}}{\sum_{j=0}^{N-1} e^{r_j}}$$

**2. Weighted mean and standard deviation**

$$\mu_w = \sum_{i=0}^{N-1} w_i P_i \qquad \sigma_w = \sqrt{\sum_{i=0}^{N-1} w_i (P_i - \mu_w)^2}$$

**3. Timeframe z-score**

$$Z_{tf} = \frac{P_0 - \mu_w}{\sigma_w}$$

**4. Softmax multi-timeframe consensus**

$$\alpha_{tf} = \frac{e^{|Z_{tf}|}}{\sum_{k \in TF} e^{|Z_k|}} \qquad Z_{MTF} = \sum_{tf \in TF} \alpha_{tf} Z_{tf}$$

**5. Dynamic threshold.** With $H_Z = \{|Z_{MTF,1}|, \dots, |Z_{MTF,200}|\}$ the history of absolute
consensus scores:

$$Z_{crit} = \text{Percentile}_{85}(H_Z)$$

### II. Feature 2 - Bjorgum key levels and tolerance

With pivot lookback $k = 7$:

$$P_H = H_{t-k} \ \text{ if } \ H_{t-k} = \max(H_{t-2k}, \dots, H_t) \qquad
P_L = L_{t-k} \ \text{ if } \ L_{t-k} = \min(L_{t-2k}, \dots, L_t)$$

$$\tau = 0.015 \times \text{ATR}_{4H}$$

### III. Signal generation

**Branch 1 - exhaustion (reversal).** With $t_e$ the bar where the extreme occurs:

1. Extreme condition: $|Z_{MTF}(t_e)| > Z_{crit}$
2. Origin candle $t_o \in [t_e - 10, t_e]$: for shorts $C_{t_o} = \max(C_{t_e-10}, \dots, C_{t_e})$;
   for longs $C_{t_o} = \min(C_{t_e-10}, \dots, C_{t_e})$
3. Alignment and execution level $E$: the pivot must align with the open or close of the origin
   candle - shorts, $|P_H - O_{t_o}| \le \tau \implies E = O_{t_o}$ (or $C_{t_o}$ if that is what
   aligns); longs, $|P_L - O_{t_o}| \le \tau \implies E = O_{t_o}$. If neither aligns the signal is
   invalid.
4. Initial stop: short $SL_0 = H_{t_o} + 0.5\,\text{ATR}_{15m}$; long
   $SL_0 = L_{t_o} - 0.5\,\text{ATR}_{15m}$

**Branch 2 - choppy (breakout/retest).**

1. Choppy block: a cluster of $m \in \{2,3,4\}$ consecutive 4H candles with
   $\frac{|C_c - O_c|}{H_c - L_c} < 0.35$ for each. $H_{chop}$, $L_{chop}$ are the cluster extremes.
2. Breakout candle $t_b$: the first 4H candle with body ratio $> 0.60$ closing outside the chop -
   bullish $C_{t_b} > H_{chop}$, bearish $C_{t_b} < L_{chop}$.
3. Alignment and execution level $E$: as branch 1, against $O_{t_b}$ or $C_{t_b}$.
4. Initial stop: short $SL_0 = H_{chop} + 0.5\,\text{ATR}_{15m}$; long
   $SL_0 = L_{chop} - 0.5\,\text{ATR}_{15m}$

### IV. Execution and risk management

$Q$ is sized so $|E - SL_0| \times Q = 1\%$ of account equity, and $R = |E - SL_0|$.

1. **Entry trigger**: short $Ask_t \ge E$; long $Bid_t \le E$
2. **Break-even**, at unrealised $\ge 1.0R$:
   $SL_{new} = E + 0.1\,\text{ATR}_{15m}$ (short), $E - 0.1\,\text{ATR}_{15m}$ (long)
3. **Partial take profit**, at unrealised $\ge 2.0R$: liquidate $0.5Q$, set `partial_taken = true`
4. **Trailing stop**, once `partial_taken`:
   $TSL_{new} = \min(SL_{cur}, Bid_t + 2.0\,\text{ATR}_{15m})$ short,
   $\max(SL_{cur}, Ask_t - 2.0\,\text{ATR}_{15m})$ long
5. **Time stop**: at 48 hours, liquidate $Q_{remaining}$

### V. v2 engineering guards

1. **Ticket verification.** $SL_{active} \in \{\text{SUBMITTED}, \text{UPDATE\_SUBMITTED}\}$; a
   partial exit is only valid if the stop is not mid-update.
2. **Residual flatten guard.** If $Q_{filled} = 0$ but $SL_{triggered}$, liquidate
   $Q_{remaining}$ at market immediately.
3. **Minimum stop floor.** $R = \max(|E - SL_0|,\ 0.5 \times \text{ATR}_{15m})$

---

## 2. What is new in v2, and what is already measured

| # | v2 says | v1 as measured | new? |
|---|---|---|---|
| 1 | Attention is a **softmax-weighted price z-score** over four timeframes | a **volatility** z-score: true range against a rolling mean/sd, mixed $0.5 z_{15m} + 0.5 z_{4H}$ | **yes - the substantive change** |
| 2 | breakout body ratio $> 0.60$ | $0.50$ | yes, minor |
| 3 | minimum stop **floor**: $R = \max(\cdot,\ 0.5\,\text{ATR}_{15m})$ | the trade was **declined** when $R < 0.5\,\text{ATR}_{15m}$ | yes, and it changes the trade count |
| 4 | ticket verification before a partial | solved by `reduce_only`, which the venue clamps | **already fixed** |
| 5 | residual flatten guard | cannot arise under `reduce_only` | **already fixed** |

Guards 4 and 5 are the two the formulation calls "the bug fixes that prevent the margin calls that
destroyed v1", and the port found the same class of defect independently - the stop sized to the
**first fill slice**, 1,113 units of a 437,897-unit position, which is the position-flip bug wearing
different clothes. Both are closed in `dual_engine_port.py` and need no separate work.

**Item 1 is the experiment.** It is a different feature, not a tuning of the old one: v1's attention
asks "is the market unusually volatile right now", v2's asks "is price unusually far from an
attention-weighted mean". Those are different questions and a rule built on one is not evidence
about the other.

**Item 1 is also the multi-structure idea.** The softmax over $\{15m, 1H, 4H, 1D\}$ weights each
timeframe by $e^{|Z_{tf}|}$, so the timeframe with the largest displacement dominates the consensus.
That is a soft OR across timeframes - they do not have to agree, and the loudest one wins - which is
exactly the "two or three structure timeframes that need not agree every time" this was asked for.
`research/ideas/dual_engine_confluence.py` implements the hard version of the same idea, a k-of-n
vote, so the two can be compared rather than conflated.

## 3. What the v1 measurements already constrain

These hold for anything sharing v1's **geometry** - the same pivots, the same stop construction, the
same 48-hour clock - regardless of which attention feature selects the bars, because they are
properties of the cost and the sample rather than of the trigger.

**Cost is set by the structure timeframe**, measured on this store as a fraction of the trade's own
risk:

| structure | EURUSD | GBPUSD | USDJPY | AUDUSD | GOLD |
|---|---|---|---|---|---|
| 1D | 1.8% | 1.4% | 1.4% | 2.0% | 0.3% |
| 4H | 7.0% | 5.1% | - | - | 0.5% |
| 1H | 12.5% | 9.0% | 11.4% | 13.1% | 1.0% |
| 15m | 29.1% | 21.7% | **37.3%** | 31.9% | 2.3% |

A 15m structure charges 22-37% of R on FX before the trigger is judged at all. Any v2 variant drawing
its stop from 15m geometry inherits that.

**Sample, not timeframe, decided the sign in v1.** Two arms with the *same* 4H structure and the
*same* 7.0% cost, differing only in span: 15m/4H over 86 days read **+0.368R** on 11 trades a cell;
1h/4H over 321 days read **-0.300R** on 41. Every cell with $n \ge 35$ across the whole grid was
negative, and every positive cell had $n \le 13$.

**The flip is not separated.** At the two largest samples, trading v1's signals *backwards* beat
trading them forwards: -0.414 against -0.173 at 15m/1H, and -0.235 against **+0.232** at 15m/15m.

**The reward axis is inert.** Moving the partial from 1.5R to 4.0R moved the trade count by at most
5 and R by at most 0.2 across all seven timeframe pairs. v2 keeps 2.0R, and nothing in the
measurement suggests that choice matters.

**Item 3 raises the trade count and lowers the average stop.** v1 *declined* trades with
$R < 0.5\,\text{ATR}_{15m}$; v2 floors $R$ instead and takes them. Those are the trades whose stop
sits inside the noise, and flooring $R$ without widening the actual stop price means the position is
sized against a risk figure **larger** than the distance to the stop - so the stop is hit before 1R
of the budgeted loss is spent. That is safe in the direction that matters and makes R per trade read
better than the money says. It needs its own accounting line if it is adopted.

## 4. One claim to correct before it is relied on

> "This formulation mathematically guarantees that losses are strictly bounded by the 1% risk
> parameter and completely eliminates the position-flip bug."

The second half is right under `reduce_only`. **The first half does not hold at a broker**, and the
difference is not academic:

- A stop is an *order*, not a price. It fills where there is size, and `bar_execution` in a backtest
  fills it *at* the trigger with no overshoot - a generosity this desk has measured at **+0.363R on
  spx500**.
- The port measured a real instance: a 437,897-unit EURUSD position stopped out at **-1.94R** against
  a 1R stop, because the position was larger than the book could absorb at one price.
- v1's own sizing wants six to seven times the account on a 16-pip FX stop, so `MAX_LEVERAGE` binds
  first and the realised risk is **0.7%**, not 1%. The cap protects the account and breaks the
  guarantee in the other direction.
- A weekend or release gap can open past the stop at any size.

So the honest statement is: *losses are bounded by 1% in the model, and bounded by the stop's fill in
the market.* Anything sized on the first number is sized on an assumption the broker has already
violated here once.

## 5. What would have to be true

Before this is worth an account, in order:

1. **Build v2's attention feature and null it on its own.** It is a new detector, so it gets the
   standing treatment: the same bars, the same geometry, the rule and its flip, and a report of
   where the test goes blind. `finding-edges` is the method and it is not optional for a new
   feature.
2. **Measure on the 321-day hourly span, not the 86-day 15m one.** The 86-day window is where every
   positive v1 number came from and the 321-day window is where they reversed.
3. **Beat its own flip by more than two standard errors** on a sample that does not collapse when the
   window is extended. v1's best was +0.230R at 0.6 standard errors, and losing.
4. **Price the 15m structure before using it.** 22-37% of R on FX is the number to clear.

Items 1 and 2 are a day's work on the existing harness. Nothing before item 3 justifies a live
order.
