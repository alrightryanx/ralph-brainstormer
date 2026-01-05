# Ralph Brainstormer 🧠

Ralph Brainstormer is a multi-agent planning engine that uses a "Debate & Consensus" workflow to generate high-quality technical roadmaps. It pits multiple AI models (Claude, Gemini, Codex) against each other to critique, refine, and ultimately agree on a winning plan.

## 🚀 The "Ralph Mode" Workflow

1.  **Drafting Phase**: Generates 9 unique plans (3 iterations x 3 AI models).
2.  **Ranking (Round 1)**: All models vote on the drafts to find the Top 3.
3.  **Expansion**: The Top 3 winners are expanded into detailed Master Plans.
4.  **Agent Debate**: 
    *   **Agent A (Critics)**: Identify 3 critical technical weaknesses per plan.
    *   **Agent B (Solvers)**: Provide detailed technical solutions to those weaknesses.
    *   **Revision**: Both agents create revised "perfect" versions of the plans.
5.  **Final Ranking**: All 9 refined plans (3 Enhanced + 6 Debate) are ranked again.
6.  **Consensus**: All models review the winning plan and provide a final "Verdict" and "Approval".

## 🛠 Setup

### Prerequisites
- Python 3.8+
- Access to AI CLIs:
  - **Claude**: `claude` (Claude Code)
  - **Gemini**: `gemini` (Gemini CLI)
  - **Codex/GPT-4**: `openai` CLI (or simulated via Gemini)

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/alrightryanx/ralph-brainstormer.git
   cd ralph-brainstormer
   ```
2. Install dependencies (if any):
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
