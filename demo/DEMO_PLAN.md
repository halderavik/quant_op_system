# Quant OS live demo runbook

**Story for the audience:** one workspace takes a study from a client brief to a client-ready PowerPoint. Specialist agents do each job, every number is computed rather than written by a model, and the researcher can edit at every step.

**Running time:** about 53 minutes plus Q&A. Data cleaning (Act 4) is skipped for synthetic data, which brings it to about 48 minutes. The core path (Acts 1, 3, 5, 6 and 8) takes 30 minutes if you need to cut. Act 8b (connectors) adds 3 minutes and is the first thing to drop after that.

**Study used throughout:** the BrewCo home coffee machine brand health study. Its brief is in [brief.md](brief.md).

---

## 1. How the demo is set up

Some steps take a few minutes, so run the demo across two projects:

| Project | What it is | Used for |
|---|---|---|
| **Demo – Live** | Empty at the start. You type every prompt in front of the audience. | Acts 1 to 7 |
| **Demo – Backup** | The full study run end to end the day before, with the same prompts. | Showing finished outputs while a live task runs, and as the fallback if a step fails |

**Rule of thumb:**
- **Short steps** (under a minute): wait on screen and narrate the stage messages in the chat.
- **Long steps:** start the step, switch to **Demo – Backup**, show the finished version of the same output, then switch back.

**How long each step usually takes.** "Median" and "Slowest seen" come from your past runs; "Rehearsal" is the Demo – Backup build of the 13th.

| Step | Median | Slowest seen | Rehearsal | How to handle it |
|---|---|---|---|---|
| Brief to questionnaire | 1.6 min | 5.7 min | 5.5 min | Live; narrate, and go to Backup at 3 min |
| Questionnaire edit by chat | 0.9 min | 1.0 min | 2.0 min | Live |
| Decipher programming | under 1 min | – | 4 s | Live |
| Prolific price quote | under 10 s | – | 10 s | Live, **quote only** |
| Synthetic respondents (600) | 1.8 min | 2.0 min | 1.8 min | Live |
| Fraud and quality check | 2.3 min | 2.8 min | 16 s | **Skipped** for synthetic data |
| Single crosstab | under 10 s | – | 10 s | Live |
| Build the tab spec | under 10 s | 4.4 min | 1.7 min | Live |
| Run the full tab spec | 0.5 min | **21.5 min** | 33 s | **Show it from Backup** |
| Analysis (driver, segmentation, tests) | 0.3 min | 11 min | 16–64 s | Live; switch to Backup if past 2 min |
| AutoCoder on an open end | 1.8 min | – | 16 s | Live |
| Report plan refresh | under 1 min | 1.3 min | 16 s | Live |
| Generate the report deck | 5.4 min | 6.7 min | 6–9 min | Start it live, show Backup's deck while it runs |
| Connector request (plan and approval card) | – | – | 16 s | Live |
| Approve a connector step | – | – | 2 s | Live |

---

## 2. Preparation

### The day before

1. **Demo – Backup is already built.** It was made on 13 November with every prompt in this runbook. It holds:
   - questionnaire v2 and the Decipher survey (selfserve/563/261143);
   - the Prolific quote (not published) and 600 synthetic respondents;
   - the cleaning recommendation and the full tab book (110 tables);
   - the key driver, segmentation and Kruskal-Wallis analyses;
   - the AutoCoder codeframe for Q27;
   - the report: 66 slides, 53 of them with native charts or tables.
   
   Open it once before the demo to check it loads.
2. **Know the question numbers.** The questionnaire is generated fresh each time, so the numbers in **Demo – Live** may differ from Backup's. All the prompts below use plain words: a resolver maps them to the right columns by their labels, so they work either way. In Backup the numbers are:

   | Number | Question |
   |---|---|
   | **Q18** | BrewCo likelihood to recommend (0–10) |
   | **Q10r1–Q10r10** | BrewCo image grid |
   | **Q27** | reason for the recommendation score |
   | **Q28** | why BrewCo wasn't considered |
   | **S6** | gender |
   | **S5** | region |
   | **S1** | age |
   
   If a plain-language prompt ever asks which column you mean, answer with the number ("Q18 by S6").
