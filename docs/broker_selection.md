# Broker selection: criteria and questionnaire

**Status (2026-11-10): no broker is recommended yet.** Your country of residence is still open, and web search
is disabled in this workspace, so a country-specific broker list could not be researched. Following your
instruction, this file holds the criteria and the questionnaire only. Nothing in Phase 1 depends on the choice:
the system runs against the paper broker, which needs no account and no tax identification number.

I am not a lawyer or a tax adviser. Confirm anything legal or tax-related with a local professional.

## What will not be recommended or built for

- A broker that skips identity verification, or offers to.
- Anything that relies on a false tax ID, residency or identity declaration.
- A broker's offshore entity used to get around rules that apply to residents of your country.

## Hard requirements: failing any one rules a broker out

1. It legally accepts residents of your country: the legal entity that would hold your account, and its regulator.
2. Full identity verification (KYC) with your real identity, address, residency and tax status.
3. A legitimate route for your tax-ID situation (see below).
4. An API for orders, positions and account history, or at least read-only history for reconciliation.
5. A demo or paper account usable through that API.
6. Funding and withdrawal that your country's foreign-exchange rules allow.
7. For leveraged retail products such as CFDs: negative balance protection or an equivalent.

## Scored criteria

| Criterion | Why it matters here | How it is scored |
| --- | --- | --- |
| Regulator and investor protection | Where your money sits if the broker fails | Regulator, compensation scheme, segregation of client money |
| Costs on your markets | Small edges disappear in costs | Spread, commission, overnight financing, FX conversion, platform and inactivity fees, on your expected trade count |
| API quality | Decides which modes are possible | Order types with attached stop and target, rate limits, historical data allowance, streaming, client order ids, demo parity |
| Execution modes it can carry | Declared per adapter in code | M0 and M1 only (ticket or ProOrder) versus M0 to M3 (order API) |
| ProRealTime availability | Lets you keep ProRealTime for charts, tickets and backtests | ProRealTime lists IG, Interactive Brokers and Saxo as partners |
| Instruments | Must match what you will trade | Indices, FX, single stocks, futures, options |
| Funding and withdrawal | Must be legal and practical from your bank | Methods, currencies, time to withdraw, fees |
| Historical data | Research needs more than an execution API usually gives | Depth and limits through the API; IG's is 10,000 price points a week |

## Tax identification number (TIN)

- **Find what your country uses.** The OECD's
  [tax identification numbers portal](https://www.oecd.org/en/networks/global-forum-tax-transparency/resources/aeoi-implementation-portal/tax-identification-numbers.html)
  describes, jurisdiction by jurisdiction, what serves as the TIN or its functional equivalent. In many countries
  the national identity number or a number issued by the tax authority serves as the TIN.
- **Why brokers ask.** Under the OECD Common Reporting Standard (CRS), brokers collect a self-certification of
  your tax residency and your TIN for each country where you are tax resident.
- **If you do not hold one.** CRS self-certification forms commonly offer a short list of reasons for not giving
  a TIN, typically: the country does not issue TINs; you cannot obtain one, with an explanation; or the country's
  law does not require it to be collected. The exact wording is on each broker's form. Choose only the reason that
  is true. A broker may still refuse to open the account without a TIN.
- **Getting one.** Where your tax authority issues TINs to individuals, the usual path is to register with it as
  a taxpayer. The country-specific steps go here once the country is known.
- **US securities.** Brokers ask non-US persons for form W-8BEN, which also asks for a foreign TIN.

## Capital controls and sending money abroad

Some countries require central-bank or ministry authorisation before a resident opens a foreign investment
account or transfers money abroad for investment. **Before funding any foreign account, confirm with your bank
or a local lawyer that it is allowed, and keep the authorisation if one is needed.** The live stage waits for that
confirmation.

## Questionnaire

Answer what you can; "don't know" is a useful answer.

1. Country of tax residence, and citizenship if different. Any other country where you are tax resident? Are you a US person?
2. Do you hold a tax identification number? Do you have a national identity number? Has your tax authority ever issued you a number?
3. Your bank: country and currency. Can it send an international transfer for investment, and does that need an authorisation?
4. Accounts you already have: ProRealTime, IG, Interactive Brokers, Saxo, others. Any demo accounts?
5. Must ProRealTime stay part of the setup?
6. Markets and instruments: indices, FX, single stocks, futures, options, crypto. CFDs or exchange-traded products?
7. Horizon: intraday or swing?
8. Capital for the small-live stage, and the monthly budget for data and APIs.
9. Leverage and short selling: allowed or not?

## What happens with your answers

I look up the TIN rules for your country on the OECD portal, check which brokers legally accept residents and on
what terms, fill the scored table for each, and recommend one or two with reasons. Until a live account exists,
only the paper broker is used.
