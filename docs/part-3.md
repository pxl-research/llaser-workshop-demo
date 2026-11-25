---
title: Automated red teaming with promptfoo
eyebrow: Part 3 · 11:15 - 11:45
---

**Time: 30 minutes.** Your own prompts show *that* an attack can work. promptfoo shows *how often* attacks work: it sends the same 72 attacks every time and counts how many get through. In this part, you use it to measure the question from 2e: do the guardrails make Mistral Nemo secure?

The steps for a run are in the [README](https://github.com/pxl-research/llaser-workshop-demo#automated-red-teaming-with-promptfoo). A run of the workshop set takes about 7 minutes, and only one run can go at a time.

## Plan your runs

Start the runs in this order:

1. Set the chat model to `mistralai/mistral-nemo` and switch off both prompt defenses. Start a run named `mistral` on the **Auto red team** page right away.
2. When it is done, switch on both prompt defenses, wait until both show **Active**, and start a run named `mistral-guarded`.
3. When it is done, switch both defenses off again, set the chat model to `meta-llama/llama-3.3-70b-instruct`, and start a run named `llama` to compare with.

## While the runs go on, study the results

Try these things while you wait:

- Open **Answers** for a finished run and find an attack that got through. Try that attack by hand in the chat. Does it work there too?
- Look for attacks that resemble your own attacks from part 1. Did promptfoo find tricks that you didn't think of, or the other way around?
- Compare your numbers with your neighbours. Do the same settings give the same result?

Ask yourself what an automated run can measure that you can't, and what your own creativity finds that a fixed attack set misses.