3. **Check the keys in `backend/.env`.** You need the OpenAI and Anthropic keys, plus Decipher (for Act 2) and Prolific (for Act 3). Without the Decipher key, programming still produces the XML and the preview, but it doesn't upload. Never show the `.env` file on screen.
4. **Check the AutoCoder is installed.** If you ran `uv sync` since installing it, reinstall it (see the README).

### One hour before

1. **Start the backend** in its own PowerShell terminal. Don't run `uv sync` on demo day; it uninstalls the AutoCoder.

```powershell
cd backend
uv run uvicorn app.main:app --port 8000
```

2. **Start the frontend** in a second terminal:

```powershell
cd frontend
npm run dev
```

3. **Set up the screen.**
   - Open http://localhost:5173 at about 110% browser zoom.
   - Choose the light or dark theme with the theme button in the projects rail.
   - Close the other projects in the rail if possible, or make sure the two demo projects are at the top.
4. **Have these ready to hand:**
   - [brief.md](brief.md), open to copy.
   - PowerPoint, to open the final deck.
   - Excel, for the tab book.
   - Word, for the questionnaire.
5. **Start the connectors stand-in** (for Act 8b) in a third terminal. It is a local server with Drive-like and Slack-like tools. It holds the BrewCo brief and a Reports folder, and keeps everything in memory, so each restart starts clean.

```powershell
cd backend
.venv\Scripts\python.exe -m tests.mock_mcp_server --port 8765 --token demo-token
```

   Then open **Connectors** (bottom left of the projects rail):
   - If **Stand-in workspace (Drive + Slack)** is listed under Custom MCP servers, click **Test**. It should show **Connected** and **Tools · 5**.
   - If it isn't listed, add it: name `Stand-in workspace (Drive + Slack)`, URL `http://127.0.0.1:8765/mcp`, token `demo-token`, then **Add and connect**.
   - Leave the Google Drive, Slack and Microsoft 365 cards as they are. They show **Needs admin setup**, which you'll point to in Act 8b.
6. **Warm-up:** in Demo – Backup, send one short message (for example `Run a crosstab of Q18 by S6`) so the first model call isn't the slow one in front of the audience.
7. **Create an empty project named `Demo – Live`.**

### Do not do these live

- **Never confirm the Prolific purchase or publish.** Pricing is free; confirming spends real money and recruits real people. Stop at the quote.
- **Don't send `launch it on Decipher` more than once.** Each send creates or updates a real survey in the company Decipher account.
- **Don't run the full tab spec live.** It can take up to 20 minutes.
- **Don't call the stand-in "our Google Drive".** It's a local stand-in until an admin sets up the real Drive and Slack connectors. Say so in one line (see Act 8b).

---

## 3. The demo, act by act

Each act lists what to **say**, what to **type** (exact prompts), what to **show**, and the **fallback**.

### Act 0 – Opening (2 min)

**Say:**
> "Quant OS is a research workspace where specialist agents do the work a quant team does. That's questionnaire writing, survey programming, sampling, data cleaning, tables, advanced analytics, open-end coding and the client deck. A router agent reads each request and hands it to the right specialist. Every number you'll see is computed in code; the language models plan and write, but never invent figures."

**Show:**
- **Layout:** the projects rail on the left, the chat in the middle, and the workspace on the right with its **Outputs** tab, grouped by stage: Survey design, Fieldwork and data, Analysis and reporting.
- **Theme:** switch between light and dark once with the theme button. The b3 logo adapts.

---

### Act 1 – From brief to questionnaire (7 min)

**Do:** open **Demo – Live** and paste the whole of [brief.md](brief.md) into the chat.

**Say while it runs** (1–3 min). Point at the stage messages as they appear:
> "The router recognised a study brief and sent it to the questionnaire agent. It's drafting screeners, the brand funnel, the image grid, importance, NPS and open ends to match each objective. A validator then checks every skip, show-if and termination rule before the draft is saved. A draft with broken logic is never stored."

**Show:**
1. **The questionnaire editor:**
   - Expand a question.
   - Edit an option label.
   - Use **Move up** / **Move down** on a question.
   - **Add option**, then save.
   
   Say: "Researchers stay in control: every question is editable here."
2. **Objectives coverage:** each objective maps to the questions that answer it.
3. **Downloads:** **DOCX** from the Outputs card. Open it in Word for a few seconds.

