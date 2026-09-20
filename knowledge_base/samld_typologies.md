# SAML-D typology catalogue

SAML-D is used only as a calibration and validation source. Its rows are not
joined to the HI-Small detection table. The compact `saml_knowledge` table
contains every labelled laundering row and a deterministic 50,000-row sample
of normal rows.

## Laundering labels

| SAML-D label | Source count | Primary component |
|---|---:|---|
| Structuring | 1,870 | Rule engine |
| Cash_Withdrawal | 1,334 | Rule engine |
| Deposit-Send | 945 | Feature engineering |
| Smurfing | 932 | Rule engine |
| Layered_Fan_In | 656 | Graph tool |
| Layered_Fan_Out | 529 | Graph tool |
| Stacked Bipartite | 506 | Graph tool |
| Behavioural_Change_1 | 394 | Statistical / ML |
| Bipartite | 383 | Graph tool |
| Cycle | 382 | Graph tool |
| Fan_In | 364 | Graph tool / rule engine |
| Gather-Scatter | 354 | ML / graph tool |
| Behavioural_Change_2 | 345 | Statistical / ML |
| Scatter-Gather | 338 | ML / graph tool |
| Single_large | 250 | Rule engine |
| Fan_Out | 237 | Graph tool |
| Over-Invoicing | 54 | Manual-review rule |

These 17 classes total 9,873 labelled laundering rows.

## Normal-behaviour labels

The 11 source labels retained as model and statistical baselines are
`Normal_Small_Fan_Out`, `Normal_Fan_Out`, `Normal_Fan_In`, `Normal_Group`,
`Normal_Cash_Withdrawal`, `Normal_Cash_Deposits`, `Normal_Periodical`,
`Normal_Plus_Mutual`, `Normal_Mutual`, `Normal_Foward`, and
`Normal_single_large`.

The spelling `Normal_Foward` is preserved because it is the exact source label.
