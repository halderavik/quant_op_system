# Report Planner: design

Status: in build (T203). Date: 2026-11-13.

## What it does

The report planner keeps one **report plan** per project. The plan says what each slide of the final deck will show and how its numbers will be computed. It is built passively, the user edits it, and when data arrives the planner cleans the data and updates the plan. One request then runs the plan and produces an editable PowerPoint deck.

```
brief + objectives ──► draft plan ──(questionnaire saved / revised / programmed)──► plan refreshed
                                                                         │
SPSS data arrives ──► cleaning agent (recommend + apply) ──► bases, low-base flags, missing variables ──► plan "data ready"
                                                                         │
"Generate the report" ──► executor calls cross-tab engine / analysis agent / coding agent per slide
                       ──► headlines written from computed numbers only ──► PPTX with native, editable charts
```

## The plan (artifact `report_plan`)

- **Stage:** `draft` (from the questionnaire), `questionnaire_final` (programmed in Decipher), `data_ready` (cleaned data mapped), then `reported`.
- **Storyline sections, in order:**
  1. Title
  2. Objectives and approach
  3. Sample and data (who answered, cleaning, weighting)
  4. One section per study objective, from broad to specific
  5. Deeper analysis (drivers, segmentation and so on)
  6. Open-ended feedback
  7. Key takeaways
  8. Appendix (method, bases, coverage)
- **Each slide has:**
  - title, the question it answers (purpose) and the objectives it serves
  - how its numbers are computed:
    - `distribution`: one question, % of base; optionally by a banner
    - `grid_summary`: items of a grid, as % yes or top-2 box
    - `mean_summary`
    - `nps`
    - `rank_summary`
    - `funnel`: awareness to consideration to purchase to ownership, by brand
    - `profile`: demographics
    - `analysis`: a request for the analysis agent, naming the method
    - `coding`: an open end for the coding agent
    - `text`: written slides
  - the question ids and variables, banner, filter and chart type
  - status (planned, needs data, low base, dropped) and the base n once data exists
  - origin (agent or user) and an edited flag
- **Coverage:** a check that every objective has at least one slide, and every reportable question is used somewhere. A question is either placed on a slide or listed with the reason it isn't reported (screener, attention check, admin). This is how the planner "misses nothing".

## How the plan is made

1. **Rules first:** a deterministic draft from the questionnaire, so a plan exists even without a model key.
   - Each objective's mapped questions become slides by question type: yes/no grid → `grid_summary` (% yes); rating grid → top-2 box and means; 0–10 recommend → `nps`; rank → `rank_summary`; text → `coding`; demographics → `profile`.
   - Analysis is added where the design supports it:
     - a satisfaction or recommendation outcome plus an attribute battery → key driver analysis
     - attitude batteries of 6+ items → segmentation (4–8 segments, profiled)
     - awareness, consideration and purchase grids → a brand funnel
2. **Planner agent:** reads the objectives, the questionnaire and the draft, then refines the storyline: section titles, slide titles, order, and extra analysis. Anything that names an unknown question is dropped.
3. **Coverage check:** fills any gap the agent left.
4. **Merge with user edits:**
   - Slides the user added or edited are kept as they are.
   - Slides the user removed stay removed.
   - Agent slides that the user hasn't touched are replaced by the new draft.

## Data stage

When a dataset becomes active (upload or synthetic):

1. The cleaning agent runs, and its removals are applied. The original file is kept, and a cleaned copy becomes the active dataset.
2. Every slide's variables are mapped to dataset columns. Missing variables mark the slide `needs_data`.
3. Each slide's base is computed. Under 30 is flagged as not reportable; under 50 as directional.
4. Analysis that the bases can't support is flagged. For example, segmentation needs 200 or more.
5. Data facts are recorded on the plan: raw n, removed, final n, weight.

This runs as a visible chat task ("I cleaned the data and updated the report plan…").

## Execution ("Generate the report")

For each slide, in order:

- **Questions:** `distribution`, `profile` and banner splits use the cross-tab engine. Summaries across grid items use the same masking and weighting rules ("Don't know" excluded from scales).
- **Analysis:** the analysis agent runs the slide's request. Its chart specs and key metrics come back.
- **Open ends:** an existing coding result is reused, or the AutoCoder runs.

Then:

- **Headlines:** the writer turns each slide's numbers into a headline and 2–3 bullets. A sentence with a number that isn't in the slide's computed facts is dropped (the same check analysis reports use). Takeaways are written last, from the headlines.
- **PPTX build:**
  - 16:9, Quant OS colours, and the logo on the title slide
  - section dividers
  - native PowerPoint charts (bar, column, stacked, line, scatter), so every chart is editable in PowerPoint
  - heatmaps become native tables
  - base and question text in each slide's footer
- **Outputs:** the report artifact (slide list and PPTX download), and the plan moves to `reported`.

## Editing

- **Panel editor:**
  - change any slide's title, purpose, method, questions, banner or chart
  - add or remove slides and sections, reorder them, and restore removed slides
- **Buttons:** "Update with data" and "Generate report" send the matching chat request, so progress shows in the chat.

## Out of scope for this build

- Editing the plan by chat instruction (the panel covers editing).
- Client-branded templates beyond the Quant OS theme.
- Pulling data from Decipher automatically. The data stage starts when an SPSS file is uploaded or synthetic data is generated.
