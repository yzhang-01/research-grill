# Research Grill

[简体中文](README.zh-CN.md)

Research Grill is a Codex skill for keeping yourself accountable to your own research plan. Set weekly goals and define what completion looks like. Freeze the plan once you confirm it. Use a short, evidence-based self-review to see what moved forward, what stalled, and what you will try next.

## Install

1. Install Codex and Python 3.10 or later. Confirm that `python --version` works in your terminal.
2. Open this folder as a Codex project. To add the skill to another project, copy the entire `.agents/skills/research-grill/` directory to that project's `.agents/skills/` directory.
3. In a Codex chat for the project, type `$` and select `research-grill`. If it does not appear, reopen the project and start a new chat.

## Your first research review

1. **Set a goal.** Try `$research-grill Help me plan this week. I want to read one paper and explain a key result with a page or figure citation. Show me a draft first.` Confirm your project and participant IDs on first use. Review the deliverable, criteria, and due date, then confirm the plan. Codex freezes it once you agree.
2. **Record what happened.** Try `$research-grill Record that I tested the baseline. Here is the run and what I learned: …` Add versioned links, paper passages, or run IDs when available. Record blockers or changes in direction during the week.
3. **Review the week.** Try `$research-grill Start my weekly research review.` Each goal gets a targeted follow-up. Expect questions about what stopped you, what you tried, or what evidence supports your result. You can attach an artifact for Codex to examine. When asked if you have anything else to add, say you are done when ready. Codex returns a ZIP with the report, verbatim answers, and an evidence index under `.research-grill/exports/`.
4. **Archive or share.** Keep the package for personal review or share it for team coordination. For material others need to verify, provide links recipients can access or share the relevant files separately.

Chat in your preferred language. The built-in final question and report template are available in English and Simplified Chinese. Participant records and answers retain their original wording.

## Team coordination

Place received ZIPs in a project with Research Grill installed and ask:

> `$research-grill Import these weekly reports. Summarize progress against each person's frozen goals and cite the evidence or original answers.`

Use a shared project ID and a different participant ID for each person. A roster and a review date help coordinate weekly reporting. Packages can be queried by participant, week, and version.

## A direction for peer review

We encourage journals and conferences to request manuscript-related Research Grill records as supplementary material and invite reviewers to consult them when evaluating a submission. A record can show the hypotheses, dead ends, negative results, repeated attempts, and decisions behind the final figures. It gives reviewers evidence of where researchers invested effort and how they evaluated competing explanations.

Authors can document where AI contributed to code, analysis, writing, or figures and what they did to verify the outputs. The record helps reviewers examine the provenance of the findings, the evidence behind the claims, and the judgments the authors take responsibility for.

See the [MIT License](LICENSE), [open-source preparation](OPEN_SOURCE.md), and [acknowledgments](ACKNOWLEDGMENTS.md).
