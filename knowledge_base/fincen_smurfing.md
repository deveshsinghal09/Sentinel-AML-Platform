# FinCEN Guidance: Smurfing

## Definition
Smurfing is a form of structuring that uses a network of individuals ("smurfs") who each make
sub-threshold deposits or transfers into separate accounts. The proceeds are then consolidated
into a primary account controlled by the orchestrator. It is essentially distributed structuring.

## Regulatory Basis
- **FinCEN Advisory FIN-2014-A005**: Highlights the use of third-party networks to facilitate
  structured deposits and wire transfers.
- **FATF Recommendation 20**: Same SAR obligation as structuring.
- **Bank Secrecy Act (BSA)**: Any person who causes another to structure is equally liable.

## Key Indicators
1. Multiple distinct accounts (≥ 5) sending sub-threshold amounts to a single recipient within days.
2. The sending accounts have no prior relationship or apparent business connection.
3. Sending accounts are newly opened (< 90 days) with little other activity.
4. Geographic dispersion: senders in different regions/countries while recipient is centralised.
5. High fan-in ratio: one account receiving from many sources simultaneously.

## Detection Logic (Used by Rule Engine + Graph Tool)
- **Fan-in threshold**: ≥ 5 unique source accounts → same destination within 7 days
- **Per-source amount**: Each source sends < $10,000
- **Aggregate amount**: Total received by destination ≥ $25,000 in the window
- **Graph signal**: High in-degree centrality node with low out-degree = potential smurf aggregator

## Difference from Pure Structuring
| Feature | Structuring | Smurfing |
|---|---|---|
| Who transacts | Single individual | Multiple individuals |
| Detection difficulty | Medium | High |
| Graph signal | Weak | Strong (hub node) |
| Rule signal | Strong | Moderate |

## SAR Filing Guidance
Always file a SAR. Include all known smurf account identifiers in the narrative.
Reference: FinCEN SAR Form 111, Field 68 (Coordinated Structuring)