**Type** (edit by chat):
```
Add a question after the NPS question asking how likely they are to buy a coffee machine in the next 12 months, on a 5-point scale.
```
**Show:** the new version, and that the version number on the Outputs card went up.

**Show the quiet extra:** a **Report plan** card has already appeared under Analysis and reporting.
> "As soon as a questionnaire exists, the report planner drafts the client deck plan in the background. We'll come back to it."

**Fallback:** if the draft takes more than 4 minutes, switch to **Demo – Backup** and walk through its questionnaire. Come back when the live one lands.

---

### Act 2 – Programming the survey in Decipher (4 min)

**Type:**
```
Program this questionnaire in Decipher
```

**Say:**
> "The programming agent writes Decipher XML, with rank-sort styles, rotations and quotas. If Decipher rejects anything, the agent reads the error, repairs the XML and uploads again."

**Show:**
1. The Decipher card: **Download XML**.
2. **Preview survey:** click through two or three screens as a respondent. Answer a screener so the routing is visible.
3. The Decipher survey link in the chat reply, if the key is configured.

**Fallback:** if upload fails, show the XML and the preview. Say upload is environment-dependent.

---

### Act 3 – Fieldwork: price a sample, then generate data (6 min)

**Type** (quote only):
```
Price a Prolific sample: 600 US adults, 50/50 men and women, age bands 18-34, 35-49, 50-65, 12 minutes.
```
**Show:** the quote card with the eligible audience, the per-respondent reward and the total cost.
> "Nothing is bought until a person confirms the total. For today we stop here."

**Do not confirm.**

**Type:**
```
Generate 600 synthetic respondents from the Decipher survey, following the sample requirements: 50/50 men and women, age bands 18-34, 35-49, 50-65 at a third each, and regions in line with US Census.
```

**Say** (about 2 min):
> "To demo and test before fieldwork, a synthetic generator walks the programmed survey: its routing, terminates and quotas. A model drafts personas and the traits that link answers. For example, people who like a brand rate it higher everywhere. Python then draws every respondent and checks the result. The output is a real SPSS file loaded as the project dataset."

**Show:** the synthetic data card, with its **Personas**, **Traits that link answers** and **Quotas** (target vs. achieved), plus the **SPSS .sav** download.

> Alternative if you have a real file: drag a `.sav` into the chat with the upload button instead. Every later step works the same.

---

### Act 4 – Data quality: skipped for synthetic data (30 sec)

**Don't run cleaning in the live demo.** For synthetic data the report planner skips the cleaning step by default:
- the synthetic-data reply says "Data cleaning is optional for synthetic data";
- the report plan shows **Data (synthetic) … cleaning skipped**, with **Skip data cleaning** ticked.

**Say, in one line, then move on:**
> "On real fieldwork data, a cleaning agent checks for speeders, straight-liners, failed attention checks and gibberish open ends, and recommends who to remove. Synthetic data doesn't need it, so the report plan skips that step. A researcher can untick that to run it anyway."

**If someone asks to see cleaning,** open the `Cleaning test (Brand X)` project. It holds a real tracker dataset, and its fraud recommendation shows each respondent's flags and the keep / review / remove call. Don't run cleaning on the synthetic data: synthetic open ends repeat, so nearly everyone lands in "review".

---

### Act 5 – Tables (6 min)

**Type** (a quick single table):
```
Run a crosstab of likelihood to recommend BrewCo by gender
```
**Show:** the crosstab viewer, with percentages, bases and significance letters within the banner. Download **Excel**.

**Type** (the full tab plan):
```
Build the tab spec from the questionnaire with banners: total, gender, age band, region, and BrewCo owners vs competitor owners vs non-owners
```
**Show:**
- The editable tab-spec grid: sort, **Insert table**, delete a row.
- **Download Excel**: the tab plan in the analyst workbook style.
- That the saved spec has been dry-run, so every table has a base.

**Then switch to Demo – Backup** and open its full crosstab output:
- Use **Search tables** to jump to the NPS table.
- Download the full tab book.

> "Running the full tab book takes a few minutes on a real study, so here's the one from the rehearsal."

---

### Act 6 – Advanced analytics (9 min)

Back in **Demo – Live**.

