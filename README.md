# 🌆 GridWise LLM

## Your Operator Directive → Optimized Schedule

[![BUP CSE Fest 2026](https://img.shields.io/badge/BUP_CSE_FEST-2026-blue)](#)
[![Presentation](https://img.shields.io/badge/Presentation-Video%20Link-red)](https://drive.google.com/drive/folders/1z2A7ljdhnD6J-JHNkV_2gDAxN50XqGo-?usp=sharing)
[![Live Host](https://img.shields.io/badge/LIVE_HOST-LINK-yellow)](https://bup-fest-hackathon-team.onrender.com)

<a href="https://drive.google.com/drive/folders/1z2A7ljdhnD6J-JHNkV_2gDAxN50XqGo-?usp=sharing">🎥 Presentation Video</a>
<a href="https://bup-fest-hackathon-team.onrender.com">📺 Live Host</a>

<b> Team RoopJoti CodeQorche | BUP CSE FEST 2026 </b>

> Turn 1–3 lines of plain-English operator notes into a validated, cost-minimal 24-hour campus energy schedule.

**GridWise LLM** is an energy-optimization service built for the **BUP CSE Fest 2026 Hackathon — Online Preliminary**. It combines an LLM language layer with deterministic validation and mathematical optimization to interpret operator directives and produce a feasible 24-hour energy plan.

The central design principle is simple:

> **The LLM understands language. Deterministic code validates it. The optimizer does the math.**

---

## 🎯 The Challenge

Each scenario provides:

- 24 hours of **demand**
- 24 hours of **solar production**
- 24 hours of **electricity tariffs**
- Battery specifications
- **1–3 operator notes** written in plain English

Some notes affect the energy schedule:

- Cleaning crews may reduce usable solar.
- A maintenance window may prevent battery charging.
- A reserve requirement may restrict battery discharge.

Other notes are deliberately irrelevant:

- A cafeteria menu change, for example, should be recognized as a `no_op` rather than being turned into an invented energy rule.

Hidden test cases can express the same rule using very different wording, so the system is designed for **paraphrase understanding rather than keyword matching**.

### Objective

The optimizer minimizes:

```text
total_cost_bdt
    = Σ grid_kwh[h] · tariff[h]
      for h = 0..23
```

subject to:

- Energy balance for every hour
- Battery physics and limits
- Every applicable operator directive

---

## 🤔 What We're Building

GridWise LLM exposes **one deployed HTTP service with two endpoints**.

### `GET /health`

Returns:

```json
{ "status": "ok" }
```

This endpoint confirms that the service is alive before evaluation begins.

### `POST /optimize-energy`

Accepts one energy scenario containing:

- 24-hour energy data
- Battery configuration
- Operator notes

and returns:

- Structured interpretation of every note
- A validated 24-hour energy plan
- Total grid consumption
- Total cost in BDT
- Peak grid usage
- A concise plan summary

The service is designed so that every note is interpreted by the LLM, validated before optimization, applied to the mathematical model, and checked again before the response is returned.

---

## 🧠 Core Architecture

GridWise LLM deliberately separates **language understanding** from **numerical optimization**.

```text
┌──────────────────────┐
│   Operator Notes     │
│  Plain-English text  │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│   01 · LLM           │
│      Interpreter     │
└──────────┬───────────┘
           │ structured directives
           ▼
┌──────────────────────┐
│   02 · Guardrail     │
│      Validator       │
└──────────┬───────────┘
           │ trusted constraints
           ▼
┌──────────────────────┐
│   03 · Math          │
│      Optimizer       │
└──────────┬───────────┘
           │ candidate plan
           ▼
┌──────────────────────┐
│   04 · Final         │
│      Validator       │
└──────────┬───────────┘
           │ verified plan
           ▼
┌──────────────────────┐
│   05 · API Response  │
└──────────────────────┘
```

The five-stage rule is:

> **Understand → Validate → Compute → Verify → Respond**

The LLM never directly performs the optimization math, and the mathematical optimizer never tries to interpret natural language.

---

## 🧩 The Six Supported Directives

The LLM must map every operator note to exactly one of these six structured directive types.

| Directive                 | Meaning                                     | Structured Adjustment           |
| ------------------------- | ------------------------------------------- | ------------------------------- |
| `structured_adjustment`   | General structured adjustment               | Defined by the supported schema |
| `solar_reduction`         | Reduce usable solar during a time window    | `{hours, factor}`               |
| `minimum_battery_reserve` | Maintain a minimum battery energy level     | `{hours, minimum_energy_kwh}`   |
| `no_charge_window`        | Disable battery charging during a window    | `{hours}`                       |
| `no_discharge_window`     | Disable battery discharging during a window | `{hours}`                       |
| `max_grid_window`         | Cap grid import during a window             | `{hours, max_grid_kwh}`         |
| `no_op`                   | Note does not affect the schedule           | `null`                          |

> The presentation specifies six supported directive types including `no_op`; `structured_adjustment` is the general structured form used by the schema.

Each scenario produces one interpretation entry per note, in `note_index` order.

---

## 🛡️ Guardrail Validation

The LLM output is treated as **untrusted data**.

Before anything reaches the optimizer, deterministic validation checks that:

- The directive type is one of the supported types.
- Every note maps to exactly one entry.
- Entries remain in note order with no duplicates or gaps.
- Hours are unique integers from `0–23`.
- Hour windows are ascending and end-exclusive.
- `solar_reduction.factor` is within `[0, 1]`.
- Reserve and grid-cap values are finite and non-negative.
- `applies = false` is only paired with `no_op`.
- Operator notes cannot modify base demand, tariff, or battery specifications.
- Malformed LLM output results in a controlled fallback rather than a crash or silent guess.

This layer is intentionally deterministic: **no model call, no randomness**.

---

## 📐 Mathematical Optimization

The energy schedule is solved as a **linear program**, one scenario at a time.

### Hourly energy balance

```text
grid[h] + solar_used[h] + discharge[h]
    = demand[h] + charge[h]
```

### Battery state

```text
E[h] = E[h-1] + charge[h] - discharge[h]

minimum_energy ≤ E[h] ≤ capacity
```

### Day boundary

```text
E[23] = initial_energy_kwh
```

The last constraint prevents the optimizer from obtaining free energy by ending the day with an artificially depleted or increased battery state.

### How directives become constraints

Directives do not require separate special-case optimization logic. They tighten the same constraint system:

```text
solar_reduction
    → scale effective solar before solving

minimum_battery_reserve
    → raise the battery-energy floor for listed hours

no_charge_window
    → charge[h] = 0

no_discharge_window
    → discharge[h] = 0

max_grid_window
    → grid_kwh[h] ≤ max_grid_kwh
```

The presentation proposes **OR-Tools / PuLP** for the LP. The variables are continuous and the formulation is convex, allowing fast exact optimization for the 24-hour problem.

---

## 🖥️ How to Run It Locally

Running GridWise LLM locally is straightforward. The project includes shell scripts to make setup and testing easier.

### Option 1: Use `prepare.sh` (Recommended)

The easiest way to prepare the project is to run the included setup script first:

```bash
./prepare.sh
```

This script handles downloading/installing the necessary files and preparing the local environment for the application.

After preparation, you can start the server using the provided `run.sh` script.

### Start the Server

```bash
./run.sh <PORT>
```

For example:

```bash
./run.sh 8080
```

This starts the GridWise LLM server locally on the selected port.

You can then access the application at:

```text
http://localhost:8080
```

Replace `8080` with whichever port you selected.

---

### Option 2: Manual Python Setup

If you prefer to set everything up manually, create a virtual environment and install the dependencies:

```bash
python3 -m venv .venv
```

Activate the environment:

```bash
source .venv/bin/activate
```

Upgrade `pip`:

```bash
pip install --upgrade pip
```

Install the project dependencies:

```bash
pip install -r requirements.txt
```

Install Uvicorn if it is not already included:

```bash
pip install uvicorn
```

You can then start the server directly with Uvicorn:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

The application will be available at:

```text
http://localhost:8080
```

---

## 🧪 Testing the Application

The project uses **Pytest** for automated testing.

Once the environment is prepared, the complete application can be tested using the provided terminal test script:

```bash
./terminal.sh
```

This provides a convenient way to test the application end-to-end from the command line.

## 🐬 Docker

To build with docker, go with

```bash
./build.sh
```

### Running Tests Manually

You can also run the Pytest test suite directly:

```bash
pytest
```

Pytest is already used throughout the project for application testing, and the test suite is intended to verify that the core functionality works correctly.

If you want to run Pytest with more detailed output:

```bash
pytest -v
```

### Typical Local Workflow

A typical local development workflow looks like this:

```text
┌──────────────────────┐
│    Clone Project     │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│    ./prepare.sh      │
│  Prepare dependencies │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│     ./run.sh 8080    │
│     Start Server     │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│   localhost:8080     │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│   ./terminal.sh      │
│   or: pytest -v      │
└──────────────────────┘
```

> **Tip:** `prepare.sh` + `run.sh` + `terminal.sh` provide the quickest workflow, while the manual Python/Uvicorn commands are useful when developing or debugging individual parts of the application.

## 🔁 Final Validation / Replay

The optimizer's output is replayed and checked hour by hour before it is returned.

The final validator confirms:

- Effective solar reductions were applied.
- Battery reserve directives hold.
- No-charge directives hold.
- No-discharge directives hold.
- Grid-cap directives hold.
- Energy balance is satisfied for all 24 hours.
- Charge/discharge rates remain within their hourly limits.
- Battery energy stays within `[minimum_energy_kwh, capacity_kwh]`.
- Final battery energy returns to `initial_energy_kwh`.

The goal is to ensure that the service does not return a plan that would fail the same physical and directive constraints used by the hidden judge.

---

## 📦 API Response

A successful `/optimize-energy` response contains both the interpretation and the resulting schedule.

```json
{
  "scenario_id": "...",
  "directive_interpretation": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "...",
      "structured_adjustment": {},
      "explanation": "..."
    }
  ],
  "hourly_plan": [
    {
      "hour": 0,
      "grid_kwh": 0,
      "solar_used_kwh": 0,
      "battery_action": "charge",
      "battery_kwh": 0,
      "battery_energy_after_kwh": 0
    }
  ],
  "total_grid_kwh": 0,
  "total_cost_bdt": 0,
  "peak_grid_kwh": 0,
  "plan_summary": "..."
}
```

`hourly_plan` contains **24 entries**, one for each hour.

---

## 🧪 Designed for Hidden-Case Paraphrases

The system is built to recognize equivalent instructions even when the wording changes.

For example, these three notes express the same underlying rule:

```text
"PV production will drop to about 20% between 13:00 and 15:00."

"Panel washing from one until three will leave roughly
one-fifth of normal output."

"Expect an 80% reduction in rooftop solar during the
1–3 PM maintenance window."
```

All should resolve to:

```text
directive_type: solar_reduction
hours: [13, 14]
factor: 0.2
```

The **LLM interpreter** absorbs the language variation, while the **guardrail validator** ensures that the resulting structured data remains valid.

---

## 🧮 What the Hidden Judge Checks

Evaluation has two required axes.

### 1. Language Understanding

The system must correctly determine:

- Whether a note applies or is irrelevant.
- The correct directive type.
- Correct hours.
- Correct numerical parameters within tolerance.
- Robustness to paraphrased hidden wording.

### 2. Downstream Application

The interpretation must actually affect the returned schedule.

The judge checks that:

- Directives are enforced in `hourly_plan`.
- All GridWise physics rules remain valid.
- Returned totals are consistent with the generated plan.
- `total_grid_kwh` and `total_cost_bdt` match values recomputed from the plan within the stated `±0.01` tolerance.

A correct interpretation that is not applied to the schedule still fails the case.

---

## 🛠️ Tech Stack

The proposed implementation uses a deliberately small stack:

- **Python**
- **FastAPI**
- **Pydantic**
- **Structured-output LLM**
- **OR-Tools / PuLP**
- **Docker**
- **Public deployment host** such as Render, Fly, or Railway

### Why this architecture?

Each component has one clear responsibility:

| Component       | Responsibility                                  |
| --------------- | ----------------------------------------------- |
| FastAPI         | HTTP service and API contract                   |
| Pydantic        | Request/response and structured-data validation |
| LLM             | Natural-language directive interpretation       |
| Guardrails      | Deterministic validation of LLM output          |
| LP Solver       | Cost-minimal feasible energy schedule           |
| Final Validator | Replay and physics/directive checks             |
| Docker          | Reproducible deployment                         |

---

## 📁 Project Structure

```text
gridwise-llm/
│
├── app/
│   ├── main.py
│   ├── ...
│
├── requirements.txt
├── Dockerfile
├── .env.example
├── .gitignore
└── README.md
```

The exact implementation structure may evolve as the project develops.

---

## ⚙️ Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/your-username/gridwise-llm.git
cd gridwise-llm
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

**Windows**

```bash
.venv\Scripts\activate
```

**Linux / macOS**

```bash
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file based on `.env.example`.

```env
LLM_API_URL=https://your-provider/v1/chat/completions
LLM_API_KEY=your-api-key
LLM_MODEL=your-model-name

LLM_TIMEOUT_SECONDS=20
LLM_MAX_TOKENS=2000
```

The LLM is used for language interpretation. The numerical optimization and validation layers remain deterministic.

### 5. Start the API

```bash
uvicorn app.main:app --reload
```

The API should then be available at:

```text
http://localhost:8000
```

Interactive API documentation:

```text
http://localhost:8000/docs
```

---

## 🐳 Running with Docker

Build the image:

```bash
docker build -t gridwise-llm .
```

Run it:

```bash
docker run --env-file .env -p 8000:8000 gridwise-llm
```

Then open:

```text
http://localhost:8000
```

---

## 🌐 Deployment

The presentation proposes deploying the container to a public host so the hackathon judge harness can call the API directly.

Possible deployment targets include:

- Render
- Fly.io
- Railway

The deployed service should expose:

```text
GET  /health
POST /optimize-energy
```

A live deployment is referenced by the project badge at the top of this README.

---

## 💡 Design Principles

### 1. Never trust the LLM with math

LLMs are useful for interpreting natural language, but the energy model should remain deterministic and auditable.

### 2. Validate before optimizing

No LLM-generated directive should reach the mathematical model without passing schema and constraint validation.

### 3. Apply, don't just explain

A directive is only useful if it changes the optimization constraints and therefore the resulting hourly plan when applicable.

### 4. Replay before responding

The final plan is checked again before it leaves the service.

### 5. Optimize cost under constraints

The objective is to minimize total grid electricity cost while respecting energy balance, battery physics, and applicable operator directives.

---

## 🔮 Future Exploration

Potential extensions include:

- [ ] More accurate energy estimation
- [ ] Support for additional energy/building systems
- [ ] CI/CD or automated scenario integration
- [ ] Build and schedule history
- [ ] Per-stage / per-window energy analysis
- [ ] More advanced optimization suggestions
- [ ] Dashboard and visualization
- [ ] Hardware-aware measurements
- [ ] Team/project-level statistics

These are future directions rather than requirements established by the current presentation.

---

## 🤝 Contributing

Ideas for improving the interpretation model, validation layer, optimization formulation, or deployment are welcome.

For substantial changes, opening an issue first can help keep implementation decisions aligned with the project's architecture.

---

## 📜 License

This project is licensed under the **MIT License**.

See [`LICENSE`](LICENSE) for details.

---

## ❤️ The Idea

GridWise LLM is built around a straightforward separation of concerns:

> **The LLM never touches the math, and the math never guesses at language.**

The result is a small, auditable pipeline that turns human operator notes into structured constraints, solves for a feasible cost-minimal schedule, and verifies the result before returning it.

---

**BUP CSE FEST 2026 · HACKATHON · ONLINE PRELIMINARY**

**GridWise LLM — Operator Directive → Optimized Schedule** ⚡
# bup-fest-hackathon-team-roopjoticodeqorche-xddx
