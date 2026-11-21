# Quant OS live demo runbook

**Story for the audience:** one workspace takes a study from a client brief to a client-ready PowerPoint. Specialist agents do each job, every number is computed rather than written by a model, and the researcher can edit at every step.

**Running time:** about 81 minutes plus Q&A, or about 90 with the optional Act 8c. Data cleaning (Act 4) is a 30-second mention, because synthetic data skips it. If you need to cut:
- drop Act 8c (tracking and languages, 9 min) first, then Act 8b (connectors, 3 min), then Act 1b (Word import, 5 min), then Act 5b (weighting, 6 min), then Act 6b (Segments tool, 4 min);
- the core path is the opening plus Acts 1, 2, 3, 3b, 5, 6 and 8, about 54 minutes. Keep Act 3b in: it's the one part the audience takes part in.

**Study used throughout:** the BrewCo home coffee machine brand health study. Its brief is in [brief.md](brief.md).

**New since the last version of this runbook (21 November):**
- on the Decipher survey, three new tabs (Act 2):
  - **To-dos**: what programming couldn't do on its own, with **Fix with AI** (the reviewer re-checks the fix) and **Mark done**;
  - **Logic test**: simulated respondents run through the XML and are checked against the questionnaire's bases and terminates;
  - **Compare XML**: each question side by side with a hand-edited or reference XML;
- programming now reviews and fixes the XML for up to 5 rounds, until nothing is left or nothing changes, so it takes a little longer (Act 2);
- a **Study tools** workspace tab with three tools:
  - **Segments**: compare solutions, name the segments, add them to the data, download an Excel typing tool (Act 6b);
  - **Tracking**: start the next wave, see what changed, trend tables between waves (Act 8c);
  - **Languages**: translate the questionnaire, review it and sign it off (Act 8c);
- updated accuracy figures in section 6.

**Earlier additions:**
- importing a finished Word questionnaire exactly as written (Act 1b);
- the programming logic panel with **Edit logic** and **Show in the file** (Act 2);
- the room takes a live survey on their phones while the bot and fraud detector flags them (Act 3b);
- Decipher uploads that wait for **Upload to Decipher** (Act 2);
- the **Learned rules** page and its **Progress** tab, **Done as … Not this?**, and **Stop** (Act 9);
- a section on what the demo can't show, and what to say instead (section 6);
- significance letters that are actually tested, including means (Welch t-test) and weighted tables (on the effective base), with a tab book cover note that matches the settings used (Act 5);
- the **Weighting** tab: census targets found by web search with references, edited by the researcher, then a rim weight that every table, tab book and the report deck use (Act 5b);
- a button to hide the projects panel while you work in a project (**Hide projects panel**, top of the rail).

---

## 1. How the demo is set up

Some steps take a few minutes, so run the demo across several projects:

| Project | What it is | Used for |
|---|---|---|
| **Demo – Live** | Empty at the start. You type every prompt in front of the audience. | Acts 1 to 7, including 5b |
| **Demo – Backup** | The full study run end to end the day before, with the same prompts. | Showing finished outputs while a live task runs, and as the fallback if a step fails |
| **Demo – Import** | The BrewCo questionnaire, downloaded as Word from Backup and imported the day before. | Act 1b: the imported questionnaire, its source text, and its planned logic |
| **Demo – Quality** | A 6-question BrewCo survey, uploaded to Decipher with bot and fraud tracking the day before. | Act 3b: the room takes the survey on their phones |
| **BrewCo Live Quality Check** | The same 6-question survey, already tested on 16–17 November. It has 15 sessions, 5 of them bots. | Act 3b fallback, and showing what a real bot looks like |
| **Demo – Wave 2** | The second wave of the BrewCo study, started from Demo – Backup the day before, with its own 600 synthetic respondents and a Spanish translation. | Act 8c: wave changes, trend tables and languages |

**Rule of thumb:**
- **Short steps** (under a minute): wait on screen and narrate the stage messages in the chat.
- **Long steps:** start the step, switch to **Demo – Backup**, show the finished version of the same output, then switch back.

**How long each step usually takes.** "Median" and "Slowest seen" come from your past runs; "Rehearsal" is the Demo – Backup build of the 13th.