**1. Key driver analysis.** Type:
```
Run a key driver analysis of likelihood to recommend BrewCo on the ten BrewCo image attributes
```
Or, with question numbers: `Run a key driver analysis of Q18 on Q10r1 to Q10r10` (Backup's numbers; check the Live project's).

**Show:**
- The importance ranking (Johnson's relative weights).
- The **Charts** gallery and the **Script** tab.
- The **Research standards applied** panel.
- **Diagnostics:** collinearity and base checks.

> "We built quant research guardrails into the analytics. Driver analysis always reports an importance ranking, and small bases or collinearity are flagged automatically."

**2. Segmentation.** Type:
```
Segment respondents on their BrewCo image ratings, then profile the segments by gender, region and likelihood to recommend
```
**Show:**
- The k search: 4 to 8 clusters tested, with the 5% smallest-segment rule.
- Segment sizes and the profile heatmap.
- The workbook download.

> "Segmentation always tests 4 to 8 solutions and rejects one with a segment too small to act on."

**3. A method the studio doesn't have built in** (shows the sandbox):
```
Test whether likelihood to recommend BrewCo differs across regions using a Kruskal-Wallis test, with Dunn post-hoc comparisons
```
> "There's no built-in Kruskal-Wallis. The analysis agent wrote the code, ran it in an isolated sandbox with no network access and no API keys, and the validator checked the numbers before publishing."

**Show:** the generated **Script** and the result.

**Fallback:** if any analysis runs past 2 minutes, open Backup's version of it from the Outputs tab.

---

### Act 7 – Open-end coding (4 min)

**Type:**
```
Auto-code the open ends for the reason behind the recommendation score
```
Or, with the question number: `Auto-code the open ends in Q27` (Backup's number).

**Say** (about 2 min):
> "The AutoCoder discovers a hierarchical codeframe of nets, subnets and codes from the question and the answers, then codes every response in one pass."

**Show:**
- The codeframe tree.
- Code frequencies.
- The review queue: search a response, change a code on one row, and note that initial and final codes are both kept.

---

### Act 8 – The report planner and the client deck (8 min, the finale)

**Open the Report plan card.** It has been updating quietly since Act 1.

**Show:**
1. **Stage and data facts:** the sample size (600, synthetic, cleaning skipped), the **Skip data cleaning** option, and the base on each slide.
2. **Objectives the deck must answer**, and how the sections follow the story: objectives and approach, then who we spoke to, then one chapter per objective, then what drives results, then takeaways.
3. **One slide:** what goes on it, which questions, the banner, the statistic or analysis method, and any filter.
4. **Edit live:**
   - Rename a slide title.
   - Remove one slide, then show it under **Planned slides not included**, where you can restore it.
   - Add a slide: a stacked bar of likelihood to purchase by age band.
   - Save.
5. **Questions not reported:** nothing the data can answer is missed. Unreported items are listed with a reason, such as attention checks.

**Click "Update with data"** (or type `Update the report plan with the data`).

**Then click "Generate report"** (or type `Generate the report`).

**Say while it runs** (5–7 min), and switch to **Demo – Backup's** report:
> "The executor runs every slide. Question slides go through the table engine, analysis slides call the analytics agent, and open-end slides call the coding agent. A writer agent drafts each headline, but any sentence that quotes a number the slide didn't compute is thrown out."

**Open Backup's PowerPoint** in PowerPoint:
- The title slide, then **What this study set out to answer**, then the sample profile.
- The brand funnel, the image chapter including the brand image map, and NPS by brand.
- Driver importance and the segments.
- **Key takeaways.**
- **Click a chart, then Edit Data.** "Every chart is a native, editable PowerPoint chart, not a picture."

**Return to Demo – Live** when its deck is done. Show its report card and the **PowerPoint** download.

---

### Act 8b – Delivering to the team's tools (3 min)

Run this in **Demo – Live** once its deck is done. If it isn't done yet, run it in **Demo – Backup**, whose deck is always there.

**Say** (one line, before you start):
> "Researchers don't live in one app. Quant OS connects to the tools a team already uses: Google Drive, Slack, Microsoft 365, or any MCP server. Today I'm using a local stand-in workspace, because the real Drive and Slack connections need our IT admin's one-time sign-off."

**Show:** open **Connectors**, bottom left.
- The Google Drive, Slack and Microsoft 365 cards, with **Setup steps** open on one of them.
- **Stand-in workspace**: **Connected**. Open **Tools · 5**: the tools that only read are marked **Reads**, and the ones that upload or post are marked **Needs approval**.

Close the dialog.

**1. Save the deck.** Type:
```
Save the report deck to Google Drive in the Reports folder
```
About 15 seconds later, an approval card appears in the chat.

**Show:** the file name (`report.pptx`) and the target folder on the card.

> "The agent found the Reports folder on its own and picked the right file. But uploading changes something outside Quant OS, so nothing happens until I approve it."

Click **Approve**. The chat confirms the save and shows the link.

**2. Tell the team.** Type:
```
Post the key takeaways to #research
```
**Show:** the card has the exact message text, drafted from the deck's Key takeaways slide. The numbers match the deck, such as 54.0% value for money.

> "It looked up the channel itself and wrote the post from computed results only. I can read every word before it goes out."

Click **Approve**.

**Agent moment:** the agent planned the steps itself: find the folder, pick the file, look up the channel, draft the message. You approved only the two steps that leave the building.

**Optional** (only if there's time): type `Import the study brief from Google Drive`. It saves the BrewCo brief into the project with no approval card, because it only reads. "That's how a project can start from a brief that's already in Drive."

**Fallback:** if a card doesn't appear within 30 seconds, or Approve shows an error, open Connectors, click **Test** on the stand-in, and try once more. If it still fails, skip the act. Say "the deck is also one click away as a download" and move on to Act 9.

---

### Act 9 – Trust and learning (3 min)

**Show:**
- **Validation badges** on the Outputs cards, and the **Provenance** and **Claims** view on an analysis. Each number in the narrative is tied to the computed result.
- **Stale badges:** edit the questionnaire, and the outputs built on the old version are marked stale.
- **Feedback:** click **Not helpful** on an output, type "Should have used top-2 box" in *What should be different?*, and submit.
  > "Every edit, correction and rating is captured. That's step one of the system learning how our researchers work."

**Close:**
> "From brief to programmed survey, sample, clean data, tables, advanced analytics, coded open ends and an editable client deck, in one workspace, with a researcher in control at every step."

---

## 4. If something goes wrong

| What you see | What to do |
|---|---|
| A task runs much longer than the table above | Say "while that runs…", switch to Backup, show the same output, come back. |
| A red error in the chat | Read it out (the messages are plain sentences), then show Backup's version. Avoid retrying more than once live. |
| The agent asks a clarifying question | That's a feature: answer it in one line ("Use 18-34, 35-54, 55+"). Say it asks rather than guesses. |
| A prompt with question numbers fails | Use the plain-language version, or check the variable names in the questionnaire card. |
| The frontend shows a blank or error page | Reload the browser. Project state is saved, and the chat history comes back. |
| The backend stops responding | Restart it with the backend command above. Tasks and outputs persist in the database. |
| A connector step says the server "could not be reached", or the stand-in card shows **Needs attention** | The stand-in isn't running. Start it with the command under *One hour before*, then click **Test** on its card. If the chat says "No connectors are connected yet", the stand-in was removed: add it again from the Connectors dialog. |

## 5. Likely audience questions

- **Where does the data go?** The models get the questionnaire, the variable labels and aggregated results. Analysis code runs locally in an isolated sandbox with no network access and no API keys.
- **Can it hallucinate numbers?** Numbers come only from code. The validator checks numeric claims against computed results, and the report writer's sentences are dropped if they quote anything uncomputed.
- **Can we use our own tab spec or codeframe?** Yes. Upload an Excel tab spec (canonical or mapped from an external template) or an existing codeframe.
- **MaxDiff or conjoint?** Out of scope today, deliberately blocked rather than approximated.
- **Does it work with our Google Drive, Slack or SharePoint?**
  - Yes, through each provider's official MCP server. An admin registers the app once, and the steps are on each card.
  - Google's Drive server is in Developer Preview.
  - Microsoft's hosted server needs a Microsoft 365 Copilot licence.
  - Any other MCP server can be added by URL.
- **Can the agent post or delete things on its own?** No. Tools that only read run straight away. Anything that uploads, posts or changes something waits on an approval card, which shows the exact file or message.
- **What's next?** Learning from captured edits (step 2), and a developer mode for approved external integrations.
