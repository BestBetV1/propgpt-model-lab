# PropGPT Model Lab

[Open the public aggregate dashboard](https://bestbetv1.github.io/propgpt-model-lab/).

No login is required. Reports include overall and model performance, grade and
multiplier breakdowns, hypothetical ROI scenarios, and team/player/bet-type
rankings. The source snapshot timestamp is shown on the dashboard.

This repository contains compiled static assets and approved aggregate reports.
It contains no raw prediction ledger, database credentials, or private backend.
The private collection pipeline commits verified aggregate snapshots here. The
Pages workflow must also deploy that commit before visitors see the update.

Aggregate performance and the files in this repository are publicly accessible.

## Delivery checks

The workflow packages and deploys in separate jobs, waits for the exact uploaded
`github-pages` artifact to appear in its run, and then compares every served
HTML, CSS, JavaScript and JSON file with the expected release. A successful
upload or deployment response alone is not treated as verified public delivery.
Visibility and propagation checks retry for a bounded interval; an unavailable
or mismatched file leaves the workflow failed rather than declaring stale data
current. Only the existing approved `site/` directory is uploaded.

Local checks use Python's standard library and do not modify the website:

```sh
python3 -m unittest discover -s tests -v
python3 ops/pages_delivery.py validate --site site
python3 ops/pages_delivery.py verify --site site \
  --url https://bestbetv1.github.io/propgpt-model-lab/ --timeout 0
```

The last command intentionally fails when this checkout differs from the served
release. Run it against the intended deployment commit, not an older checkout.
The JSON success receipt includes the manifest hash, source snapshot time,
export time and number of matched files. Verification does not alter settlement
eligibility or manufacture newer source timestamps.

### November 24, 2026 diagnosis and recovery

Public commit `9831b1c` contains the November 23 23:17:58 UTC analytics snapshot,
with completed event dates through November 22 Eastern. Its Pages run
`45296395742` uploaded artifact `14876477472` successfully at 00:21:01 UTC, but
the deployment lookup reported zero artifacts at 00:21:02 UTC. The artifact
remained retrievable by the read-only API inspection. Run `45065292304` failed
at the same lookup stage. This supports an artifact-visibility race; it does
not establish that collection failed or that a new backfill is required.

At the November 24 inspection, the served manifest still identified the
November 21 18:45:17 UTC snapshot and event dates through November 20 Eastern.
The repair separates upload from deployment, verifies the exact run/artifact
handoff, and checks actual public files after deployment. The REST visibility
check and the deploy action use different artifact API surfaces, so the first
live run must verify the full handoff; local tests cannot prove that service
behavior. A failed artifact gate does not create a Pages deployment.

Recovery requires an authorized merge of this workflow change, which triggers
the existing public Pages workflow. It uses the already-exported snapshot and
does not collect data or dispatch private jobs. Check the newest public commit
before merging so recovery publishes the latest intended aggregate snapshot.
Keep the last successful Pages deployment available if the new run fails; if
needed, revert the workflow change in a follow-up commit without rewriting
forecast or outcome history. Public readback is required before calling the
repair complete.
