# AI course notes settings

[中文](AI_NOTES.md) · [English](AI_NOTES.en.md)

Open **Workspace → Transcripts → AI course notes and review**:

1. Choose DeepSeek, OpenAI (GPT), Anthropic (Claude), or Google (Gemini) under **Summary API provider**. This is independent of live translation.
2. Choose a **Summary model**, or enter a text model ID supported by that provider and available to your account. Each provider remembers its own model without changing the translation model.
3. Click **Set summary API key**. The provider's existing saved key is shared with translation. Keys stay in Windows Credential Manager, outside preferences and generated notes. A different provider's key is never substituted.
4. Select Chinese or English in the main **Translation target language** control. Notes follow that target; the interface language is independent.
5. After stopping subtitles, click **Generate session AI notes**, or enable **Generate AI notes when the session ends**. Choose an output folder on first use.
6. Use **Organize an existing transcript** for a UTF-8 TXT file without running recognition or live translation again.

The full confirmed source transcript and corresponding translations are processed into detailed parts and a course overview. Missing material and unfinished translations are marked. Course material is treated as data, not instructions to the model or tools.

Provider, model, and language are captured when a task is queued. Summary selectors are locked during processing. Missing keys, access errors, timeouts and rate limits are reported; failed or incomplete output is not saved as successful notes. Original transcripts remain available.

AI notes send the required course text to the selected API and incur separate token charges. Raw audio is not uploaded. Reported tokens and the provider/model appear in the file; billing follows the provider's account statement.

Validation uses Mock HTTP/SSE with all four real protocol adapters, authentication headers, streamed results and usage, plus both UI languages. No personal credentials or paid API calls were used. This does not establish model access for every account, live network availability or summary quality.
