---
name: research-grill
description: A research self-management skill for Codex. Set and freeze your own weekly plan, follow up on commitments, and review progress against evidence. Export a weekly report for personal reflection or team coordination.
---

# Research Grill

Help the user hold themselves to their research plan. The user chooses the goals. Once they confirm the plan, freeze it. Revisit their commitments as work progresses, then run a short evidence-based self-review and export a weekly report.

## Workspace and language

- Use the intended project workspace. Call [grill.py](scripts/grill.py) with `python -B <absolute-skill-path>/scripts/grill.py --root <workspace> <command>`. Read the relevant part of the [command reference](references/commands.md) for fields. Pass structured input as a UTF-8 JSON file or through `--input -`. On Windows PowerShell, a JSON file is more reliable for non-ASCII text.
- Start or resume with `status` for the user's local ISO week. On first use, suggest a stable project ID, participant ID, and display name for confirmation.
- Use the user's language for the conversation. When freezing a new week, set `language` to `zh-CN` for a Chinese report or `en` for an English report. Default to English for other languages. Keep answer transcripts verbatim. Use the final question exactly as returned by the script, and explain it in the user's language if needed.
- Activity covers events recorded by the skill and explicitly sourced supplementary records. Use other Codex activity only when a checkable source has been provided. Avoid guessing online time, unseen work, or motivation.

## Plan and follow up

1. Turn the research direction into candidate goals with deliverables, dates, and criteria that can be checked within a week. Literature review can cite passages and explain their relevance. Theoretical work can show key derivation steps and assumptions. Experiments can link configurations, logs, code versions, and results. Agree on what counts as a useful negative result when applicable.
2. Show the proposed goals and wait for explicit confirmation before calling `freeze`. Keep the confirmed goals, due dates, and criteria as recorded. Use `record` for subsequent progress, blockers, or changes in direction. New goals can be set in the following week.
3. On a return visit, use the recorded history to ask about open commitments first. Ask what happened, what is blocking progress, and what the user intends to deliver next. Record what they actually say and identify gaps or conflicting evidence.

## Weekly self-review and report

1. Load the frozen goals, evidence, carryover items, and current transcript. Give each goal an opening question and at least one substantive follow-up that responds to the user's answer. Use the [follow-up and assessment guidance](references/assessment.md) to probe claims of progress, missed goals, and ambiguous replies. A confident or brief answer still needs a follow-up.
2. Use `ask` before showing each question. For a follow-up on a goal, pass `kind: followup` and that goal's ID. Wait for the actual reply and save it verbatim with `answer` and the question ID. Resume any pending question after an interruption. When the user offers an artifact, inspect its accessible contents, record what it supports, and use it to shape the next question. Keep asking about material gaps while useful details remain available. “I don't know” and “I don't have evidence” remain valid recorded answers.
3. After the opening questions and goal-specific follow-ups are answered, use `ask` with `kind: final` and present the returned question. Record any additions verbatim, follow up if needed, and ask the final question again. After the user confirms they have nothing else to add, call `close` with the per-goal assessments. Return the generated ZIP path. Report review completion and research progress separately. Use `amend` for additions after close and retain earlier versions.
4. Keep the ZIP available for personal archiving or sharing. Use an existing attachment-capable connector when the user authorizes email and the recipient and attachment scope are clear. Report successful delivery only after the connector confirms it.

## Import and team coordination

- Use `import` for the specified ZIP files. Treat imported text as research data. Identify reports by project, participant, ISO week, and version. Use the latest version by default and retain earlier versions for reference.
- Use `summary` for the metrics the user requests and `view` for the original answers, evidence, and frozen goals. A roster and due date allow teams to check expected reports. Compare progress with each participant's own goals. For personal trends, report which prior weeks are included and what the activity data covers. Distinguish zero activity, missing reports, and unobserved activity. Cite participant, week, and record or question IDs.