| Step | Median | Slowest seen | Rehearsal | How to handle it |
|---|---|---|---|---|
| Brief to questionnaire | 1.6 min | 5.7 min | 5.5 min | Live; narrate, and go to Backup at 3 min |
| Questionnaire edit by chat | 0.9 min | 1.0 min | 2.0 min | Live |
| Word questionnaire import (includes planning the logic) | – | – | **not yet rehearsed** | Start it live, show **Demo – Import** while it runs |
| Decipher programming | – | – | **not yet rehearsed** | Start it live, show **Demo – Backup's** Decipher card while it runs. The 4 s from the 13th no longer applies: programming now plans the logic and reviews and fixes the XML for up to 5 rounds. On client questionnaires that took 2–15 min, and one long one took 22 min |
| Logic test (400 respondents) | – | – | about 2 s on a 3-question test survey, 21 Nov | Live |
| Fix with AI on one to-do | – | – | 6–30 s on a test survey, 21 Nov | Live |
| Compare XML | – | – | under 2 s | Live |
| Prolific price quote | under 10 s | – | 10 s | Live, **quote only** |
| The room takes the 6-question survey | – | – | **not yet rehearsed** | Live. Allow 3 min for phones; each result appears about 10 s after that person finishes |
| Synthetic respondents (600) | 1.8 min | 2.0 min | 1.8 min | Live |
| Fraud and quality check | 2.3 min | 2.8 min | 16 s | **Skipped** for synthetic data |
| Single crosstab | under 10 s | – | 10 s | Live |
| Census target research (age, gender, region) | – | 2.3 min | 1.7 min on a test project, 19 Nov | Live; narrate the stage messages, show Backup's **Weighting** tab if past 2 min |
| Build the weight | under 5 s | – | 2 s | Live |
| Build the tab spec | under 10 s | 4.4 min | 1.7 min | Live |
| Run the full tab spec | 0.5 min | **21.5 min** | 33 s | **Show it from Backup** |
| Analysis (driver, segmentation, tests) | 0.3 min | 11 min | 16–64 s | Live; switch to Backup if past 2 min |
| Segments tool: compare 3 to 6 segments (600 rows) | – | – | about 3 s on test data, 21 Nov | Live |
| Start the next wave | – | – | under 2 s | Done the day before; don't start a wave live |
| Trend table | – | – | under 2 s | Live |
| Translate the questionnaire (Backup's has 337 segments) | – | – | **not yet rehearsed**; 5 segments took about 20 s | Done the day before; only edit and sign off live |
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

   It was built before the logic panel and the upload confirmation existed, and its questionnaire has no planned logic yet. Type `Program this questionnaire in Decipher` in Backup once more and time it; put the time in the table above. This fills in its programming logic panel and **Edit logic**, which Act 2 shows while the live run works. At the end, press **Keep XML only**, not **Upload to Decipher**: Backup already has its survey.
2. **Build Demo – Import, and time it.**
   - In Demo – Backup, download the questionnaire as **DOCX**.
   - Create a project named `Demo – Import`, attach that file, and type `Use this questionnaire`.
   - Note how long the import takes, and put it in the timing table above. The import also plans the logic, so the programming logic panel is ready when it finishes.
   - Check that **Show in the file** appears on the questions. If the import fails, the reply lists what differed. Fix the file, or drop Act 1b.
   - **Give the Learned rules page something to show.** The page is empty today because no corrections have been made yet. In Demo – Import:
     - use **Edit logic** to correct one question's planned logic, where it differs from what the notes say;
     - type `Program this questionnaire in Decipher`, then press **Keep XML only**.
     
     Comparing your correction with the plan creates a rule. Make a real correction, not a made-up one: rules are used on later projects. Afterwards, check that the rule is listed under **Learned rules**.

   Use only BrewCo or another made-up questionnaire here. Never put a client questionnaire on screen.
3. **Give Demo – Backup a weight and a fresh tab book.** Do this after step 1, because building a weight makes later tables in Backup weighted.
   - **Re-run the tab book.** Backup's tab book (13 November) was made before significance testing was fixed. Its cover still says "Weighted tables do not receive significance letters", and a few 100%-vs-0% cells have no letter. Type `Run the saved tab spec`. This can take up to 20 minutes, so start it first.
   - **Then build the weight.** Open the **Weighting** tab. The suggested variables should be **S1** (age, typed in, shown as bands 18–24 … 55–64), **S6** (gender) and **S5** (region). Click **Research census targets**, time it, and put the time in the table above.
     - Check that every reference is marked **Found by the search**, and that each variable has targets.
     - The search runs separately for each variable, so a run occasionally leaves one variable blank. Click **Research census targets** again, or type the figures from the table in Act 5b.
     - Click **Build weight**, and write down the efficiency and weight range for Act 5b.
   - Leave **Use QOS_WEIGHT in crosstabs, tab books, and reports** ticked.
4. **Build Demo – Quality, the survey the room will take.** Start clean, so the counts on screen begin at zero and only show the audience.
   - In **BrewCo Live Quality Check**, download the questionnaire as **DOCX**.
   - Create a project named `Demo – Quality`, attach the file, and type `Use this questionnaire`.
   - Open its **Live quality** tab:
     - tick **Add tracking when this survey is programmed in Decipher**;
     - tick **Show a privacy notice on the first page**;
     - leave **End the survey for respondents with a clear bot signal** off, so a colleague who rushes isn't thrown out.
   - Type `Program this questionnaire in Decipher` and press **Upload to Decipher**. This is the one new Decipher survey for the demo. Check that the tab now says **Tracking is in the survey XML** and shows **Share this survey link**.
   - **Take the survey yourself on your phone**, once honestly and once rushing through, and check that both appear in the tab. Write down how long the 6 questions take.
   - **Make a QR code for the link.** Open the link in Edge, use **Create QR code for this page** from the address bar, and save the image. Put it on one slide with the short link under it.
   - Open **BrewCo Live Quality Check**'s Live quality tab once, to check its 15 earlier sessions still load.

   If you can't make a new survey, use **BrewCo Live Quality Check** in the act instead. Say "the first 15 sessions are our test runs from 16–17 November", and point to the newest rows.
5. **Know the question numbers.** The questionnaire is generated fresh each time, so the numbers in **Demo – Live** may differ from Backup's. All the prompts below use plain words: a resolver maps them to the right columns by their labels, so they work either way. In Backup the numbers are:

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
6. **Check the keys in `backend/.env`.** You need the OpenAI key, plus Decipher (for Act 2) and Prolific (for Act 3). Without the Decipher key, programming still produces the XML and the preview, but there's no upload button. Never show the `.env` file on screen.
   - **Every agent runs on OpenAI (`gpt-6.1-sol`)** since 19 November, including synthetic respondents (Act 3), open-end coding (Act 7) and census research (Act 5b). The Anthropic account has no credit; it's only used as a backup model, so its being empty doesn't stop anything.
   - **Check the OpenAI account has credit.** It's now the only provider. Send one short request in Backup to check.
   - Synthetic data and coding on OpenAI were checked against Backup on 19 November: the persona plan took 34 s and the answer profiles 1.6 min, and 40 open ends were coded in 39 s. Re-time Act 3 at the rehearsal.
7. **Check the AutoCoder is installed.** If you ran `uv sync` since installing it, reinstall it (see the README).
8. **Check Backup's survey with the new Decipher tabs.** After step 1, open Backup's Decipher survey:
   - **Logic test:** click **Run logic test**. It should say **100% of respondents match** and **No problems**. If it lists a problem, note it: it's a real bug, and it's better found now than on stage.
   - **To-dos:** note one to-do that is easy to fix (a base or a terminate is best). In Act 2 you'll click **Fix with AI** on it. Don't fix it now.
   - **Compare XML:** download Backup's XML, change one question's wording in a text editor, and save it as `brewco_edited.xml`. Act 2 compares against it. Use BrewCo only, never a client's XML.
9. **Build Demo – Wave 2** for Act 8c. Do this after step 3, so the wave copies Backup's weighting setup.
   - In **Demo – Backup**, open **Study tools → Tracking**. Type `Q1 2027` as the label and `Demo – Wave 2` as the name, then click **Start wave 2**. This only adds a tracking label to Backup; its outputs don't change. The app opens the new project.
   - In Demo – Wave 2, type `Program this questionnaire in Decipher`, then press **Keep XML only**. Its logic is already planned, so this is quick.
   - Type the same synthetic-respondents prompt as Act 3. The trend table compares this data with Backup's.
   - Check **Tracking → Changes since the previous wave**. It should say all questions are unchanged. To have something to show, edit one question's wording in the questionnaire editor (for example, add "in the past 12 months" to a question) and save it.
   - Open **Study tools → Languages** and add `Spanish (United States)`, with the note `Neutral US Spanish; keep brand names in English`. Time it and put the time in the table above. Don't sign it off: you'll do that live.
10. **Try the Segments tool once** in Demo – Backup (**Study tools → Segments**). Pick the ten BrewCo image ratings, compare 3 to 6 segments, and write down which solution is recommended. Don't press **Add segments to the data** in Backup: it makes a new dataset version.

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
   - Once you're in a project, click **Hide projects panel** (top of the rail) for more room. **Show projects panel**, at the top left of the chat, brings it back when you switch projects.
4. **Have these ready to hand:**
   - [brief.md](brief.md), open to copy.
   - PowerPoint, to open the final deck.
   - Excel, for the tab book.
   - Word, for the questionnaire.
   - The QR code slide for Act 3b, and the survey link to paste into the meeting chat for anyone joining remotely.
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
- **Press Upload to Decipher at most once.** Programming only prepares the XML; the upload happens when you press **Upload to Decipher** or answer yes in chat. Each upload creates or updates a real survey in the company Decipher account. If you don't need the upload, press **Keep XML only**.
- **Don't program or upload again in Demo – Quality on the day.** The link the room scans must stay the same.
- **Don't ask the room for personal details** in the survey, and tell them what's recorded before they start (see Act 3b).
- **Don't put client questionnaires or client survey names on screen.** That includes the benchmark surveys behind the accuracy figures in section 6.
- **Don't run the full tab spec live.** It can take up to 20 minutes.
- **Don't start a new wave live, and don't translate the whole questionnaire live.** Both are done the day before in Demo – Wave 2. Live, only show the changes and the trend, and edit and sign off the language.
- **Don't press Add segments to the data in Demo – Backup.** It makes a new dataset version in Backup. Use Demo – Live.
- **Don't paste a client's XML into Compare XML.** Use the edited BrewCo file from the day before.
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

### Act 1b – Bringing in a questionnaire the client already wrote (5 min, optional)

**Say:**
> "Most projects don't start from a brief. They start from a Word questionnaire the client has already approved. Quant OS imports it exactly as written: it doesn't rephrase, and it doesn't drop anything."

**Do:** create a new project, attach the BrewCo questionnaire DOCX, and type:
```
Use this questionnaire
```

**Say while it runs:** point at the stage messages, such as "Read 3 of 7 parts of the file".
> "It splits the file at the question numbers and copies each part in parallel. Then every question, answer and instruction is checked against the file word for word. A part that doesn't match is read again with the differences listed. If it still doesn't match, nothing is saved, and it shows you exactly what differs."

**Then switch to Demo – Import** and show:
1. A question with **Show in the file**: the passage from the Word file, with the question's wording highlighted.
   > "You can always see exactly where each question came from."
2. The programming instructions kept word for word as notes under each question.

**Fallback:** if the live import is still running at the end of the act, leave it and carry on with Act 2 in Demo – Live.

---

### Act 2 – Programming the survey in Decipher (9 min)

**Type:**
```
Program this questionnaire in Decipher
```

**Say:**
> "The programming agent turns the instructions into logic: who sees each question, which rows show, number ranges, terminates and rotations. It builds the Decipher XML in our programmers' house style. Then a reviewer reads each question's instructions next to its XML, and the planner fixes what's missing. That repeats until nothing is left or nothing more changes."

This takes a few minutes. Point at the stage messages ("Checking the XML against the questionnaire (round 1)"), then **switch to Demo – Backup** for steps 1–2 and come back for step 3.

**Show:**
1. **The programming logic panel** on the questionnaire: each question's logic in plain words, such as who sees it, which rows show, and when it terminates. Anything it couldn't settle is listed under **item(s) need a programmer's decision**.
   > "It doesn't guess. Anything it can't express is left as a clear to-do for a programmer."
2. **Edit logic** on one question. Change one condition and show the plain-words summary change, then cancel without saving.
   > "Logic is edited in a form, not in XML. Corrections like this are also how it learns. More on that at the end."
3. **The Decipher card.** It says **Nothing has been sent yet** and shows where the survey would go.
   > "Nothing is uploaded until a person presses Upload."
   
   Press **Upload to Decipher** once (see *Do not do these live*), or **Keep XML only**.
4. **Download XML**, then **Preview survey**: click through two or three screens as a respondent, and answer a screener so the routing is visible.
5. The Decipher survey link in the chat reply, if you uploaded.

**Then show the three new tabs on the Decipher survey.** Use Backup's survey if the live one isn't done.

6. **To-dos.** Each to-do is grouped by question, and says whether the planner left it or the reviewer found it.
   - Click **Fix with AI** on the to-do you picked the day before. It takes up to half a minute.
     > "It plans that question again with the to-do as the problem, rebuilds the XML, and then the reviewer checks the fix. If the reviewer still finds something, it stays on the list. Nothing is uploaded."
   - Click **Mark done** on a quota or a page-layout to-do.
     > "Mark done is for what a programmer handles in Decipher. It disappears from the XML comments and moves to Done, where it can be reopened."
7. **Logic test.** Click **Run logic test**. It takes a couple of seconds.
   > "This is the survey test a programmer does by clicking through the test link, done 400 times. Each simulated respondent takes the XML the way Decipher would. Then the same answers are checked against the questionnaire's own bases and terminates. If anyone sees a question they shouldn't, or isn't screened out when they should be, it shows the answers that caused it."
   
   Point to **100% of respondents match** and the screened-out counts. Open **How many saw each question** to show the counts side by side.
8. **Compare XML** (optional, 1 min). Choose `brewco_edited.xml`, then **Compare**.
   > "If a programmer has edited the XML, or we have the XML from an earlier wave, this lines up each question with ours side by side, using the same checks as our accuracy benchmark."
   
   Open the question you edited and show the highlighted line.

**Fallback:**
- **The live run isn't done when you've finished steps 1–2:** show Backup's Decipher card and preview, and come back to the live upload card at the start of Act 3.
- **The upload fails:** show the XML and the preview. Say the upload depends on the environment. If Decipher rejects the file, the agent corrects the part Decipher named and tries again.

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

### Act 3b – The room takes the survey: live bot and fraud detection (7 min)

Open **Demo – Quality**, then its **Live quality** tab.

**Say:**
> "Synthetic data is great for testing, but in real fieldwork the biggest risk is bad respondents: bots, people speeding through for the incentive, and copy-pasted answers. So let's do some real fieldwork right now. You're the sample."

**Do:**
1. Show the QR code slide. Paste the link from **Share this survey link** (**Copy link**) into the meeting chat for anyone remote.
2. Before anyone starts, say what is recorded:
   > "It's 6 questions about coffee machines and takes about 2 minutes. Please don't enter anything personal. While you answer, the survey records how you answer, such as timing, typing, scrolling and taps, along with your answers and a device and network check. That's exactly what it does with real respondents. It's only used for this demo."
3. Ask most of the room to answer honestly. Ask two volunteers to be **bad respondents**:
   - tap through as fast as they can;
   - pick the same column in every row of the grid;
   - paste one copied sentence into both open ends, or type gibberish such as "asdf asdf".
4. Ask everyone to **finish the survey**. A person's verdict is worked out on the last page, so anyone who stops partway stays under **In survey**.

**Show while the room answers** (the tab refreshes about every 8 seconds; no need to click anything):
1. **The counts:** **Started**, **In survey**, **Checked** and **Flagged**, going up as people finish.
2. **Why respondents were flagged:** the volunteers should show up under **Speeder**, **Straight-lining**, **Pasted answers** or **Low-quality open ends**.
3. **The respondent table:** each row has a **Behaviour verdict** (**Looks human**, **Needs review** or **Bot-like**), plus its open-end quality and reasons. Find a volunteer's row and read the reasons out.
   > "It doesn't just say 'bad'. It says why, so a researcher can decide."
4. **Quality rules:** the thresholds a researcher can change, and **End the survey for respondents with a clear bot signal**, which is off today.
   > "With this on, a clear bot is screened out partway through the survey, so we never pay for it. It's only ever ended on a clear signal, never on a score alone."
5. **Quality dashboard** (bottom left): the live tiles, **Starts over time**, and the CSV export.

**Say to close the act:**
> "Each verdict is also written into hidden questions in the Decipher data file, so it travels with the data into cleaning and tables."

**What to expect, and what to say:**
- **Honest people flagged as Duplicate or high fraud risk.** Everyone is on the same office Wi-Fi, often on the same kind of phone, all at once. Say:
  > "That's exactly what a respondent farm looks like from the outside, which is why it's a flag for review, not an automatic removal."
- **No one is Bot-like.** That's expected: people can't fake a script. Open **BrewCo Live Quality Check**'s Live quality tab, which has 5 real bot sessions from testing, and show one of its **Bot-like** rows.

**Fallback:**
- **Results don't appear within a minute of people finishing:** open **BrewCo Live Quality Check** and walk through its 15 recorded sessions.
- **The room can't reach the survey** (blocked Wi-Fi or a corporate phone): ask people to use mobile data, or go straight to the fallback.

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

**Point to the significance letters:**
- Each letter means that column is significantly higher than the column with that letter, within the same banner group.
- Uppercase is 95% confidence, lowercase 90%.
- A column with a base of 30 or less shows "." and isn't tested.
- The footnote names the test: a two-tailed z-test for percentages, and a Welch t-test for means such as the 0–10 score's mean row.

> "These letters are computed, not decorative. The note on the cover of the tab book is written from the settings actually used, so the page and the numbers can't disagree."

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

### Act 5b – Weighting to census targets (6 min)

Still in **Demo – Live**. Open the **Weighting** tab (beside **Live quality**).

**Show the starting point:**
- the suggested variables, **age**, **gender** and **region**, picked from the questionnaire;
- the study population, taken from the questionnaire's sample notes;
- the **Sample** column: synthetic data is spread evenly, so the 18–24s and the Northeast are under-represented compared with the US population.

**Click Research census targets.** It takes about two minutes, and searches each variable separately, at the same time. While it runs:
> "An agent searches official statistics, the Census Bureau's American Community Survey and population estimates, for the population this study targets. Then it maps the published figures onto our own answer codes."

**When it finishes, show:**
1. **Targets with references.** Each target cites a source, such as [S1], and the note under it shows the arithmetic, for example which published age bands were added together.
2. **Found by the search.** Every reference is checked against the pages the search actually opened. One it can't match is marked **Not confirmed, check it**.
3. **Edit a target live.** Type over one figure. The total turns red until the variable adds up to 100 again. Then put it back.
   > "The researcher decides. The agent proposes, with its sources, and you can accept it or type your own."
4. **Click Build weight.** It takes a couple of seconds. Point to:
   - **efficiency** and **effective base**, the cost of the weight in sample size;
   - the **weight range**: weights are capped between 0.3 and 3 by default;
   - the **achieved** column, which matches every target.

**Then type:**
```
Run a crosstab of likelihood to recommend BrewCo by gender
```
**Show:**
- The base line now reads **weighted by QOS_WEIGHT**, with the unweighted, weighted and effective bases.
- The significance letters are still there. They're tested on the weighted percentages, using each column's **effective base**, so weighting can't make a difference look more certain than the sample allows.
- Typing `unweighted` in a request turns the weight off for that table.

**If the search fails or leaves a variable blank,** click **Enter targets myself** and type these (from a run on 19 November; ACS 2025 and the Vintage 2025 estimates, US adults 18–65):

| Variable | Targets |
|---|---|
| Gender | Woman 50.4, Man 49.6 (Census male/female figures) |
| Region | Northeast 17.1, Midwest 20.1, South 39.0, West 23.8 |
| Age | Copy them from Backup's **Weighting** tab (prepared the day before). |

Leave **Non-binary**, **Prefer to self-describe** and **Outside the United States** without a target. Those respondents keep their own share.

**Note for Acts 6 and 8:**
- From here on, crosstabs, tab books and the report deck in Demo – Live are weighted.
- The advanced analyses in Act 6 (driver, segmentation, tests) are not weighted yet. If anyone asks, say so.

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

### Act 6b – The Segments tool (4 min, optional)

Still in **Demo – Live**. Open **Study tools → Segments**.

**Say:**
> "The chat segmentation you just saw is the analyst's view. This is the guided version a researcher uses to choose a segmentation and hand it on."

**Do:**
1. Search `image`, tick the ten BrewCo image ratings, leave **Segments 3 to 6**, and click **Compare solutions**. It takes a few seconds.
2. **Show the solutions table:**
   - **Separation:** how clearly respondents fall into one segment.
   - **Stability:** whether the same segments come back when it's fitted on a different 80% of the sample. 1 means identical.
   - **Smallest:** the smallest segment's share.
   - **Typing tool:** how many of a held-out quarter it classifies correctly, and with how few questions.
   > "It recommends the best-separated solution whose segments are all at least 5% of the sample and that comes back the same on different data. A researcher can pick another with Use."
3. **The segment cards:** each shows its share and the three ratings that set it apart. Rename one segment live, for example "Value seekers", and click **Save names**.
4. Click **Typing tool (Excel)** and open the file.
   > "Enter a respondent's answers in the yellow cells and it names their segment. The formulas are in the sheet, so a client can use it in a future survey without us."
5. Click **Add segments to the data.**
   > "The segment is now a variable with these names as labels, so it can be a banner in the tab book or a filter in the deck."

**Note:** the Segments tool doesn't use the weight. If anyone asks, say so.

**Fallback:** if Compare solutions shows an error, read it out. It usually means too few complete respondents for 6 segments: change **to 6** to **to 5** and try again.

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
1. **Stage and data facts:** the sample size (600, synthetic, cleaning skipped), the **Skip data cleaning** option, the weight (**QOS_WEIGHT**, from Act 5b), and the base on each slide.
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

### Act 8c – The next wave, and other markets (9 min, optional)

Open **Demo – Wave 2** (built the day before), then **Study tools**.

**Say:**
> "Most of our work isn't one study; it's a tracker that comes back every quarter, often in several countries. So the second wave shouldn't start from scratch."

**1. Tracking** (about 5 min)
- **Waves in this study:** Wave 1 (Demo – Backup) and Q1 2027. Click Wave 1 to show it's the same study, then come back.
  > "Starting a wave copied the questionnaire with all its programming logic already planned, the tab spec, the weighting setup and the report plan. Programming this wave took a fraction of the time, because there was nothing left to plan."
- **Changes since the previous wave:** the question you reworded the day before is listed, with how similar the wording is.
  > "Any change that would break the trend is flagged before fieldwork: new or reworded answers, a changed base, or wording that's moved too far."
- **Trend tables:** search and tick the recommend question (Q18) and the BrewCo image ratings, then click **Trend**.
  > "Each wave is tested against the one before it, at 95%. The arrows mark significant changes; a change without an arrow is within the noise."
  
  Both waves are synthetic, so most changes will be small. Say so rather than reading meaning into one arrow.

**2. Languages** (about 4 min)
- Open **Spanish (United States)**. It shows how many segments are translated, and that it's a **Draft**.
  > "It translates what respondents see: the wording, the answers and the grid rows. Brand names and piping are kept as written, and programmer notes stay in English for our programmers."
- Show one question side by side: English on the left, Spanish on the right. Edit one translation and click **Save**.
  > "A local reviewer checks every line and can change any of them."
- Type a reviewer name, then click **Sign off**. The badge turns to **Signed off**.
- Click **DOCX** to download the Spanish questionnaire, and open it for a few seconds.
  > "If the English questionnaire changes after sign-off, only the changed lines are translated again, and the language goes back to review. Nothing goes to field in a language nobody has checked."

**Fallback:** if Demo – Wave 2 is missing a part, skip that part. Starting a wave is instant, but programming the wave and generating its data take a few minutes, and a full translation takes longer still.

---

### Act 9 – Trust and learning (5 min)

**Show:**
- **Validation badges** on the Outputs cards, and the **Provenance** and **Claims** view on an analysis. Each number in the narrative is tied to the computed result.
- **Stale badges:** edit the questionnaire, and the outputs built on the old version are marked stale.
- **Done as … Not this?** under the latest reply. Open it to show the other ways the request could have been read.
  > "If it reads a request the wrong way, one click runs the same message the other way. You don't need to retype it."
- **Stop** next to Send while a task runs. You don't need to start a task for this; just point at where it appears.
  > "Long tasks can be stopped at any point. If you send the same request again, it picks up the parts that already finished."
- **Feedback:** click **Not helpful** on an output, type "Should have used top-2 box" in *What should be different?*, and submit.
  > "Every edit, correction and rating is captured."
- **Learned rules** (sidebar). Open one rule and show:
  - the example it came from;
  - what was read or planned, against what was correct;
  - how often it has been confirmed;
  - the switch to turn it off.
  
  > "When the importer misreads a layout and the retry gets it right, or a researcher corrects the logic before programming, that becomes a general rule. The next questionnaire gets the rules that fit it. A wrong rule can be switched off here."
- The **Progress** tab on the same page: import retries and corrections over time.
  > "This is how we check the learning is working: fewer retries and fewer corrections as more studies go through."

  With only a few studies in, the chart has few points. Say so rather than reading a trend into it (see section 6).

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
| **Research census targets** shows an error, or leaves a variable blank | Read the message out. Click **Enter targets myself** and type the figures from Act 5b, or show Backup's **Weighting** tab. "Credit" in the message means the OpenAI account needs topping up. |
| The Logic test lists a problem live | Read it out: "it found a respondent who sees a question they shouldn't, before any real respondent did". Then open the To-dos tab. It's the test doing its job, not a failure. |
| **Fix with AI** says the reviewer still found something | Read the new to-do out. It stays on the list for a programmer; say "it fixes what it can and says what's left". |
| A Study tools panel shows "Upload the data first" or "needs at least two waves with data" | You're in a project without data. Switch to Demo – Live (Segments) or Demo – Wave 2 (Tracking). |
| The frontend shows a blank or error page | Reload the browser. Project state is saved, and the chat history comes back. |
| The backend stops responding | Restart it with the backend command above. Tasks and outputs persist in the database. |
| A connector step says the server "could not be reached", or the stand-in card shows **Needs attention** | The stand-in isn't running. Start it with the command under *One hour before*, then click **Test** on its card. If the chat says "No connectors are connected yet", the stand-in was removed: add it again from the Connectors dialog. |

## 5. Likely audience questions

- **Where does the data go?** The models get the questionnaire, the variable labels and aggregated results. Analysis code runs locally in an isolated sandbox with no network access and no API keys.
- **Can it hallucinate numbers?** Numbers come only from code. The validator checks numeric claims against computed results, and the report writer's sentences are dropped if they quote anything uncomputed.
- **Can we use our own tab spec or codeframe?** Yes. Upload an Excel tab spec (canonical or mapped from an external template) or an existing codeframe.
- **Is the data weighted, and how are weighted tables tested?**
  - Rim weighting (raking) to the targets in the Weighting tab, with weights capped between 0.3 and 3 by default.
  - Significance tests on weighted tables use the weighted percentages and each column's effective base, (Σw)²/Σw².
  - The advanced analyses aren't weighted yet.
- **Where do the census targets come from?** A web search of official statistics, checked so every reference is a page the search actually opened. Every figure shows its arithmetic, and the researcher can change any of them.
- **MaxDiff or conjoint?** Out of scope today, deliberately blocked rather than approximated.
- **Does it work with our Google Drive, Slack or SharePoint?**
  - Yes, through each provider's official MCP server. An admin registers the app once, and the steps are on each card.
  - Google's Drive server is in Developer Preview.
  - Microsoft's hosted server needs a Microsoft 365 Copilot licence.
  - Any other MCP server can be added by URL.
- **Can the agent post or delete things on its own?** No. Tools that only read run straight away. Anything that uploads, posts or changes something waits on an approval card, which shows the exact file or message.
- **How accurate is the Decipher programming?** See *How good the programming is* in section 6.
- **Can it read our questionnaires as they're written?** Yes, if each question has an id such as S1, Q3a or CAT11_US, in the text or in a "QID" table row (with or without a full stop, as in "BM1."). Without ids, a file can only be used as a reference to draft a new questionnaire. Images, embedded spreadsheets and Word comments aren't read.
- **How do we know the survey logic is right before fieldwork?** The Logic test runs simulated respondents through the XML and checks each one against the questionnaire's bases and terminates. The questionnaire side is worked out separately from the XML builder, so a building mistake shows up as a disagreement. It doesn't replace a programmer's check on Decipher's own test link, and it doesn't check logic that depends on select-all grids.
- **What happens to the to-dos?** They're on the survey's To-dos tab. **Fix with AI** plans that question again and has the reviewer check the result; **Mark done** is for what a programmer handled in Decipher. A to-do someone asks the AI to fix counts as an instruction from then on, so the reviewer doesn't flag the fix as going beyond the questionnaire.
- **Can it run trackers and multi-country studies?** Yes. A new wave starts with the previous wave's questionnaire, logic, tab spec, weighting and report plan, and lists what changed. Trend tables test each wave against the one before. Each language is translated, reviewed, signed off, and built as its own survey XML. One Decipher survey holding several languages isn't generated yet.
- **How is the segmentation chosen?** Each solution is scored on separation, stability on a different 80% of the sample, and the smallest segment's size. The recommendation is the best-separated one with every segment at least 5% and stability of at least 0.6. The researcher can pick another.
- **What's next?** Repeated question blocks (loops) in Decipher, fieldwork monitoring (quota fill, incidence and drop-off by question), then MaxDiff and conjoint.

---

## 6. What the demo can't show, and what to say instead

Some features can't be shown live because:
- they spend money or reach real people;
- they need weeks of real use;
- they use client files;
- they only appear when something fails.

Each item below says why it isn't in the demo, what to show instead, and a line to say if someone asks.

### Buying sample and running real fieldwork

- **Why not live:** confirming a Prolific order spends real money and recruits real people.
- **Show instead:** the quote card from Act 3. It shows the audience, quota cells, reward, total and balance.
- **Say:**
  > "Publishing locks that total only after a person confirms it. It also checks that the Decipher survey link exists, the balance covers the total, and screen-out pay is accepted. Pause, resume and stop are on the same panel."

### A real bot attack

- **Why not live:** Act 3b uses real people. Nobody in the room can behave like a script, and running a bot against a survey in the meeting isn't something to do on stage.
- **Show instead:** **BrewCo Live Quality Check**. Its Live quality tab holds 5 bot sessions recorded during testing on 16–17 November, alongside honest ones.
- **Say:**
  > "Bots give themselves away in ways people don't: no natural mouse or touch movement, typing at machine speed, or the same device showing up many times. These are runs from our testing. With the setting on, a session with a clear bot signal is ended partway through the survey, before we pay for it."

### Uploading to a survey that's already live

- **Why not live:** each upload changes the company Decipher account.
- **Show instead:** the **Upload to Decipher** card from Act 2, with **Nothing has been sent yet**.
- **Say:**
  > "A survey that's already live is never replaced. A later upload only replaces the XML of a survey that isn't live yet."

### How good the programming is on real client questionnaires

- **Why not live:** the evidence is real client questionnaires and the XML our programmers built from them. They can't go on screen, and each check takes 4–20 minutes per survey.
- **What was measured:**
  - 14 client questionnaires, each imported from Word and programmed;
  - each result was compared with the XML a programmer built by hand for the same survey;
  - the comparison covers question types, answer rows and columns, wording, who sees each question, terminates, piping, ranges and randomisation;
  - on 21 November 2026 the first set of 7 surveys matched at 85.4%, and the 3 newest at 85.2% (up from 79.3% when first measured). A second set of 4 matched 89.8% when last measured;
  - across the first and newest sets, the to-dos left for a programmer fell from 880 to 749.
- **What it doesn't do yet:**
  - it doesn't build Decipher loops, where a block is repeated per brand;
  - quotas and sample-source logic are left for the programmer;
  - hand-programmed surveys also add hidden helper variables that aren't in the questionnaire, and word some answer lists differently. These count against the score even when the survey works.
  
  These are left as clear to-dos in the XML, not guessed.
- **Say:**
  > "On real client questionnaires it passes about 85 to 90 percent of the checks against what our programmers built, and we rerun that comparison after every change. What it can't do yet, it leaves as a to-do for a programmer, so a person still checks every survey before it goes live."

  Don't name the clients or the surveys.

### Learning over time

- **Why not live:** learning shows across many studies, not within one demo.
- **Show instead:** the **Learned rules** page and its **Progress** tab, from Act 9.
- **Say:**
  > "Every correction a researcher makes becomes a rule the next study can use. The Progress tab is how we'll show it's working, with fewer retries and fewer corrections as more studies go through. It's early, so there isn't a trend to read yet."

### What happens when an AI provider fails

- **Why not live:** it only happens when OpenAI has an outage, hits a rate limit or runs out of credit. The backup is a Claude model, which only works while the Anthropic account has credit.
- **Say:**
  > "If the main model's provider fails, the call is retried once on a backup model from the other provider. The reply says when that happened."

### Picking up a long task after it stops

- **Why not live:** you'd have to stop a long import partway through and send it again.
- **Show instead:** the **Stop** button, from Act 9.
- **Say:**
  > "Model answers are kept for 14 days. Sending the same request again reuses the parts that already finished, so a stopped or failed import doesn't start from scratch."

### The full tab book, and data cleaning on real data

- **Why not live:** the full tab book can take up to 20 minutes, and synthetic data doesn't need cleaning.
- **Show instead:**
  - Backup's tab book (Act 5);
  - the `Cleaning test (Brand X)` project (Act 4).

### Our real Google Drive, Slack and Microsoft 365

- **Why not live:** an IT admin has to register the app with each provider once.
- **Show instead:** the stand-in workspace and the setup steps on each card (Act 8b).
- **Say:**
  > "It works the same way with the real services once IT has signed off."

### Not built, if someone asks

- **MaxDiff and conjoint:** refused on purpose, rather than approximated.
- **Panels other than Prolific:** not connected yet.
- **Decipher loops and quotas:** left as programmer to-dos, as described above.
- **Weighted advanced analyses:** driver analysis, segmentation (including the Segments tool) and the significance tests in Act 6 run unweighted. Crosstabs, tab books and the deck are weighted.
- **One Decipher survey in several languages:** each language is built as its own survey XML.
- **Driving Decipher's own test link:** the Logic test simulates the XML locally instead.
