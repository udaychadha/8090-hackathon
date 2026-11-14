# WO-12 committee snapshot audit

Approved source PDFs were downloaded, hashed and retained under gitignored `data/source/committee/`. No strategies or models were run.

**Qualifying purchases: 0. Date range: none to none.**
Required result note: **short sample: not a verdict**. VERIFIED eligibility: **False**.

Input rows: 30366. Purchases on an approved snapshot day for the same chamber: 15; current daily-universe overlap: 12.

## Approved sources and exact coverage

| Source | Membership coverage | Extracted rows | SHA-256 |
|---|---|---:|---|
| [house-2019-12-02](https://historycms.house.gov/WorkArea/DownloadAsset.aspx?id=25769816736) | 2019-12-02 only | 205 | `7bd4418f68fdbf802206ec16bdc4224993ce264d8b42e1a8378606bf67c5fbca` |
| [house-2021-02-01](https://historycms.house.gov/WorkArea/DownloadAsset.aspx?id=25769822882) | 2021-02-01 only | 170 | `a5989d5c6a8ee6141219a808c0f461f5b57750d506ea423c288acecac07a4027` |
| [house-2024-12-16](https://historycms.house.gov/WorkArea/DownloadAsset.aspx?id=36507226670) | 2024-12-16 only | 189 | `06bbc63405271a0ff9578424028b355c065eac70581d62576479524490cf33cd` |
| [senate-2019-03-18](https://www.govinfo.gov/content/pkg/GPO-CPUB-116spub2/pdf/GPO-CPUB-116spub2.pdf) | 2019-03-18 only | 121 | `681e60d5d851d48160aeccec93a512383d1c45843e275c1f8459049f1d0ef527` |
| [senate-2021-06-08](https://www.govinfo.gov/content/pkg/GPO-CPUB-117spub5/pdf/GPO-CPUB-117spub5.pdf) | 2021-06-08 only | 120 | `31e7863e0274f0e6f886a2e546b14b54423eb537a3cc5eb3e3d9c46a1bdc68c4` |
| [senate-2023-03-30](https://www.govinfo.gov/content/pkg/GPO-CPUB-118spub3/pdf/GPO-CPUB-118spub3.pdf) | 2023-03-30 only | 115 | `79b611512411dc648cae7a48dabcb9c2776e049dbef9752b3e9016737ecfad0c` |
| [senate-2025-06-12](https://www.govinfo.gov/content/pkg/GPO-CPUB-119spub4/pdf/GPO-CPUB-119spub4.pdf) | 2025-06-12 only | 122 | `38f827718227c32f2f503caa8beac81c482b736c60662c04ffd1a54896252b19` |

## Matching and fixed mapping

Exact normalized name plus chamber and exact snapshot/transaction date; punctuation/case/accents normalized; no aliases, middle-name deletion, fuzzy matching or crosswalk used.

No aliases were applied. Normalized rows retain original member spelling, source line, source PDF page, hash, and start=end=snapshot date.

- Armed Services: GICS Sub-Industry = Aerospace & Defense.
- Energy and Commerce: GICS Sector = Energy, Health Care.
- Financial Services: GICS Sector = Financials.
- Banking, Housing, and Urban Affairs: GICS Sector = Financials.
- Commerce, Science, and Transportation: GICS Sector = Communication Services, Information Technology.
- Energy and Natural Resources: GICS Sector = Energy.
- Health, Education, Labor, and Pensions: GICS Sector = Health Care.
- Energy and Commerce / Health: GICS Sector = Health Care.

## Point-date purchase disposition

| Member | Chamber | Transaction date | Symbol | Sector | Matched relevant committees | Disposition |
|---|---|---|---|---|---|---|
| Alan S. Lowenthal | house | 2021-02-01 | BSX | Health Care | none | no_strict_name_match_on_relevant_rosters |
| Alan S. Lowenthal | house | 2021-02-01 | BSX | Health Care | none | no_strict_name_match_on_relevant_rosters |
| Anthony E. Gonzalez | house | 2021-02-01 | CHTR | Communication Services | none | no_strict_name_match_on_relevant_rosters |
| Kathy Castor | house | 2021-02-01 | BRK.B | Financials | Energy and Commerce | gics_mapping_does_not_match |
| Virginia Foxx | house | 2021-02-01 | MO | Consumer Staples | none | no_strict_name_match_on_relevant_rosters |
| Marie Newman | house | 2021-02-01 | CHWY | outside universe | none | not_in_current_daily_universe |
| Marie Newman | house | 2021-02-01 | KR | Consumer Staples | none | no_strict_name_match_on_relevant_rosters |
| Marie Newman | house | 2021-02-01 | PFE | Health Care | none | no_strict_name_match_on_relevant_rosters |
| Marie Newman | house | 2021-02-01 | VRM | outside universe | none | not_in_current_daily_universe |
| Marie Newman | house | 2021-02-01 | VRM | outside universe | none | not_in_current_daily_universe |
| William F Hagerty | senate | 2021-06-08 | BA | Industrials | none | no_strict_name_match_on_relevant_rosters |
| Lloyd Doggett | house | 2024-12-16 | KO | Consumer Staples | none | no_strict_name_match_on_relevant_rosters |
| Jonathan Jackson | house | 2024-12-16 | ORLY | Consumer Discretionary | none | no_strict_name_match_on_relevant_rosters |
| Thomas H. Kean Jr | house | 2024-12-16 | ABT | Health Care | none | no_strict_name_match_on_relevant_rosters |
| Thomas H. Kean Jr | house | 2024-12-16 | PLD | Real Estate | none | no_strict_name_match_on_relevant_rosters |

## Public availability

No roster public-release timestamp established. Do not treat cover, metadata or production date as public availability. Historical usable rows are zero until evidence or owner decision resolves this; no inferred timestamp was created.

If an independently evidenced publication time becomes available, derived event availability must be no earlier than BOTH the disclosure-based next market open and roster publication availability. A snapshot date establishes the membership observation, not when that observation was public.

## Limitations

- unverified source
- Current daily universe carries survivorship bias.
- GICS sector/sub-industry classifications come from the current static data/sp500.csv, not historical classifications.
- Seven snapshot days only; no inference over congressional terms or between snapshots.
- The fixed owner mapping assigns both Energy and Health Care to full Energy and Commerce membership; no extra Health-subcommittee condition is imposed.
- Strict matching can exclude genuine aliases; unmatched rows remain excluded and are retained for review.
- PDF metadata and production timestamps do not establish public availability.
