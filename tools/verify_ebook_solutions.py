"""Re-compute every numeric worked solution of "Quantitative Finance From Scratch" (pp. 23-25)
from the book's public formulas and compare with the printed answer.
Writes tests/fixtures/ebook_solutions.json, which later phases load as unit-test fixtures.
Run: python tools/verify_ebook_solutions.py
"""
from __future__ import annotations
import json, math
from itertools import product
from pathlib import Path
from statistics import NormalDist

N = NormalDist()
rows = []

def add(qid, chapter, quantity, computed, printed, tol, unit=""):
    ok = abs(computed - printed) <= tol
    rows.append(dict(id=qid, chapter=chapter, quantity=quantity, computed=computed,
                     printed=printed, tol=tol, unit=unit, reproduces=ok))

# Ch1 returns
add("1.1a", 1, "simple return 80->60", 60/80 - 1, -0.25, 1e-12)
add("1.1b", 1, "return needed 60->80", 80/60 - 1, 0.333, 5e-4)
add("1.2a", 1, "total return +10% then -10%", 1.1*0.9 - 1, -0.01, 1e-12)
add("1.2b", 1, "sum of log returns", math.log(1.1) + math.log(0.9), -0.0101, 5e-5)
# Ch2 present value
add("2.1", 2, "FV 1000 at 4% for 3y", 1000*1.04**3, 1124.86, 5e-3, "$")
add("2.2a", 2, "PV of 500 in 2y at 5%", 500/1.05**2, 453.51, 5e-3, "$")
add("2.2b", 2, "PV of 500 in 2y at 8%", 500/1.08**2, 428.67, 5e-3, "$")
add("2.fig", 2, "100 at 5% for 10y (figure caption)", 100*1.05**10, 162.89, 5e-3, "$")
# Ch3 expected value
add("3.1", 3, "EV of fair die", sum(range(1, 7))/6, 3.5, 1e-12, "$")
add("3.2a", 3, "EV single number at 35:1", (1/37)*35 + (36/37)*(-1), -0.027, 5e-4, "$")
add("3.2b", 3, "EV $1 on red", 18/37 - 19/37, -0.027, 5e-4, "$")
# Ch4 random walk
paths = [100 + sum(p) for p in product((1, -1), repeat=4)]
add("4.1a", 4, "P(price=100 after 4 fair steps)", paths.count(100)/len(paths), 0.375, 1e-12)
add("4.1b", 4, "number of distinct end prices", len(set(paths)), 5, 0)
# arcsine law: share of long fair walks spending >90% of time on one side
add("4.2", 4, "arcsine-law share >90% one side", 2*(2/math.pi)*math.asin(math.sqrt(0.1)), 0.41, 5e-3)
# Ch5 square-root rule
add("5.1a", 5, "annual sd from 1% daily, 252d", 0.01*math.sqrt(252), 0.159, 5e-4)
add("5.1b", 5, "4-day sd from 1% daily", 0.01*math.sqrt(4), 0.02, 1e-12)
# Ch6 bell curve
add("6.1", 6, "P(R < -24%) for N(8%,16%)", N.cdf((-0.24-0.08)/0.16), 0.0228, 5e-5)
add("6.1b", 6, "one year in N", 1/N.cdf((-0.24-0.08)/0.16), 44, 0.5, "years")
# Ch7 volatility (population sd, divide by N as in the book)
r = [1, -2, 3, 0, -2]
m = sum(r)/len(r)
add("7.1a", 7, "mean of 5 daily log returns (%)", m, 0.0, 1e-12, "%")
add("7.1b", 7, "daily vol dividing by N (%)", math.sqrt(sum((x-m)**2 for x in r)/len(r)), 1.90, 5e-3, "%")
# Ch8 Sharpe
add("8.1a", 8, "Sharpe fund A", (0.09-0.03)/0.15, 0.40, 1e-12)
add("8.1b", 8, "Sharpe fund B", (0.06-0.03)/0.06, 0.50, 1e-12)
add("8.2a", 8, "mix return w=0.5", 0.5*0.09 + 0.5*0.03, 0.06, 1e-12)
add("8.2b", 8, "mix vol w=0.5", 0.5*0.15, 0.075, 1e-12)
add("8.2c", 8, "mix Sharpe w=0.5", (0.06-0.03)/0.075, 0.40, 1e-12)
add("8.3", 8, "annualised Sharpe from daily 0.1 (iid)", 0.1*math.sqrt(252), 1.59, 5e-3)
# Ch9 volatility drag
add("9.1a", 9, "+50% then -50%", 1.5*0.5 - 1, -0.25, 1e-12)
add("9.1b", 9, "+20% then -20%", 1.2*0.8 - 1, -0.04, 1e-12)
add("9.2a", 9, "g = mu - sigma^2/2, sigma=20%", 0.10 - 0.20**2/2, 0.08, 1e-12)
add("9.2b", 9, "g = mu - sigma^2/2, sigma=40%", 0.10 - 0.40**2/2, 0.02, 1e-12)
# Ch10 correlation
add("10.1", 10, "rho from cov 0.02, vols 20%", 0.02/(0.2*0.2), 0.5, 1e-12)
# 10.2: X uniform on {-1,0,1}, Y = X^2 depends fully on X yet has zero covariance with it
xs = (-1, 0, 1); mx = sum(xs)/3; my = sum(x*x for x in xs)/3
add("10.2", 10, "Cov(X, X^2) for X uniform on {-1,0,1}", sum((x-mx)*(x*x-my) for x in xs)/3, 0.0, 1e-12)
# Ch11 diversification
volp = lambda s, n, rho: s*math.sqrt(1/n + (1-1/n)*rho)
add("11.1", 11, "4 independent assets, 20% vol", volp(0.2, 4, 0.0), 0.10, 1e-12)
add("11.2a", 11, "4 assets, rho=0.25", volp(0.2, 4, 0.25), 0.132, 5e-4)
add("11.2b", 11, "limit N->inf, rho=0.25", 0.2*math.sqrt(0.25), 0.10, 1e-12)
add("11.figa", 11, "10 assets, rho=0.3 (figure)", volp(0.2, 10, 0.3), 0.122, 5e-4)
add("11.figb", 11, "100 assets, rho=0.3 (figure)", volp(0.2, 100, 0.3), 0.111, 5e-4)
add("11.figc", 11, "floor, rho=0.3 (figure)", 0.2*math.sqrt(0.3), 0.110, 5e-4)
# Ch12 minimum-variance weight
s1, s2, rho = 0.10, 0.30, -1.0
w1 = (s2**2 - rho*s1*s2)/(s1**2 + s2**2 - 2*rho*s1*s2)
add("12.1a", 12, "min-variance weight w1", w1, 0.75, 1e-12)
add("12.1b", 12, "resulting portfolio vol", math.sqrt(max(0.0, w1**2*s1**2 + (1-w1)**2*s2**2 + 2*w1*(1-w1)*rho*s1*s2)), 0.0, 1e-9)
# Ch13 beta / CAPM
add("13.1a", 13, "beta = rho*si/sm", 0.6*0.30/0.15, 1.2, 1e-12)
add("13.1b", 13, "expected move for market -4%", 1.2*-0.04, -0.048, 1e-12)
add("13.2", 13, "CAPM expected return", 0.03 + 1.4*(0.08-0.03), 0.10, 1e-12)
# Ch14 Kelly
kelly = lambda p, b: p - (1-p)/b
g = lambda f, p, b: p*math.log(1+b*f) + (1-p)*math.log(1-f)
add("14.1", 14, "Kelly p=0.6, b=1", kelly(0.6, 1), 0.2, 1e-12)
add("14.2a", 14, "Kelly p=0.4, b=2", kelly(0.4, 2), 0.1, 1e-12)
add("14.2b", 14, "log growth at full Kelly", g(0.10, 0.4, 2), 0.0097, 5e-5)
add("14.2c", 14, "log growth at half Kelly", g(0.05, 0.4, 2), 0.0073, 5e-5)
add("14.2d", 14, "half-Kelly growth / full-Kelly growth", g(0.05, 0.4, 2)/g(0.10, 0.4, 2), 0.75, 1e-2)
add("14.fig", 14, "Kelly p=0.55, b=1 (figure)", kelly(0.55, 1), 0.10, 1e-12)
# Ch15 Monte Carlo
add("15.1", 15, "paths for SE 0.4 -> 0.1", 10_000*(0.4/0.1)**2, 160_000, 1e-6)
add("15.fig", 15, "growth rate of 8% mean, 20% vol (figure)", 0.08 - 0.2**2/2, 0.06, 1e-12)
# Ch16 fat tails
p5 = 0.5*math.erfc(5/math.sqrt(2))
add("16.1a", 16, "P(Z < -5)", p5, 2.87e-7, 5e-10)
add("16.1b", 16, "years between 5-sigma drops", 1/(p5*252), 13_800, 60, "years")
# Ch17 VaR / ES
z = N.inv_cdf(0.99)
add("17.1", 17, "1-day 99% parametric VaR", z*0.01*1_000_000, 23_263, 0.5, "$")
add("17.2", 17, "1-day 99% parametric ES", N.pdf(z)/(1-0.99)*0.01*1_000_000, 26_652, 0.5, "$")
add("17.z", 17, "z at 99%", z, 2.3263, 5e-5)
add("17.es_mult", 17, "ES in standard deviations", N.pdf(z)/0.01, 2.67, 5e-3)

out = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "ebook_solutions.json"
out.write_text(json.dumps(dict(
    source="Quantitative Finance From Scratch (QuantFinanceToGo), solutions pp. 23-25 and figure captions",
    note="computed = re-derived here from the book's public formulas; printed = value in the book",
    rows=rows), indent=1))
bad = [r for r in rows if not r["reproduces"]]
print(f"{len(rows)} checks, {len(rows)-len(bad)} reproduce, {len(bad)} do not")
for r in bad:
    print("MISMATCH", r)
for qid in ("8.3", "11.2a", "14.2a", "17.1", "17.2"):
    r = next(x for x in rows if x["id"] == qid)
    print(qid, r["quantity"], "->", round(r["computed"], 6), "printed", r["printed"])
