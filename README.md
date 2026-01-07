# Ralph Brainstormer 🧠

Ralph Brainstormer is a multi-agent planning engine that uses a "Debate & Consensus" workflow to generate high-quality technical roadmaps. It pits multiple AI models (Claude, Gemini, Codex) against each other to critique, refine, and ultimately agree on a winning plan.

## 🚀 The "Ralph Mode" Workflow v2.0

1.  **Drafting Phase (Collaborative)**: Generates 6 unique plans (2 iterations x 3 AI models).
    *   *New:* Agents are aware of each other's drafts in Round 2. "Claude proposed X, so I will propose Y to complement it."
2.  **Ranking (The Ruthless Judge)**: All models vote on the drafts using a **strict 0-100 scoring system**.
    *   Generic plans are penalized.
    *   Technical depth is rewarded.
3.  **Synthesis (Cross-Pollination)**: The Top 3 winners are merged into a single "Unified Blueprint".
    *   The synthesizer explicitly combines the best ideas from different agents (e.g., "Use Gemini's database schema with Claude's API design").
4.  **Boardroom Critique**: 
    *   Agents act as "Senior Architects" to find fatal flaws in the Unified Blueprint.
5.  **Final Polish**: The plan is rewritten to address all critiques, resulting in a **Master Plan**.

## 🛠 Setup

### Prerequisites
- Python 3.8+
- Access to AI CLIs:
  - **Claude**: `claude` (Claude Code)
  - **Gemini**: `gemini` (Gemini CLI)
  - **Codex**: `codex` (via `npm install -g @shadow/codex` or similar) - **MUST be installed, simulation is disabled.**

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/alrightryanx/ralph-brainstormer.git
   cd ralph-brainstormer
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## 📂 Usage

Run the engine with one click using `run.bat` (Windows) or via terminal:

```bash
python ralph_brainstormer.py --project "MyProject" --objective "Build a decentralized chat app"
```

The final plan will be saved to `plans/ralph_brainstorm/MyProject/FINAL_MASTER_PLAN.md`.

## 📄 License
MIT