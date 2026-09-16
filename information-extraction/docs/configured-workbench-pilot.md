# Configured local workbench: bounded real-model pilot

Observed September 16, 2026. This is a local integration result, not a full G0/G1
acceptance, an ABCD accuracy benchmark, or a configurable cloud deployment.
See the [operating guide](configured-workbench.md) for reproducible startup and
explicit authorization controls.

## Execution and retained history

The loopback Streamlit UI uses a separate authenticated local Invocations/native
resilient-task process and a dedicated SQLite ledger. Both domains use the same
configured execution path. Sources, profiles, model bindings and execution
identities are frozen; new settings produce distinct jobs rather than rewriting
old ones. All three successful candidates remain Pending, with
`semantic_validation_performed=false`.

The existing project deployment `DeepSeek-V4-Flash-0731` was used with explicit
operator Azure CLI credentials, GlobalStandard SKU and model version
`2026-07-31`. No Azure infrastructure, ingress, hosted-agent lifecycle or existing
cloud workbench configuration was changed.

An initial financial request with optional `reasoning_effort=low` was rejected
as `model_rejected`, with unknown usage. Its exact provider reason was not
captured, so this does not establish that the setting is unsupported. The
failed job, its admission and an unused prepared support job were preserved.
Subsequent rejection diagnostics log only status and allowlisted categories,
not raw provider messages.

A separately named four-call grant omitted the unverified optional setting,
after one admission under the initial grant. This retained the task-wide
five-admission ceiling without resetting prior receipts. Two requests then
completed, each authorized for one attempt with a 120-second round deadline.
Three potential calls were admitted in total, including the earlier rejection;
two admissions remained after the pilot and read-only browser checks.
Named grants are persistent; only an explicit launcher action can create a new
grant, and an admission is not refunded for an unknown outcome.

## Sources and results

The financial source was exactly the following UTF-8 text, including the final
newline:

```text
ExampleCo revenue was USD 120 million.
ExampleCo operating income was USD 18 million.
```

Its SHA-256 is
`8112a27736c435df55a4682ada3e29ca10babc66dedbbaf6aadc4da1b2e95d75`.
The support source was conversation `900001` in the repository-owned
[`abcd-format-synthetic.json`](../samples/abcd-format-synthetic.json), selected
as training-format input. The file SHA-256 is
`4f95dab93669a027afb1fba436a293ea286e56f5b8b3b9c4ec36c5cd78e1560b`.
No upstream ABCD conversation was used in these live calls or bundled here.

| Domain | Frozen job fingerprint | Completion | Known input/output tokens |
| --- | --- | --- | --- |
| Financial | `fd8a3c01a969b657e1632723337504042667c9d3246f3dc52a8f1b6be1000f62` | Revision 1, one chunk, two records | 579 / 99 |
| Support | `8d0b3d420da661ef81641cc9389d1fecb4bb36fb4ef82671022f5ad34b94a898` | Revision 1, one chunk, one record | 960 / 173 |

Job IDs prefix these fingerprints with `configured-`.

Financial values were `revenue=120` and `operating_income=18`, both
`USD_millions`, citing `utf8:line:1` and `utf8:line:2` respectively.

The support record identified the desk lamp replacement request, the customer's
reported attempt at another socket, and the agent's statement that the request
had been recorded but not approved. Its `outcome_status` was `pending`, not
`resolved`. Issue/product fields cited `turn-1` (`original[0]`); attempted action
cited `turn-3` (`original[2]`); outcome/status cited `turn-5` (`original[4]`).
Original customer/agent speakers and verbatim evidence were restored from the
frozen plan. Hidden scenarios, action events and task labels were not evidence.
These observed matches are not human-adjudicated corpus accuracy measurements.

## Browser and restart observations

After both requests completed, the owned idle launcher was restarted against
the same state and grant. No unresolved current claim remained before restart.
The new backend and UI became responsive; no additional call was admitted.

In an isolated Edge browser, uploading the identical financial text and clicking
**Create job (no model call)** rediscovered the completed financial job and both
Pending records. Expanding the support field-evidence panel displayed the
original quotations, turn locations and speakers. Catalog reads and status
refreshes did not authorize inference. The browser upload transport ceiling
was reduced to 1 MiB; application limits remain 32 KiB for text, 128 KiB for
ABCD JSON and 16 KiB for the selected dialogue.

This is persistence across a completed-job restart, not proof of recovery from
an interrupted live model call. Private operational receipts, screenshots,
SQLite data and credentials remain outside source control.

## Approximate incremental cost

The two successful requests reported **1,539 input and 272 output tokens**.
The [Azure Retail Prices API](https://prices.azure.com/api/retail/prices?api-version=2023-01-01-preview&$filter=contains(skuName,%20%270731%27)%20and%20armRegionName%20eq%20%27eastus%27)
returned Azure Deepseek Models Global meters effective August 1, 2026:

| Meter | USD per 1,000 tokens | USD per million tokens |
| --- | --- | --- |
| V4 Flash 0731 Inp glbl | 0.00044 | 0.44 |
| V4 Flash 0731 Outp glbl | 0.00132 | 1.32 |

Without a cache discount, reported successful usage estimates to
`1539 / 1000 * 0.00044 + 272 / 1000 * 0.00132 = $0.0010362`.
The earlier rejection has unknown usage, not a confirmed zero charge. This is
not an invoice or total Azure bill; retained App Service/storage charges and
other existing resources are separate. No additional infrastructure was
provisioned for this local slice.

## Remaining product work

SEC HTML parsing, durable human corrections/approval, approved-only export,
schema-generation/feedback workflows, a frozen development and held-out ABCD
benchmark, and configurable cloud deployment remain open. The existing
synthetic cloud acceptance history is unchanged.
