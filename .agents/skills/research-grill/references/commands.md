# Commands and data format

Requires Python 3.10 or later. The CLI uses the Python standard library, stores state in `.research-grill/records.sqlite3`, and writes transferable snapshots to `.research-grill/exports/`. Keep the database for continuity across weeks. If close saved the record and file export then failed, fix the file access issue and call `export` for the saved version.

Run commands as `python -B <skill>/scripts/grill.py --root <workspace> <command>`. Use `--week YYYY-Www` for week-specific commands. Pass a UTF-8 JSON object with `--input <file>` or `--input -`. Keep payload files with private working data.

## Plans and records

| Command | Fields |
|---|---|
| `init` | `project_id`, `student_id`, `student_name`. Members of a project share a project ID and use distinct participant IDs. IDs are 1–64 ASCII letters, digits, underscores, or hyphens, starting with a letter or digit. Display names can be Unicode. |
| `status` | Optional `history_limit`. Defaults to the last four planned weeks. Shows current and historical goals, records, review state, and latest assessment. |
| `freeze` | Optional `direction` and `language`. Language accepts `en` (default) or `zh-CN`. The `goals` list requires `title`, `deliverable`, `criteria`, and `due` (YYYY-MM-DD). Optional `critical` defaults to false. The script assigns goal IDs. |
| `record` | Required `kind` and `text`. Kinds include `progress`, `evidence`, `blocker`, `extra`, `activity`, `commitment`, `feedback`, and `supplement`. Optional fields are `goal_id`, `source` (`self_report`, `evidence`, or `skill`), `reference`, and `observed_on` (YYYY-MM-DD). Evidence needs a reference. Use a stable locator that recipients are allowed to access. Original evidence files can be shared separately. |

## Review and close

| Command | Fields |
|---|---|
| `ask` | For a goal, pass `kind: goal`, `goal_id`, and `prompt`. After its initial answer, ask a goal-specific follow-up with `kind: followup`, the same `goal_id`, and `prompt`. The first review requires an answered follow-up for every goal before `kind: final` is available. Use the returned final prompt verbatim. |
| `answer` | Pass `question_id` and `text` containing the actual reply. The final answer also requires boolean `no_more`. A false value adds the answer to the supplementary records. |
| `close` | Pass an `assessments` list with one item for each frozen goal. An assessment includes `goal_id`, `status`, `outcome`, `judgment`, `basis`, `response_observation`, and nonempty `refs` (existing Q or R IDs). Optional fields are `student_explanation`, `next_step`, and `delivered_on` (YYYY-MM-DD, for confirmed complete goals). See [assessment guidance](assessment.md). |
| `amend` | Pass `text`. Records an addition and reopens the week. Ask and record a new final answer before closing the next version. |
| `export` | Optional `version`. Exports the latest saved version by default. |

## Import and query

| Command | Fields |
|---|---|
| `import` | Pass `paths`, a list of ZIP paths. Duplicate versions with identical contents reuse the existing record. Conflicting records with the same identity and version are rejected. The reader consumes structured JSON from the archive. |
| `roster` | Pass `project_id` and `students`. Each entry has `student_id`, `student_name`, `from_week`, and optional `through_week`. Optional `due_offset_days` defaults to 6 (Sunday). A value of 7 means the following Monday. The supplied roster replaces the project's roster. |
| `summary` | Pass `project_id` and optional `as_of` (local date by default). The latest version closed by that date is used, based on the participant's clock. A report due that day is `pending` if unavailable and becomes `missing` the following day. `closed_on_time` is based on the first close date. Personal comparisons use up to four preceding reported weeks. Skill activity days count dated skill events once per day. Supplementary reported days are listed separately. |
| `view` | Pass `project_id`, `student_id`, and optional `version`. Returns the original report data. |

New reports record their selected language. Older Chinese reports without a language field still work with this release. Use this release on both sides when exchanging English reports. Language changes affect built-in prompts and report headings. The source text written by participants stays in its original language.
