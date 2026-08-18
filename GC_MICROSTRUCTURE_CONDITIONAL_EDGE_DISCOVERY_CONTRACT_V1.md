# GC Microstructure Conditional Edge Discovery Contract V1

The machine-readable contract is `research_manifests/gc_microstructure_conditional_edge_discovery_contract_v01.json`.

Freeze receipt: `cb67d1ba793a80e58d5439be2f3c07ac5fcac1b965440f2035bb48b86efde949`.

London and New York are independent research units. Their decision clock is 08:00 local in `Europe/London` and `America/New_York`, converted with IANA timezone rules. Features use only complete one-second GC buckets before the cutoff. The neutral XAUUSD outcome begins at the frozen 08:01 local reference and ends at 12:00 local; it is not a trade or assumed fill.

The development sample is the second complete Monday–Friday block of every calendar month from August 2021 through December 2024. Six microstructure engineering dates are permanently excluded. Calendar 2025 remains exposed historical forward data, and every 2026 value remains locked.

Only registered standalone microstructure states and explicitly enumerated two-condition interactions may later be tested. Support uses selected-week clustering; uncertainty uses a year-stratified week-cluster bootstrap and permutation test; multiplicity uses Benjamini–Hochberg at q=0.05 separately by session and stage. Zero candidates is acceptable. Development evidence can only create a provisional, unvalidated candidate.

Trade construction, entry/exit logic, execution optimization, and PnL are outside this contract.

Step 5A result: `PASS_STEP_5A_METADATA_READINESS`. No acquisition or research-value access occurred.
