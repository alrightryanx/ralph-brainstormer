import argparse
import subprocess
import os
import sys
import time
import re
import json
import logging
from datetime import datetime

# --- Configuration ---
PLANS_DIR = "plans"
RALPH_DIR = os.path.join(PLANS_DIR, "ralph_brainstorm")

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("RalphBrainstormer")

def clean_output(text):
    """Removes ANSI codes and excess whitespace."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\-_]| [0-?]*[@-~])')
    return ansi_escape.sub('', text).strip()

def call_cli(cli_name, prompt, context_files=None, retries=3, delay=20):
    """
    Executes the specified CLI with exponential backoff for rate limits.
    """
    logger.info(f"[{cli_name.upper()}] Thinking...")
    
    full_prompt = prompt
    if context_files:
        full_prompt += "\n\n--- CONTEXT FROM FILES ---"
        for cf in context_files:
            if os.path.exists(cf):
                with open(cf, 'r', encoding='utf-8') as f:
                    full_prompt += f"\nFile: {os.path.basename(cf)}\n{f.read()}\n"
    
    command = []
    # Windows-specific handling for PowerShell/CMD execution
    is_windows = os.name == 'nt'
    shell_flag = is_windows

    if cli_name == "claude":
        command = ["claude", full_prompt]
    elif cli_name == "gemini":
        if is_windows and os.path.exists("gemini.ps1"):
            command = ["powershell", "-NoProfile", "-File", "gemini.ps1", full_prompt]
        else:
            command = ["gemini", full_prompt]
    elif cli_name == "codex":
        # Force PowerShell execution for codex on Windows to ensure .ps1/npm scripts run correctly
        if is_windows:
             # Use -Command to allow shell execution of 'codex' which might be an alias or script in PATH
             command = ["powershell", "-NoProfile", "-Command", "codex", full_prompt]
        else:
             command = ["codex", full_prompt]

    for attempt in range(retries):
        try:
            result = subprocess.run(
                command, 
                capture_output=True, 
                text=True, 
                encoding='utf-8', 
                timeout=300, 
                shell=False # Shell=True can be dangerous/messy with list args on Windows. We use direct executable calls.
            )
            
            output = clean_output(result.stdout)
            errors = result.stderr.lower() if result.stderr else ""
            
            # Rate Limit & Error Detection
            # Some CLIs print errors to stdout, so we check both.
            combined_log = (output + errors).lower()
            is_limited = any(x in combined_log for x in 
                            ["rate limit", "429", "too many requests", "overloaded", "try again in", "capacity"])
            
            if is_limited:
                wait_time = delay * (2 ** attempt)
                logger.warning(f"[{cli_name.upper()}] Rate limited. Retrying in {wait_time}s... (Attempt {attempt+1}/{retries})")
                time.sleep(wait_time)
                continue

            if result.returncode != 0 and not is_limited:
                # If command not found, try to be helpful
                if "is not recognized" in errors or "command not found" in errors:
                    logger.error(f"Command '{cli_name}' not found. Please ensure it is installed.")
                    return f"Error: {cli_name} command not found."
                # Allow partial output even on error codes, sometimes CLIs are weird
                if output and len(output) > 50:
                    logger.warning(f"[{cli_name.upper()}] returned non-zero exit code but had output. Using it.")
                    return output
                return f"Error generating plan with {cli_name}: {result.stderr}"
            
            if not output.strip():
                 # Empty output is a failure
                 return f"Error: {cli_name} returned empty output."

            return output

        except Exception as e:
            if attempt == retries - 1:
                return f"Exception: {str(e)}"
            time.sleep(delay)
            
    return f"Error: {cli_name.upper()} is consistently rate limited. Skipping."

def save_md(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info(f"Saved: {path}")

def get_rankings(clis, plans, objective, round_num=1):
    """Asks multiple CLIs to rank a list of plans using a rigorous persona."""
    all_plans_text = ""
    for d in plans:
        all_plans_text += f"\n\n=== PLAN ID: {d['id']} ===\n{d['content'][:2500]}...\n"
    
    persona = (
        "You are a PRINCIPAL ARCHITECT and RUTHLESS EVALUATOR."
        "You DO NOT tolerate generic, shallow, or hallucinated solutions. "
        "You value technical depth, feasibility, and specific implementation details over buzzwords."
    )
    
    ranking_prompt = (
        f"{persona}\nObjective: {objective}\n\n"
        f"Review these plans carefully. Rank them from BEST to WORST.\n"
        f"Scoring Criteria (0-100):\n"
        f" - Technical Feasibility (40%)\n"
        f" - Completeness (30%)\n"
        f" - Innovation (30%)\n\n"
        f"CRITICAL: Be extremely strict. A standard generic plan should score < 50.\n"
        f"Return ONLY a JSON object in this format:\n"
        f"{{ \"rank\": [\"id_of_1st_place\", \"id_of_2nd_place\", ...], \"scores\": {{ \"id\": 85, ... }}, \"critique\": \"Brief explanation of choices\" }}\n\n"
        f"{all_plans_text}"
    )
    
    votes = {}
    
    # We rotate the judge to avoid bias, or use all of them
    judges = clis
    
    for cli in judges:
        logger.info(f"Asking {cli.upper()} to judge...")
        resp = call_cli(cli, ranking_prompt)
        try:
            # Extract JSON from potential markdown blocks
            json_match = re.search(r'\{.*\}', resp, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                rank_list = data.get('rank', [])
                
                logger.info(f"[{cli.upper()}] Ranking: {rank_list}")
                
                for idx, pid in enumerate(rank_list):
                    # Borda count: 1st place gets max points (len(plans))
                    # Weighted by rank (higher is better)
                    votes[pid] = votes.get(pid, 0) + (len(plans) - idx)
            else:
                logger.warning(f"[{cli.upper()}] No valid JSON found in response.")
        except Exception as e:
            logger.warning(f"[{cli.upper()}] Ranking parse failed: {e}")
    
    return sorted(votes.items(), key=lambda x: x[1], reverse=True)

def synthesize_ideas(clis, top_plans, objective):
    """Combines the best elements of the top plans into one unified blueprint."""
    logger.info("Synthesizing Top 3 Plans into a Unified Blueprint...")
    
    combined_text = ""
    for i, plan in enumerate(top_plans):
        combined_text += f"\n\n--- SOURCE PLAN {i+1} (ID: {plan['id']}) ---\n{plan['content']}\n"
        
    synthesizer = "claude" # Claude is often good at long context synthesis
    
    prompt = (
        f"You are a PRINCIPAL ENGINEER tasked with creating a UNIFIED MASTER PLAN.\n"
        f"Objective: {objective}\n\n"
        f"I have provided {len(top_plans)} promising drafts below. "
        f"Your job is to MERGE them into a single, cohesive, superior architecture.\n"
        f"MANDATE:\n"
        f"- CROSS-POLLINATE: Explicitly combine Idea A from Agent X with Idea B from Agent Y if they are synergistic.\n"
        f"- RESOLVE CONFLICTS: Choose the technically superior option when plans disagree.\n"
        f"- NO FLUFF: Go straight to architecture, code structure, and implementation steps.\n\n"
        f"{combined_text}"
    )
    
    unified_plan = call_cli(synthesizer, prompt)
    return unified_plan

def run_brainstorm(project_name, objective):
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = os.path.join(RALPH_DIR, project_name, session_id)
    os.makedirs(session_dir, exist_ok=True)
    
    # Ensure CLIs are actual agents, not simulations
    clis = ["claude", "gemini", "codex"]
    
    print("\n" + "="*60)
    print(f"  🚀 RALPH BRAINSTORMER v2: {project_name.upper()}")
    print("="*60 + "\n")

    # 1. DRAFTING PHASE (Collaborative Awareness)
    logger.info("PHASE 1: Generating Initial Drafts (Collaborative Mode)...")
    drafts = []
    
    # We will do 2 rounds. Round 2 sees a summary of Round 1.
    previous_round_summary = ""
    
    for r in range(1, 3): # 2 Rounds
        logger.info(f"Drafting Round {r}...")
        for cli in clis:
            context = ""
            if previous_round_summary:
                context = (
                    f"\n\n--- INTELLIGENCE FROM ROUND 1 ---\n"
                    f"The following ideas were proposed by your peers:\n{previous_round_summary}\n\n"
                    f"INSTRUCTION: Analyze these ideas. IMPROVE upon them. Do not just repeat them. "
                    f"If you see a flaw in another agent's plan, fix it in yours."
                )
            
            prompt = f"Draft #{r} for '{project_name}'. Objective: {objective}. Provide a unique, high-level technical approach.{context}"
            
            plan = call_cli(cli, prompt)
            
            if "Error" in plan and len(plan) < 100:
                logger.warning(f"Skipping empty/error plan from {cli}")
                continue

            path = os.path.join(session_dir, f"round{r}-draft-{cli}.md")
            save_md(path, plan)
            drafts.append({"id": f"{cli}-R{r}", "content": plan, "path": path})
        
        # Summarize Round 1 for Round 2
        if r == 1 and drafts:
             logger.info("Summarizing Round 1 for context...")
             # We want the summary to attribute ideas
             summary_prompt = (
                 "Summarize the key technical approaches in these drafts. "
                 "Format: 'Agent [ID] proposed [Idea]'. "
                 "Identify unique contributions from each."
             )
             summary_context = [d['path'] for d in drafts]
             previous_round_summary = call_cli("gemini", summary_prompt, context_files=summary_context)

    if not drafts:
        logger.error("No drafts generated. Exiting.")
        return

    # 2. RANKING & SELECTION
    logger.info("PHASE 2: Strict Ranking of Drafts...")
    sorted_ids = get_rankings(clis, drafts, objective, round_num=1)
    
    if not sorted_ids:
        logger.error("Ranking failed. Using first 3 drafts.")
        top_3_ids = [d['id'] for d in drafts[:3]]
    else:
        top_3_ids = [x[0] for x in sorted_ids[:3]]
        
    top_3_plans = [d for d in drafts if d['id'] in top_3_ids]
    logger.info(f"Top 3 Selected: {top_3_ids}")

    # 3. SYNTHESIS (Combining Ideas)
    logger.info("PHASE 3: Synthesizing Unified Blueprint...")
    unified_content = synthesize_ideas(clis, top_3_plans, objective)
    unified_path = os.path.join(session_dir, "unified-alpha-plan.md")
    save_md(unified_path, unified_content)

    # 4. CRITIQUE & REFINE (The "Boardroom" Meeting)
    logger.info("PHASE 4: Boardroom Critique & Refinement...")
    
    # Step A: Collect Critiques
    critiques = ""
    for cli in clis:
        logger.info(f"Requesting critique from {cli.upper()}...")
        crit = call_cli(cli, f"Critique this Unified Plan. Identify 3 fatal flaws, missing components, or optimization opportunities. Be harsh.", context_files=[unified_path])
        critiques += f"\n\n### Critique from {cli.upper()}:\n{crit}\n"
        
    critique_path = os.path.join(session_dir, "boardroom-critiques.md")
    save_md(critique_path, critiques)
    
    # Step B: Final Polish (Codex or Gemini applies the fixes)
    logger.info("PHASE 5: Finalizing Master Plan...")
    final_architect = "claude" # Claude is good at final docs
    final_prompt = (
        f"You are the Lead Architect. I have a Unified Plan and a set of Critiques from the senior team.\n"
        f"Your goal: Rewrite the plan into the FINAL VERSION.\n"
        f"- Address the critiques.\n"
        f"- Ensure formatting is perfect (Markdown).\n"
        f"- Add a 'Next Steps' section.\n\n"
        f"Original Plan:\n{unified_content}\n\n"
        f"Critiques:\n{critiques}"
    )
    
    final_plan = call_cli(final_architect, final_prompt)
    master_path = os.path.join(RALPH_DIR, project_name, "FINAL_MASTER_PLAN.md")
    
    # 5. FINAL DECISION
    save_md(master_path, final_plan)
    
    print("\n" + "="*60)
    print(f"  DONE! Master Plan Ready.")
    print(f"  Location: {master_path}")
    print("="*60 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ralph Mode Brainstorming Engine")
    parser.add_argument("--project", required=True, help="Name of the project")
    parser.add_argument("--objective", required=True, help="Goal or prompt for the planning session")
    args = parser.parse_args()
    
    run_brainstorm(args.project, args.objective)