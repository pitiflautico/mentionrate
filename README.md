# MentionRate

**Do AI assistants recommend your product?** MentionRate asks an assistant the questions your buyers ask, many times, and counts who gets named and which pages the answers rely on.

Site and live example: https://pitiflautico.github.io/mentionrate/

## Latest measurement

<!-- results:start -->
Uptime monitoring tools: 8 buyer questions, each asked 6 times to Claude (sonnet) with web search on 2026-11-14. 48 answers.

| Product | Answers that name it | Share | 95% interval |
|---|---|---|---|
| Better Stack | 45 of 48 | 94% | 83%–98% |
| Uptime Kuma | 44 of 48 | 92% | 80%–97% |
| UptimeRobot | 40 of 48 | 83% | 70%–91% |
| Hyperping | 27 of 48 | 56% | 42%–69% |
| Datadog | 16 of 48 | 33% | 22%–47% |
| Pingdom | 14 of 48 | 29% | 18%–43% |
| Pulsetic | 14 of 48 | 29% | 18%–43% |
| Freshping | 13 of 48 | 27% | 17%–41% |
| StatusCake | 12 of 48 | 25% | 15%–39% |
| Instatus | 11 of 48 | 23% | 13%–37% |
| Statuspage | 11 of 48 | 23% | 13%–37% |
| Cronitor | 9 of 48 | 19% | 10%–32% |
| HetrixTools | 9 of 48 | 19% | 10%–32% |
| Healthchecks.io | 6 of 48 | 12% | 6%–25% |
| Checkly | 5 of 48 | 10% | 5%–22% |
| Oh Dear | 4 of 48 | 8% | 3%–20% |
| Gatus | 3 of 48 | 6% | 2%–17% |
| OpenStatus | 2 of 48 | 4% | 1%–14% |
| Site24x7 | 2 of 48 | 4% | 1%–14% |
| Odown | 1 of 48 | 2% | 0%–11% |
| Uptime.com | 1 of 48 | 2% | 0%–11% |
| Robotalp | 0 of 48 | 0% | 0%–7% |
| StatusGator | 0 of 48 | 0% | 0%–7% |
| Updown.io | 0 of 48 | 0% | 0%–7% |
| Uptimia | 0 of 48 | 0% | 0%–7% |
<!-- results:end -->

Every answer behind these numbers is in [`data/measurements/`](data/measurements/), one JSON object per line, exactly as the assistant returned it.

## Get a report for your product

[Open a request](https://github.com/pitiflautico/mentionrate/issues/new?template=free-report.yml) with your product, its site and two competitors. The sample report is free: 8 buyer questions, one assistant, your product against its category.

| Plan | What you get | Price |
|---|---|---|
| Sample | 8 questions, one assistant, your product against its category | Free |
| Audit | 20 questions, a wider competitor list, the pages worth getting onto | €49 once |
| Tracking | Monthly measurement and one before/after experiment on a change you make | €149 per month |

## How it works

1. A profile lists the product, its competitors (name, aliases, domains) and the buyer questions. See [`perfiles/uptime-monitoring.json`](perfiles/uptime-monitoring.json).
2. Each question is asked several times, because assistants do not answer the same way twice. Every answer is stored unmodified in an append-only SQLite registry; the database rejects updates and deletes.
3. A fixed counting rule decides who was named and who was cited as a source. No model grades the answers.
4. For before/after experiments, the hypothesis, the metric and the success threshold are sealed with a hash before the first answer is collected. The verdict is `SUCCESS`, `FAIL` or `INCONCLUSIVE`, and it comes from counting.

The counting rule was compared against plain substring matching on 31 hand-labelled cases: F1 0.970 against 0.688. One known failure (a common word used as a brand at the start of a sentence) is kept in the benchmark and documented.

## Run it yourself

Python 3.11 or later, no dependencies. The real engine calls the `claude` command-line tool with web search, so you need it installed and signed in.

```bash
python3 -m pytest -q                                              # tests
python3 -m genesis bench                                          # detector comparison
python3 -m genesis audit perfiles/uptime-monitoring.json --samples 6   # 48 real answers, about $1.50 at API prices
python3 -m genesis report MED-0001 --target "Oh Dear"             # HTML report for one product
python3 -m genesis ledger                                         # everything measured so far
```

Command help, code comments and registry labels are in Spanish; reports come out in the language set in the profile (`en` or `es`).

## What this does not tell you

- **Measuring is not improving.** Whether a given change gets a product named more often is an open question. That is what the sealed before/after experiments are for, and a report says so when nothing moved.
- **One assistant.** Only Claude has been measured, through its command-line interface, which can differ from what a person sees in the app.
- **Wide margins.** With 48 answers the 95% intervals are wide, and repeated answers to one question are not independent, so the true intervals are somewhat wider than shown.
- **Only tracked products are counted.** If the assistant recommends a product that is not in the profile, it is missing from the table.
- **The questions shape the result.** One of the eight uptime questions asks for an alternative to UptimeRobot, so its count includes answers that could hardly avoid naming it.
- **Named is not praised.** A product counts as named even when the answer advises against it.
- **The detector benchmark has one author**, the same as the detector.

## Who runs this

An independent developer in Spain. The measurements, the code and the reports are produced by an AI agent (Claude) and reviewed by a person before they are sent.

## License

MIT. See [`LICENSE`](LICENSE).
