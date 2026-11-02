# Shipping Document & BOL Parser

Turns unformatted shipping text (bills of lading, carrier confirmation emails, pasted PDF text) into validated, standardized JSON, and refuses to pass along anything incomplete.

**Stack:** Python 3.10+ (standard library only), regular expressions, pytest. Optional LLM fallback via the Anthropic Messages API.

## The problem

Shipping documents rarely look the same twice. One carrier writes `SHIP TO`, another writes `consignee:`. Weights show up in lbs or kg. Dates come as `10/14/2026` or `Oct 14, 2026`. Manually keying these into an ERP is slow, and a single wrong weight or missing ZIP causes billing disputes and failed deliveries.

## How it works

```
raw .txt ──► extract (rules) ──► validate ──► accepted/*.json
                   │                 │
                   │ (missing fields │ errors ──► rejected/*.json + errors.log
                   │  and --llm)     │
                   └──► LLM fallback ┘  (fills gaps only, re-validated)
```

1. **Extract**: Regex rules pull the BOL number, ship date, carrier/SCAC, PO, ship-from and ship-to addresses, line items (product code, qty, weight), total weight, hazmat flag, and special instructions. Label aliases and units are normalized (kg → lbs, any date → ISO).
2. **Validate**: Blocking errors include missing required fields, an incomplete ship-to address, non-positive quantity or weight, and line-item weights that don't match the stated total (1% tolerance). Non-blocking warnings cover missing ship-from, no total to cross-check, or no hazmat flag.
3. **Route**: Clean records go to `accepted/`, failures go to `rejected/`, and every problem is written to `errors.log` for a human to review.

### Optional AI fallback

If the rules miss required fields and you pass `--llm` with `ANTHROPIC_API_KEY` set, the raw text is sent to an LLM that returns the same JSON shape. The fallback **only fills gaps**. It never overwrites a rule-extracted value, and its output goes through the exact same validation. Failures, like network errors or bad JSON, are logged and never crash the batch. Tests run fully offline and don't call the API.

## Run it

```bash
python -m bol_parser samples/ --out output/
```

```
[OK  ] bol_complete.txt
[FAIL] bol_incomplete.txt  (3 error(s))
[OK  ] shipping_confirmation_email.txt

2 accepted, 1 rejected. Details in output/errors.log
```

`errors.log` for the rejected file:

```
ERROR bol_incomplete.txt: ship_to missing zip
ERROR bol_incomplete.txt: line 2 (PC-30140): quantity must be positive
ERROR bol_incomplete.txt: weight mismatch: line items sum to 3150.0 lbs, document states 4000.0 lbs
WARNING bol_incomplete.txt: ship_from not found
WARNING bol_incomplete.txt: hazmat flag not stated
```

The exit code is `1` when any document is rejected, so the command can gate a scheduled job or an n8n/Power Automate step.

## Samples

| File | What it exercises |
|---|---|
| `bol_complete.txt` | Standard BOL layout, passes cleanly |
| `shipping_confirmation_email.txt` | Email body, lowercase labels, `shipper`/`consignee` aliases, kg weights, spelled-out date, hazmat |
| `bol_incomplete.txt` | Missing ZIP, zero quantity, weight mismatch, so it's rejected |

## Tests

```bash
pip install pytest
python -m pytest -q
```

## Layout

```
bol_parser/
  extract.py        rule-based field extraction and normalization
  validate.py       blocking errors vs. warnings
  llm_fallback.py   optional gap-filling with an LLM (stdlib HTTP only)
  __main__.py       batch CLI
samples/            three example documents
tests/              pytest suite
```
