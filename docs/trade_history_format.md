# Trade history: the file format I need

Send one CSV file in the format below. Check it first:

```
python -m quantbot history check path\to\your_trades.csv
```

It prints `valid`, or every problem with its row and column. A complete example is in
[examples/trade_history_example.csv](examples/trade_history_example.csv).

## Format

- CSV, UTF-8, comma separator, first row is the header.
- **One row per fill**: every execution, including partial fills and stop or target hits. A round trip is two
  or more rows that share a `position_id`.
- Decimal point `.`, no thousands separators.
- Times in ISO 8601 **with a UTC offset**: `2026-03-02T09:05:12+01:00` or `2026-03-02T08:05:12Z`.
  A time without an offset is rejected, because a one-hour error moves a trade to another bar.

| Column | Required | Meaning | Example |
| --- | --- | --- | --- |
| `fill_id` | yes | Unique id of the execution (the broker's deal id if you have it) | `F0001` |
| `timestamp` | yes | When it filled, with UTC offset | `2026-03-02T09:05:12+01:00` |
| `instrument` | yes | Broker symbol or IG epic | `IX.D.DAX.IFD.IP` |
| `side` | yes | `BUY` or `SELL` | `BUY` |
| `quantity` | yes | Positive size in the broker's unit: contracts, shares, or amount per point | `1` |
| `price` | yes | Fill price in the instrument's quote currency | `18012.4` |
| `currency` | yes | Quote currency of the price, ISO code | `EUR` |
| `order_id` | no | The order the fill belongs to | `O0001` |
| `position_id` | no | Groups the fills of one trade | `P0001` |
| `commission` | no | Cost in account currency, positive | `1.00` |
| `financing` | no | Overnight funding in account currency, positive = paid | `0.42` |
| `account_currency` | no | ISO code | `EUR` |
| `fx_rate` | no | Price currency to account currency at the fill | `0.9205` |
| `order_type` | no | `MARKET`, `LIMIT` or `STOP` | `MARKET` |
| `stop_price`, `target_price` | no | Levels attached at entry | `17920` |
| `strategy` | no | Your own label for the setup | `breakout` |
| `intent` | no | `ENTRY` or `EXIT`, if you know it | `ENTRY` |
| `notes` | no | Free text. Kept as data; never used to make or approve a decision | |

Unknown extra columns are reported as warnings and ignored.

## If your export looks different

If your ProRealTime or IG export (CSV or XLSX) does not match, send the original file unchanged together with
answers to these four questions. I will write the importer from the real export in the broker phase.

1. Which time zone are the times in, if the export does not say?
2. What does the quantity mean: contracts, shares, or amount per point?
3. Does it contain every trade, manual and automatic, for the whole period?
4. What is the account currency?

## Where it goes

Put the file under `data/` in the project folder. `data/` is excluded from git, so your trades are never
committed. Set `trade_history.path` in `config/quantbot.yaml` to its location.

## How many trades

Send everything you have. At the start of the ML phase I will ask for the file again and report what the count
allows. As a rough guide from Phase 0: telling a 55 % hit rate from a coin flip, at 5 % significance and 80 %
power, takes about 620 trades.
