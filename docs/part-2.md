---
title: Defend
eyebrow: Part 2 · 10:45 - 11:15
---

**Time: 30 minutes.** All the defenses are on the **Controls** page. They apply at once and stay changed until the app restarts. A defense is only working when its status shows **Active**.

Change **one** thing at a time, and then run the same attacks again: prompts 4, 5 and 10 from part 1, plus your own best attacks. That way, you know which change made the difference.

## 2a. The system prompt (5 minutes)

The system prompt contains a confidentiality rule after the documents (`{context}`).

1. Remove the confidentiality rule, apply it, and ask prompts 2 and 3 again.
2. Restore the default. Then move the rule *before* `{context}` and attack again.
3. *Optional:* write your own, stricter rule, and test it against your best attack.

Ask yourself how much a rule in plain language can really guarantee.

## 2b. The NLP defense (5 minutes)

The NLP defense is a small classifier model on your laptop. It checks every question before the chat model sees it.

1. Restore the default system prompt. Switch on the NLP defense, wait for **Active**, and run your attacks again.
2. Ask prompt 9 from part 1. It is a harmless question that sounds like an attack. Is it blocked?
3. *Optional:* move the threshold slider and try again. Lower means more blocked attacks, but also more blocked harmless questions.

When a defense blocks a question, the chat model never sees it. The question waits for review as an alert on the **Alerts** page, and while it waits, the chat accepts no new questions. **Accept** sends the question to the chat model and shows the answer. **Deny** drops only that question, and you can continue. **New chat** starts over without waiting. Try both buttons once: you are now the human in the loop.

## 2c. The LLM defense (5 minutes)

The LLM defense asks a second language model whether your question is safe or malicious.

1. Switch off the NLP defense, switch on the LLM defense, and run your attacks again.
2. Compare it with the NLP defense. Which attacks does each one stop, and how much slower is each answer?
3. Run prompt 10 again, with both turns in a new chat. Then ask only turn 2 in another new chat.

Ask yourself what a defense can see when it checks each question on its own.

## 2d. Safe answer rendering (5 minutes, demo)

The previous defenses check your *question*. Safe answer rendering protects against a dangerous *answer*: an image in an answer can send data to another server without anyone clicking.

The host shows this attack and its defense on the projector. *Optional:* if you have Python 3, follow the image-leak steps in the [README](https://github.com/pxl-research/llaser-workshop-demo#answers-are-untrusted-output-the-image-leak) yourself.

Ask yourself which of the other defenses would have stopped this attack.

## 2e. Can guardrails make a weak European model secure? (10 minutes)

The chat model is one of the most important factors in which attacks get through. Our earlier research showed large differences between models. `mistralai/mistral-nemo`, the default model, from the French company Mistral AI, was the weakest model in our tests (see [Models to compare](https://github.com/pxl-research/llaser-workshop-demo#models-to-compare)). For organisations in Europe, a European model can be an important choice. So the question is whether extra guardrails can make it secure anyway, and how it compares with models that have stronger built-in guardrails.

1. Switch off both prompt defenses and keep the default system prompt and the default model `mistralai/mistral-nemo`.
2. Run prompts 3, 4, 5 and 10 and your best attack.
3. Add the guardrails one at a time: first the NLP defense, then the LLM defense as well. Run the same attacks after each step.
4. Keep both guardrails on. Switch the chat model to `meta-llama/llama-3.3-70b-instruct`, and then to `openai/gpt-6-luna`. Both have stronger built-in guardrails. Run the same attacks with each model.
5. *Optional:* Mistral AI has more models in the model list. Try a larger one with the same attacks.

Write down which attacks still get through Mistral Nemo with all guardrails on. Is "Mistral Nemo with guardrails" now as safe as Llama 3.3 70B or GPT-6 Luna with the same guardrails?

The guardrails come from somewhere too. The NLP defense is a fine-tuned DistilBERT model that runs on your laptop. The LLM defense uses a Qwen model, from the Chinese company Alibaba. It runs on the PXL DGX Spark in Belgium when the Spark is available, and otherwise through OpenRouter. Ask yourself what a completely European setup would need.
