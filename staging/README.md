# `staging/`

Scratch output for in-progress and completed generation jobs. Each `.dcm`
file is written here first — `store_to_pacs` reads from a job's folder and
uploads it into Orthanc; nothing here is served directly.

One subfolder per job, named after the `job_id` `materialize_dataset`,
`modify_dataset`, or `generate_prior_study` returned:

| Prefix | Created by |
|---|---|
| `job-<id>/` | `materialize_dataset` — fresh generation |
| `modjob-<id>/` | `modify_dataset` |
| `priorjob-<id>/` | `generate_prior_study` |

Gitignored (runtime scratch space) — safe to delete freely; nothing here is
authoritative. The authoritative record of what was generated lives in
Orthanc (once stored) and `.pixel-atlas/logs/jobs.log` (regardless of
whether it was ever stored).
